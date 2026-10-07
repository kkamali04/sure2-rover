#!/usr/bin/env python3
"""Local browser controller for stock WAVE ROVER; starts disarmed.

Default is simulation. --live explicitly enables the selected rover transport.
Only the dedicated motor worker writes commands; HTTP request threads update
bounded desired state. Position and wheel speed are never inferred from PWM.
"""
from __future__ import annotations

import argparse
import hmac
import hashlib
import ipaddress
import io
import json
import logging
import math
import secrets
import threading
import time
import webbrowser
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from rover_test import STOP, SerialTransport
from validation_run import ValidationRun
from telemetry import Telemetry, decode_response
from hardware_owner import HardwareOwner
from session_storage import SessionHandler, register, finish

MAX_BODY = 2048
MAX_SEQ = 2**53 - 1
TRANSPORT_TIMEOUT_S = 0.25


class ControllerError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError("Unexpected redirect from rover; verify its configured IP")


class RoverHTTP:
    """One short HTTP request per command, sent directly to a literal rover IP."""
    def __init__(self, host):
        parsed = urlsplit(host if "://" in host else "http://" + host)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("Use the rover's HTTP IP address, e.g. 192.168.4.1")
        ipaddress.ip_address(parsed.hostname)
        self.base = "http://" + parsed.netloc
        # Local rover traffic must not be forwarded through an OS proxy.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def open(self):
        pass

    def send(self, command):
        query = urlencode({"json": json.dumps(command, separators=(",", ":"))})
        with self.opener.open(self.base + "/js?" + query, timeout=TRANSPORT_TIMEOUT_S) as response:
            if response.status != 200:
                raise OSError(f"Rover HTTP status {response.status}")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise OSError('Rover response exceeds 64 KB')
            return dict(http_status=response.status, **decode_response(raw))
        # HTTP 200 means request accepted, not proof of wheel movement or stop.

    def close(self):
        pass


class RoverSerial(SerialTransport):
    def open(self):
        super().open()
        self.connection.timeout = TRANSPORT_TIMEOUT_S
        self.connection.write_timeout = TRANSPORT_TIMEOUT_S


class SimulatedTransport:
    def open(self):
        pass

    def send(self, command):
        pass

    def close(self):
        pass


class Controller:
    """Thread-safe desired state with exactly one motor-writer worker.

    `tick()` may be called manually by offline tests instead of starting the
    worker. A writer lock prevents overlapping sends even if called twice.
    """
    def __init__(self, transport=None, *, live=False, pwm_cap=0.25,
                 deadman_s=0.35, period_s=0.1, clock=time.monotonic, log_path=None):
        if not math.isfinite(pwm_cap) or not 0.05 <= pwm_cap <= 0.25:
            raise ValueError("PWM cap must be >= 0.05 and <= 0.25")
        if live and transport is None:
            raise ValueError("Live mode requires an explicit rover transport")
        self.transport = transport if live and transport is not None else SimulatedTransport()
        self.live = bool(live)
        self.pwm_cap = pwm_cap
        self.deadman_s = deadman_s
        self.period_s = period_s
        self.clock = clock
        self.telemetry = Telemetry(clock)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.writer_lock = threading.Lock()
        self.wake = threading.Event()
        self.quit = threading.Event()
        self.neutral_done = threading.Event()
        self.thread = None
        self.opened = False
        self.seq = 0
        self.generation = 0
        self.armed = False
        self.desired = (0.0, 0.0)
        self.last_input = None
        self.last_sent = None
        self.last_command = dict(STOP)
        self.neutral_pending = True
        self.transport_state = "connecting" if live else "simulated"
        self.error = ""
        self.reason = "Startup: neutral transmission pending"
        self.last_stop_reason = self.reason
        self.telemetry_queue = []
        self.telemetry_inflight = False
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
        self.run_directory = None
        self.logger = None
        if log_path:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.logger = logging.Logger("containmentiq-controller-" + secrets.token_hex(4))
            handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=1, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
            self.run_directory = path.resolve().parent / "test_runs" / self.run_id
            self.run_directory.mkdir(parents=True, exist_ok=True)
            register(self.run_directory, 'live_controller' if self.live else 'simulator')
            session_handler = SessionHandler(self.run_directory / "controller_log.jsonl")
            session_handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(session_handler)
        self.validation = ValidationRun(self.run_id, self.live, self.clock, self._log, self.run_directory)
        self._log("session_started", software_sha256={name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                  for name in ("remote_controller.py", "remote_controller.html", "validation_run.py", "validation_panel.js", "motion_calibration.py", "station_trials.py", "telemetry.py", "hardware_owner.py", "ContainmentIQ_Cabinet_Planner.html")
                  if (Path(__file__).parent / name).is_file()})
        self._log('retention_policy', maximum_sessions=10, maximum_total_bytes=90_000_000,
                  event_log_limit='4 MB plus one 4 MB backup per session; oldest events rotate')

    def _log(self, event, **data):
        if self.logger:
            self.logger.info(json.dumps(dict(data, time=datetime.now(timezone.utc).isoformat(),
                                            event=event, live=self.live, run_id=self.run_id), allow_nan=False))

    def _latch_stop(self, reason):
        self.last_stop_reason = reason
        self.telemetry_queue.clear()
        if self.armed or self.reason != reason:
            self._log("stop_latched", reason=reason)
        self.validation.cancel(reason)
        self.armed = False
        self.desired = (0.0, 0.0)
        self.last_input = None
        self.generation += 1
        self.neutral_pending = True
        self.neutral_done.clear()
        self.reason = reason
        self.wake.set()

    def _expire(self):
        if (self.armed and any(self.desired) and self.last_input is not None
                and self.clock() - self.last_input >= self.deadman_s):
            self._latch_stop("Browser heartbeat expired; re-arm required")

    def _status(self):
        return dict(run_id=self.run_id, recording=bool(self.logger), timer_active=self.validation.active is not None, live=self.live, armed=self.armed, pwm_cap=self.pwm_cap,
                    deadman_ms=round(self.deadman_s * 1000), seq=self.seq,
                    last_command=dict(self.last_command), desired=dict(L=self.desired[0], R=self.desired[1]),
                    transport_state=self.transport_state, neutral_pending=self.neutral_pending,
                    age_ms=None if self.last_sent is None else round(max(0, self.clock() - self.last_sent) * 1000),
                    input_age_ms=None if self.last_input is None else round(max(0, self.clock() - self.last_input) * 1000),
                    error=self.error, reason=self.reason, last_stop_reason=self.last_stop_reason,
                    telemetry_busy=bool(self.telemetry_queue) or self.telemetry_inflight, telemetry=self.telemetry.status())

    def request_telemetry(self, payload):
        if payload != {'action': 'read'}:
            raise ControllerError('Expected action=read only', 422)
        with self.lock:
            if self.armed or self.neutral_pending or self.validation.active or self.transport_state not in {'ready', 'simulated'}:
                raise ControllerError('STOP and wait for neutral before reading telemetry', 409)
            if self.telemetry_queue or self.telemetry_inflight:
                raise ControllerError('Telemetry read already pending', 409)
            if self.live and not isinstance(self.transport, RoverHTTP):
                raise ControllerError('This telemetry read requires HTTP transport', 422)
            self.telemetry_queue = [130, 126]
            self._log('telemetry_requested', commands=[130, 126])
            self.wake.set()
            return self._status()

    def status(self):
        with self.lock:
            # Read-only status: the writer owns periodic deadman enforcement.
            return self._status()

    def validation_action(self, payload):
        with self.lock:
            try:
                return self.validation.action(payload, armed=self.armed, neutral_pending=self.neutral_pending,
                                              ready=self.transport_state in {"ready", "simulated"})
            except (ValueError, KeyError, TypeError) as error:
                raise ControllerError(str(error), 422) from error

    def validation_status(self):
        with self.lock:
            return dict(self.validation.status(), telemetry=self.telemetry.status())

    def export_session(self):
        with self.lock:
            if self.armed or self.neutral_pending or self.validation.active:
                raise ControllerError('STOP and finish/cancel timers before exporting the session', 409)
            if not self.run_directory:
                raise ControllerError('This controller was started without disk logging', 409)
            for handler in self.logger.handlers:
                handler.flush()
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
                # Fixed allowlist; never include tokens, arbitrary files or another session.
                for name in ('session.json', 'validation.json', 'controller_log.jsonl.1', 'controller_log.jsonl'):
                    path = self.run_directory / name
                    if path.is_file() and not path.is_symlink():
                        bundle.writestr(name, path.read_bytes())
                bundle.writestr('EXPORT_NOTE.txt',
                    'Snapshot of this local session. Raw commands/responses and operator records are evidence, '
                    'not proof of position or sensor acquisition. Logs are bounded and older events may have '
                    'rotated out. Export important tests before starting more sessions. No credentials included.\n')
            return archive.getvalue()

    def session(self):
        self._log('local_session_connected', note='Browser bootstrap/reconnect; explicit rearming required, existing evidence retained')
        return dict(token=self.token, **self.status())

    def action(self, action, payload):
        if action not in {"arm", "drive", "stop", "disarm"}:
            raise ControllerError("Unknown action", 404)
        if not isinstance(payload, dict):
            raise ControllerError("JSON body must be an object")
        allowed = {"seq", "left", "right"} if action == "drive" else {"seq"}
        if action in {'stop', 'disarm'} and 'reason' in payload:
            allowed.add('reason')
            if not isinstance(payload['reason'], str) or not 1 <= len(payload['reason']) <= 240:
                raise ControllerError('Stop reason must be 1..240 characters')
        if set(payload) != allowed:
            raise ControllerError("Unexpected or missing request fields")
        seq = payload.get("seq")
        if type(seq) is not int or not 1 <= seq <= MAX_SEQ:
            raise ControllerError("seq must be an integer from 1 to 9007199254740991")
        left = right = 0.0
        if action == "drive":
            values = []
            for key in ("left", "right"):
                value = payload[key]
                try:
                    finite_value = float(value) if type(value) in (int, float) else float("nan")
                except OverflowError:
                    finite_value = float("nan")
                if not math.isfinite(finite_value) or abs(finite_value) > self.pwm_cap:
                    raise ControllerError(f"{key} must be finite PWM within +/-{self.pwm_cap}", 422)
                values.append(finite_value)
            left, right = values
        with self.lock:
            self._expire()
            if seq <= self.seq:
                raise ControllerError("Stale sequence rejected; refresh session state", 409)
            # A valid newer request consumes its sequence even if arming is denied.
            self.seq = seq
            if action in {"stop", "disarm"}:
                self._latch_stop(payload.get('reason', "Stopped by operator; re-arm required"))
            elif action == "arm":
                if self.telemetry_queue or self.telemetry_inflight:
                    raise ControllerError('Wait for the stopped-state telemetry read to finish', 409)
                if self.validation.active:
                    raise ControllerError("Cancel or finish the sample timer before arming", 409)
                if self.armed:
                    raise ControllerError("Already armed; release controls or STOP before re-arming", 409)
                if self.neutral_pending or self.transport_state not in {"ready", "simulated"}:
                    raise ControllerError("Wait for a successful neutral transmission before arming", 409)
                self.armed = True
                self.desired = (0.0, 0.0)
                self.last_input = None
                self.generation += 1
                self.reason = "Armed and idle; hold a direction to drive"
            else:
                if not self.armed:
                    raise ControllerError("Controller is disarmed; explicit ARM required", 409)
                if (left or right) and self.neutral_pending:
                    raise ControllerError("Neutral transmission pending; try again once ready", 409)
                self.desired = (left, right)
                self.last_input = self.clock() if left or right else None
                self.generation += 1
                if not (left or right):
                    self.neutral_pending = True
                    self.neutral_done.clear()
                    self.reason = "Armed and idle; neutral requested"
                else:
                    self.reason = "Driving by commanded PWM; position is unknown"
                self.wake.set()
            snapshot = self._status()
        self._log(action, seq=seq, requested=dict(L=left, R=right))
        return snapshot

    def tick(self):
        if not self.writer_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                self._expire()
                self.validation.tick()
                if not self.neutral_pending and not (self.armed and any(self.desired)) and not self.telemetry_queue:
                    return
                if (not self.neutral_pending and self.last_sent is not None
                        and (self.last_command["L"] or self.last_command["R"])
                        and self.clock() - self.last_sent < self.period_s):
                    return
            try:
                if not self.opened:
                    self.transport.open()
                    self.opened = True
                # Re-read after opening: STOP or a timeout may have invalidated
                # a previously observed drive while the connection was opening.
                with self.lock:
                    self._expire()
                    if self.neutral_pending:
                        command = dict(STOP)
                    elif self.armed and any(self.desired):
                        command = {"T": 1, "L": self.desired[0], "R": self.desired[1]}
                    elif not self.armed and self.telemetry_queue:
                        command = {'T': self.telemetry_queue.pop(0)}
                        self.telemetry_inflight = True
                    else:
                        return
                    generation = self.generation
                # No state lock during blocking I/O: STOP requests stay responsive.
                # An already in-flight write cannot be withdrawn; neutral follows.
                self._log('command_attempt', command=command, generation=generation)
                response = self.transport.send(command)
                with self.lock:
                    if isinstance(response, dict):
                        self.telemetry.receive(response)
                        self._log('rover_response', command=command, **response)
                    if command['T'] != 1:
                        self.telemetry_inflight = False
                        self._log('telemetry_read_completed', command=command, simulated=not self.live)
                        return
                    if self.transport_state == 'error':
                        self._log('transport_recovered', note='Neutral only; explicit rearming required')
                    self.last_command = command
                    self.last_sent = self.clock()
                    self.transport_state = "ready" if self.live else "simulated"
                    self.error = ""
                    if not (command["L"] or command["R"]):
                        if generation == self.generation:
                            self.neutral_pending = False
                            self.neutral_done.set()
                            if not self.armed:
                                self.reason += "; neutral command transmitted"
                    elif generation != self.generation:
                        # A more recent stop/release wins over the in-flight send.
                        if not any(self.desired) or not self.armed:
                            self.neutral_pending = True
                            self.neutral_done.clear()
                            self.wake.set()
                    self._expire()
                self._log("command", command=command, generation=generation)
            except Exception as error:
                with self.lock:
                    self._latch_stop("Transport failure; re-arm required after neutral succeeds")
                    self.transport_state = "error"
                    self.error = str(error)[:400]
                    self.telemetry.fault = self.error
                self._log("transport_error", error=str(error)[:400])
                try:
                    self.transport.close()
                except Exception:
                    pass
                self.opened = False
        finally:
            with self.lock:
                self.telemetry_inflight = False
            self.writer_lock.release()

    def _run(self):
        try:
            while not self.quit.is_set():
                self.wake.clear()
                self.tick()
                # Bound neutral retries after connection faults; never retry motion.
                if self.status()["transport_state"] == "error":
                    # The failure itself sets wake; do not turn that into an
                    # unbounded retry loop on immediate connection refusals.
                    self.quit.wait(0.25)
                else:
                    self.wake.wait(self.period_s)
        finally:
            try:
                self.transport.close()
            except Exception:
                pass

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Controller worker already started")
        self.thread = threading.Thread(target=self._run, name="rover-motor-writer", daemon=True)
        self.thread.start()

    def close(self):
        with self.lock:
            self._latch_stop("Controller shutdown")
        if self.thread and self.thread.is_alive():
            self.neutral_done.wait(0.8)
            self.quit.set()
            self.wake.set()
            self.thread.join(timeout=1.0)
        self._log("session_closed", final_state=self.status())
        if self.logger:
            for handler in self.logger.handlers:
                handler.close()
        finish(self.run_directory)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, controller, directory=None):
        if address[0] != "127.0.0.1":
            raise ValueError("Controller must bind to 127.0.0.1")
        self.controller = controller
        self.directory = Path(directory or Path(__file__).resolve().parent)
        super().__init__(address, ControllerHandler)


class ControllerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(2.0)

    def log_message(self, format, *args):
        pass

    def _host(self):
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise ControllerError("Invalid local Host", 403)
        return host

    def _reply(self, code, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        try:
            self._host()
            path = urlsplit(self.path).path
            if path == "/api/session":
                self._reply(200, self.server.controller.session())
            elif path == "/api/status":
                self._reply(200, self.server.controller.status())
            elif path == "/api/session-export":
                self._reply(200, self.server.controller.export_session(), 'application/zip')
            elif path == "/calibration-test-plan":
                self._reply(200, (Path(__file__).parent / 'CALIBRATION_TEST_PLAN.md').read_bytes(), 'text/plain; charset=utf-8')
            elif path == "/api/validation":
                self._reply(200, self.server.controller.validation_status())
            elif path in {"/", "/planner", "/validation_panel.js", "/preview/vendor/three.min.js", "/preview/assets.js", "/preview/scene.js"}:
                name = "ContainmentIQ_Cabinet_Planner.html" if path in {"/", "/planner"} else path.lstrip("/")
                file = self.server.directory / name
                if not file.is_file():
                    raise ControllerError("Missing local application file", 404)
                self._reply(200, file.read_bytes(), "text/html; charset=utf-8" if path in {"/", "/planner"} else "text/javascript; charset=utf-8")
            elif path in {"/debug", "/debug.html", "/remote_controller.html"}:
                file = self.server.directory / "remote_controller.html"
                if not file.is_file():
                    raise ControllerError("remote_controller.html is missing from the kit", 404)
                self._reply(200, file.read_bytes(), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self._reply(204, b"")
            else:
                raise ControllerError("Not found", 404)
        except ControllerError as error:
            self._reply(error.status, {"error": str(error)})

    def do_POST(self):
        body_read = False
        try:
            host = self._host()
            if self.headers.get("Origin") != "http://" + host:
                raise ControllerError("Only this controller's local origin is allowed", 403)
            token = self.headers.get("X-Controller-Token", "")
            if not hmac.compare_digest(token.encode("utf-8"), self.server.controller.token.encode("ascii")):
                raise ControllerError("Invalid controller session token", 403)
            if self.headers.get_content_type() != "application/json":
                raise ControllerError("POST requires application/json", 415)
            if self.headers.get("Transfer-Encoding"):
                raise ControllerError("Chunked request bodies are not accepted", 400)
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise ControllerError("Valid Content-Length required", 411) from error
            path = urlsplit(self.path).path
            body_limit = 1_000_000 if path == "/api/validation" else MAX_BODY
            if not 1 <= length <= body_limit:
                raise ControllerError(f"Request body must be 1..{body_limit} bytes", 413)
            raw = self.rfile.read(length)
            body_read = True
            if len(raw) != length:
                raise ControllerError("Incomplete request body")
            try:
                payload = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeDecodeError, RecursionError) as error:
                raise ControllerError("Invalid finite JSON body") from error
            path = urlsplit(self.path).path
            if path == "/api/validation":
                self._reply(200, self.server.controller.validation_action(payload))
                return
            if path == '/api/telemetry':
                self._reply(200, self.server.controller.request_telemetry(payload))
                return
            if path not in {"/api/arm", "/api/drive", "/api/stop", "/api/disarm"}:
                raise ControllerError("Not found", 404)
            self._reply(200, self.server.controller.action(path.rsplit("/", 1)[1], payload))
        except ControllerError as error:
            # Windows can reset a socket closed with an unread request body,
            # dropping our 403/409 response. Drain only bounded, framed bodies;
            # authentication still happens before any parsing or state change.
            if not body_read and not self.headers.get("Transfer-Encoding"):
                try:
                    pending = int(self.headers.get("Content-Length", "0"))
                    if 0 < pending <= MAX_BODY:
                        self.rfile.read(pending)
                except (ValueError, TimeoutError, ConnectionError, OSError):
                    pass
            self.server.controller._log("request_rejected", path=urlsplit(self.path).path, status=error.status, error=str(error))
            self._reply(error.status, {**self.server.controller.status(), "error": str(error)})
        except (TimeoutError, ConnectionError, OSError):
            self.close_connection = True

    def do_OPTIONS(self):
        self._reply(403, {"error": "Cross-origin access is disabled"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Enable physical rover commands, initially DISARMED")
    mode.add_argument("--simulate", action="store_true", help="Explicit simulation (also the default)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--host", default=None, help="Rover HTTP IP; default 192.168.4.1")
    target.add_argument("--serial", help="USB serial port, e.g. COM4")
    parser.add_argument("--port", type=int, default=8765, help="Local page port (binds only 127.0.0.1)")
    parser.add_argument("--pwm-cap", type=float, default=0.25, help="Maximum normalized PWM, from 0.05 to 0.25")
    parser.add_argument("--log", default="controller_log.jsonl", help="Local rotating JSONL log, max 5 MB + one backup")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be 1024..65535")
    controller = None
    server = None
    owner = None
    try:
        if args.live:
            owner = HardwareOwner()
        transport = RoverSerial(args.serial) if args.serial else RoverHTTP(args.host or "192.168.4.1")
        controller = Controller(transport, live=args.live, pwm_cap=args.pwm_cap, log_path=args.log)
        server = LocalServer(("127.0.0.1", args.port), controller)
        controller._log("transport_selected", transport="simulation" if not args.live else "serial" if args.serial else "http", target=None if not args.live else args.serial or args.host or "192.168.4.1", local_port=args.port, pwm_cap=args.pwm_cap)
        controller.start()
        url = f"http://127.0.0.1:{args.port}"
        print(f"{'LIVE transport enabled' if args.live else 'SIMULATION: no rover commands'}; controller starts DISARMED.")
        print(f"Open {url}; close other rover-control clients. Ctrl+C stops and exits.", flush=True)
        print(f"Session record: {controller.run_directory}", flush=True)
        print("Command acceptance is not measured movement. Keep physical power cutoff accessible.", flush=True)
        if args.open_browser:
            webbrowser.open(url + ("/debug" if args.live else "/"))
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("Stopping controller...")
    except (ValueError, OSError) as error:
        print(f"Controller could not start: {error}")
        return 1
    finally:
        if controller:
            controller.close()
        if server:
            server.server_close()
        if owner:
            owner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
