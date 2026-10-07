#!/usr/bin/env python3
"""ContainmentIQ stock WAVE ROVER planning and deliberately bounded bench tests.

No coordinate-navigation implementation is present. Stock T:1 inputs are PWM,
not speeds or distances. A plan is always simulated, never dispatched as motion.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

SCHEMA = "containmentiq.cabinet-plan.v1"
MAX_JOG_SECONDS = 1.0
MAX_JOG_PWM = 0.25  # Firmware's 0.5 is 100%; this cap is 50%, not 25%.
STOP = {"T": 1, "L": 0.0, "R": 0.0}
IO_TIMEOUT_S = 0.5


def number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def validate_plan(plan):
    """Recompute all limits from base dimensions; never trust derived exports."""
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError(f"Expected schema {SCHEMA}")
    units = plan.get("units", {})
    if not isinstance(units, dict):
        raise ValueError("units must be an object")
    if units.get("length") != "mm" or units.get("time") != "s":
        raise ValueError("Expected units.length='mm' and units.time='s'")
    try:
        p = plan["profile"]
        chamber, keepout = p["chamber"], p["keepout"]
        rover, mount, probe = p["rover"], p["mount"], p["probe"]
        w = number(chamber["width_mm"], "chamber.width_mm", 1)
        d = number(chamber["depth_mm"], "chamber.depth_mm", 1)
        h = number(chamber["height_mm"], "chamber.height_mm", 1)
        side = number(keepout["side_mm"], "keepout.side_mm", 0)
        front = number(keepout["front_mm"], "keepout.front_mm", 0)
        rear = number(keepout["rear_mm"], "keepout.rear_mm", 0)
        length = max(number(rover["length_mm"], "rover.length_mm", 1),
                     number(mount["length_mm"], "mount.length_mm", 1))
        width = max(number(rover["width_mm"], "rover.width_mm", 1),
                    number(mount["width_mm"], "mount.width_mm", 1))
        rover_h = number(rover["height_mm"], "rover.height_mm", 1)
        mount_h = number(mount["max_height_mm"], "mount.max_height_mm", rover_h)
        radius = number(probe["radius_mm"], "probe.radius_mm", 0)
        headroom = number(probe["headroom_mm"], "probe.headroom_mm", 0)
        offset_x = number(probe["offset_x_mm"], "probe.offset_x_mm")
        offset_y = number(probe["offset_y_mm"], "probe.offset_y_mm")
        settle = number(plan["settle_s"], "settle_s", 0)
        heights = plan["heights_mm"]
        stations = plan["stations"]
        motion = plan["motion"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"Missing or malformed required plan field: {error}") from error
    if not isinstance(motion, dict):
        raise ValueError("motion must be an object")
    if motion.get("heading_axis") not in {"+X", "route"} or motion.get("origin") != "front-left-deck":
        raise ValueError("Expected +X or route heading, origin='front-left-deck'")
    if number(motion.get("heading_deg"), "motion.heading_deg") != 0:
        raise ValueError("Only fixed 0-degree heading geometry is supported")
    if mount_h > h - headroom:
        raise ValueError("Mount exceeds chamber height minus overhead clearance")
    # Rectangle footprint plus independently offset spherical probe clearance.
    xmin = max(side + length / 2, side + radius - offset_x)
    xmax = min(w - side - length / 2, w - side - radius - offset_x)
    ymin = max(front + width / 2, front + radius - offset_y)
    ymax = min(d - rear - width / 2, d - rear - radius - offset_y)
    routed = motion.get("heading_axis") == "route"
    if routed:
        turn_radius = max(math.hypot(length, width) / 2,
                          math.hypot(offset_x, offset_y) + radius)
        xmin, xmax = side + turn_radius, w - side - turn_radius
        ymin, ymax = front + turn_radius, d - rear - turn_radius
    if xmin > xmax or ymin > ymax:
        raise ValueError("Rover/mount/probe envelope does not fit inside usable deck")
    if not isinstance(heights, list) or not 1 <= len(heights) <= 100:
        raise ValueError("heights_mm must contain 1..100 sensor heights")
    zmin = rover_h + radius
    zmax = min(mount_h - radius, h - headroom - radius)
    checked_heights = [number(z, f"heights_mm[{i}]", zmin, zmax)
                       for i, z in enumerate(heights)]
    if not isinstance(stations, list) or not 1 <= len(stations) <= 1000:
        raise ValueError("stations must contain 1..1000 station objects")
    checked, ids = [], set()
    for i, station in enumerate(stations):
        if not isinstance(station, dict):
            raise ValueError(f"stations[{i}] must be an object")
        sid = station.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError(f"stations[{i}].id must be a unique nonempty string")
        ids.add(sid)
        x = number(station.get("x_mm"), f"{sid}.x_mm", xmin, xmax)
        y = number(station.get("y_mm"), f"{sid}.y_mm", ymin, ymax)
        dwell = number(station.get("dwell_s"), f"{sid}.dwell_s", 0)
        checked.append(dict(id=sid, x=x, y=y, dwell=dwell,
                            departure=station.get("departure", "auto")))
    route = route_preview(checked) if routed else []
    warnings = ["Geometry checks do not establish motion accuracy or mechanical reach."]
    if p.get("measured") is not True:
        warnings.append("UNMEASURED PROFILE: measure this cabinet and assembled mount before use.")
    if max(s["y"] for s in checked) - min(s["y"] for s in checked) > 1e-6:
        warnings.append("Y varies: turning calibration and physical swept-path verification are required before motion.")
    if routed:
        warnings.append("Direction presets are planning-only. Conservative rectangular turn clearance is not physical validation.")
    if len(set(checked_heights)) != len(checked_heights):
        warnings.append("Repeated sensor heights are present.")
    schedule = []
    elapsed = 0.0
    for index, station in enumerate(checked):
        heading = math.radians(route[index]["heading_deg"] if routed else 0)
        sensor_x = station["x"] + math.cos(heading) * offset_x - math.sin(heading) * offset_y
        sensor_y = station["y"] + math.sin(heading) * offset_x + math.cos(heading) * offset_y
        for z in checked_heights:
            start = elapsed
            elapsed += settle + station["dwell"]
            if not math.isfinite(elapsed):
                raise ValueError("Cumulative sample duration is not finite")
            schedule.append(dict(station=station["id"], x_mm=station["x"],
                                 y_mm=station["y"], sensor_x_mm=round(sensor_x, 3),
                                 sensor_y_mm=round(sensor_y, 3), sensor_z_mm=z,
                                 settle_s=settle, dwell_s=station["dwell"],
                                 sample_start_s=start + settle, sample_end_s=elapsed))
    return dict(schedule=schedule, acquisition_seconds=elapsed, warnings=warnings, route_preview=route,
                center_bounds_mm=dict(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax),
                chamber_mm=(w, d, h), stations=len(checked), heights=len(checked_heights))


def route_preview(stations):
    """Recompute uncalibrated pose intent; never dispatch motion commands."""
    heading, result = 0., []
    norm = lambda angle: (angle + 180) % 360 - 180
    for index, station in enumerate(stations):
        action = station["departure"]
        if not isinstance(action, str) or action not in {"auto", "forward", "reverse", "left", "right", "left90", "right90"}:
            raise ValueError(f"{station['id']}: unknown direction preset")
        before, turn, reverse = heading, 0., False
        if index < len(stations) - 1:
            following = stations[index + 1]
            dx, dy = following["x"] - station["x"], following["y"] - station["y"]
            if math.hypot(dx, dy) < .001:
                raise ValueError("Consecutive stations must have different XY coordinates")
            target = math.degrees(math.atan2(dy, dx))
            turn = norm(target - heading)
            if action == "reverse":
                if abs(norm(target - heading - 180)) > .01:
                    raise ValueError(f"{station['id']}: Backward does not point toward next station")
                turn, reverse = 0., True
            elif action == "forward":
                if abs(turn) > .01:
                    raise ValueError(f"{station['id']}: Straight does not point toward next station")
            elif action in {"left90", "right90"}:
                expected = 90 if action == "left90" else -90
                if abs(norm(turn - expected)) > .01:
                    raise ValueError(f"{station['id']}: turn preset does not point toward next station")
                turn = expected
            elif action == "left" and turn < 0:
                turn += 360
            elif action == "right" and turn > 0:
                turn -= 360
            heading = norm(heading + turn)
        result.append(dict(station_id=station["id"], from_heading_deg=before,
                           heading_deg=heading, turn_deg=turn, reverse=reverse,
                           action=action, hardware_ready=False))
    return result


def dry_run(path):
    with Path(path).open(encoding="utf-8") as stream:
        result = validate_plan(json.load(stream))
    print("DRY RUN ONLY: no port opened, no network request, no hardware commands.")
    print("Travel, lift motion and sensor acquisition are not implemented.")
    w, d, h = result["chamber_mm"]
    print(f"Plan interior: {w:g} x {d:g} x {h:g} mm (X / Y / Z).")
    for warning in result["warnings"]:
        print(f"CHECK: {warning}")
    print("Station    rover X     rover Y    probe X    probe Y    probe Z   settle   dwell")
    for sample in result["schedule"]:
        print(f"{sample['station']:<9.9} {sample['x_mm']:9.2f} {sample['y_mm']:11.2f} "
              f"{sample['sensor_x_mm']:10.2f} {sample['sensor_y_mm']:10.2f} "
              f"{sample['sensor_z_mm']:10.2f} {sample['settle_s']:8.2f} {sample['dwell_s']:7.2f}")
    print(f"{result['stations']} stations x {result['heights']} heights = "
          f"{len(result['schedule'])} planned samples.")
    print(f"Settle + dwell only: {result['acquisition_seconds']:g} s; "
          "travel, lift and unconfirmed sensor overhead are excluded.")
    print("Stock WAVE ROVER has no wheel encoders: this file cannot be used as exact goto motion.")
    return 0


class SerialTransport:
    def __init__(self, port):
        self.port = port
        self.connection = None

    def open(self):
        try:
            import serial
        except ImportError as error:
            raise RuntimeError("USB mode needs pyserial: python -m pip install -r requirements.txt") from error
        # Set line states before opening; an OS/adapter may still toggle reset lines.
        conn = serial.Serial(baudrate=115200, timeout=IO_TIMEOUT_S,
                             write_timeout=IO_TIMEOUT_S, dsrdtr=False, rtscts=False)
        conn.rts = False
        conn.dtr = False
        conn.port = self.port
        self.connection = conn
        conn.open()

    def send(self, command):
        payload = (json.dumps(command, separators=(",", ":")) + "\n").encode("ascii")
        count = self.connection.write(payload)
        if count != len(payload):
            raise OSError("Incomplete serial command write")

    def close(self):
        if self.connection is not None:
            self.connection.close()


class HttpTransport:
    def __init__(self, host):
        parsed = urlsplit(host if "://" in host else "http://" + host)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("--host must be a rover address such as http://192.168.4.1")
        self.base = parsed.scheme + "://" + parsed.netloc

    def open(self):
        pass

    def send(self, command):
        query = urlencode({"json": json.dumps(command, separators=(",", ":"))})
        with urlopen(self.base + "/js?" + query, timeout=IO_TIMEOUT_S) as response:
            if response.status != 200:
                raise OSError(f"Rover HTTP status {response.status}")

    def close(self):
        pass


def make_transport(args):
    if args.serial:
        return SerialTransport(args.serial)
    if args.host:
        return HttpTransport(args.host)
    raise ValueError("Select exactly one transport: --serial PORT or --host ROVER_IP")


def send_stops(transport, attempts=3):
    """Attempt each stop even if an earlier stop failed; no hardware ACK is assumed."""
    errors = []
    successes = 0
    for attempt in range(attempts):
        try:
            transport.send(STOP)
            successes += 1
        except (Exception, KeyboardInterrupt) as error:
            errors.append(str(error) or type(error).__name__)
        if attempt + 1 < attempts:
            try:
                time.sleep(0.05)
            except KeyboardInterrupt:
                # Another Ctrl+C must not skip remaining neutral attempts.
                pass
    return successes, errors


def validate_jog(left, right, seconds):
    left = number(left, "left PWM", -MAX_JOG_PWM, MAX_JOG_PWM)
    right = number(right, "right PWM", -MAX_JOG_PWM, MAX_JOG_PWM)
    seconds = number(seconds, "jog seconds", 0.02, MAX_JOG_SECONDS)
    return {"T": 1, "L": left, "R": right}, seconds


def jog(args, factory=make_transport):
    command, seconds = validate_jog(args.left, args.right, args.seconds)
    print(f"Command: {json.dumps(command)}; requested host interval {seconds:g} s.")
    print("PWM units: 0.5 = 100% duty; 0.25 = 50%. This does not specify speed or distance.")
    if not args.live:
        print("DRY RUN: no hardware connection. Add --live only after wheels-raised checks.")
        return 0
    print("LIVE BENCH JOG. Keep the physical power switch/cutoff within reach.", flush=True)
    transport = factory(args)
    opened = False
    exit_code = 0
    try:
        transport.open()
        opened = True
        # Neutral first; deliberate settling accommodates a board reset on USB open.
        neutral, errors = send_stops(transport)
        if neutral != 3:
            raise RuntimeError("Pre-jog stop transmission failed: " + "; ".join(errors))
        time.sleep(0.3)
        deadline = time.monotonic() + seconds
        # One finite motion request only. Do not implement an endless heartbeat.
        transport.send(command)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
    except KeyboardInterrupt:
        print("Interrupted; attempting stop.", file=sys.stderr)
        exit_code = 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        exit_code = 1
    finally:
        if opened:
            successes, errors = send_stops(transport)
            print(f"Stop transmissions accepted by host transport: {successes}/3.")
            print("Transport success is not proof the motors stopped; verify physically.")
            if errors:
                print("STOP TRANSMISSION FAILURE: " + "; ".join(errors), file=sys.stderr)
                print("Use the physical power cutoff immediately if moving.", file=sys.stderr)
                exit_code = exit_code or 1
        try:
            transport.close()
        except Exception as error:
            print(f"Close failed: {error}", file=sys.stderr)
            exit_code = exit_code or 1
    return exit_code


def stop(args, factory=make_transport):
    transport = factory(args)
    try:
        transport.open()
        successes, errors = send_stops(transport)
        print(f"STOP transmissions accepted by host transport: {successes}/3.")
        print("Verify the motors have stopped. If still moving, use physical power cutoff.")
        if errors:
            print("Errors: " + "; ".join(errors), file=sys.stderr)
        return 0 if successes == 3 else 1
    finally:
        transport.close()


def list_ports():
    try:
        from serial.tools import list_ports as serial_ports
    except ImportError as error:
        raise RuntimeError("Port listing needs pyserial: python -m pip install -r requirements.txt") from error
    ports = list(serial_ports.comports())
    for port in ports:
        print(f"{port.device}: {port.description}")
    if not ports:
        print("No serial ports found. Connect the internal driver-board USB port using a data cable.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"dry-run", "jog", "stop", "ports", "-h", "--help"}
    # A JSON pathname alone is a dry run by default.
    if argv and argv[0] not in commands:
        argv.insert(0, "dry-run")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    plan_parser = sub.add_parser("dry-run", help="Validate and print a mission; never connects")
    plan_parser.add_argument("plan", help="JSON exported by the local planner")
    sub.add_parser("ports", help="List USB serial ports without opening them")
    jog_parser = sub.add_parser("jog", help="Bounded PWM bench command; dry-run unless --live")
    jog_parser.add_argument("--left", type=float, default=0.10)
    jog_parser.add_argument("--right", type=float, default=0.10)
    jog_parser.add_argument("--seconds", type=float, default=0.25)
    jog_parser.add_argument("--live", action="store_true", help="Explicitly permit this one physical jog")
    stop_parser = sub.add_parser("stop", help="Send real neutral commands immediately")
    for p in (jog_parser, stop_parser):
        transport = p.add_mutually_exclusive_group(required=p is stop_parser)
        transport.add_argument("--serial", metavar="PORT", help="USB port, e.g. COM4 or /dev/ttyUSB0")
        transport.add_argument("--host", metavar="ROVER_IP", help="e.g. 192.168.4.1")
    args = parser.parse_args(argv)
    owner = None
    try:
        if args.action == 'stop' or (args.action == 'jog' and args.live):
            from hardware_owner import HardwareOwner
            owner = HardwareOwner()
        if args.action == "dry-run":
            return dry_run(args.plan)
        if args.action == "ports":
            return list_ports()
        if args.action == "jog":
            return jog(args)
        return stop(args)
    except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    finally:
        if owner:
            owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
