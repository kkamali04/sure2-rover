"""Offline boundary checks: no hardware is opened or commanded by these tests."""
import argparse
import contextlib
import copy
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rover_test as rover


def sample_plan():
    return {
        "schema": rover.SCHEMA, "units": {"length": "mm", "time": "s"},
        "profile": {
            "chamber": {"width_mm": 1800, "depth_mm": 630, "height_mm": 780},
            "keepout": {"front_mm": 75, "rear_mm": 75, "side_mm": 25},
            "rover": {"length_mm": 194, "width_mm": 168, "height_mm": 100},
            "mount": {"length_mm": 194, "width_mm": 168, "max_height_mm": 600},
            "probe": {"offset_x_mm": 0, "offset_y_mm": 0, "radius_mm": 10, "headroom_mm": 25},
            "measured": False,
        },
        "heights_mm": [150, 350, 550], "settle_s": 2,
        "stations": [{"id": f"S{i + 1}", "x_mm": 122 + i * 311.2, "y_mm": 315, "dwell_s": 5}
                     for i in range(6)],
        "motion": {"heading_deg": 0, "heading_axis": "+X", "origin": "front-left-deck"},
    }


class PlanningBoundaryTests(unittest.TestCase):
    def test_full_18_sample_schedule_and_unmeasured_warning(self):
        result = rover.validate_plan(sample_plan())
        self.assertEqual(len(result["schedule"]), 18)
        self.assertEqual(result["acquisition_seconds"], 126)
        self.assertEqual(result["center_bounds_mm"], {"xmin": 122, "xmax": 1678, "ymin": 159, "ymax": 471})
        self.assertTrue(any("UNMEASURED" in s for s in result["warnings"]))

    def test_envelope_edge_rejects_even_if_probe_is_inside(self):
        plan = sample_plan()
        plan["stations"][0]["x_mm"] = 121.9
        with self.assertRaises(ValueError):
            rover.validate_plan(plan)

    def test_probe_offset_can_make_otherwise_valid_rover_position_invalid(self):
        plan = sample_plan()
        plan["profile"]["probe"]["offset_x_mm"] = 150
        with self.assertRaises(ValueError):
            rover.validate_plan(plan)

    def test_assembly_and_sensor_height_are_both_checked(self):
        for field, value in [("max_height_mm", 800), ("max_height_mm", 500)]:
            plan = sample_plan()
            plan["profile"]["mount"][field] = value
            with self.assertRaises(ValueError):
                rover.validate_plan(plan)

    def test_infinite_boolean_and_wrong_units_rejected(self):
        for value in [float("nan"), float("inf"), True, "122"]:
            plan = sample_plan()
            plan["stations"][0]["x_mm"] = value
            with self.assertRaises(ValueError):
                rover.validate_plan(plan)
        plan = sample_plan()
        plan["units"]["length"] = "m"
        with self.assertRaises(ValueError):
            rover.validate_plan(plan)

    def test_derived_export_values_are_ignored(self):
        plan = sample_plan()
        plan["derived"] = {"valid": True, "xmin": 0, "xmax": 1800}
        plan["stations"][0]["x_mm"] = 50
        with self.assertRaises(ValueError):
            rover.validate_plan(plan)


class MotionBoundaryTests(unittest.TestCase):
    def args(self, **updates):
        values = dict(left=0.10, right=0.10, seconds=0.25, live=False, serial="FAKE", host=None)
        values.update(updates)
        return argparse.Namespace(**values)

    def test_default_jog_never_constructs_transport(self):
        factory = Mock(side_effect=AssertionError("Must not open transport"))
        with contextlib.redirect_stdout(io.StringIO()):
            code = rover.jog(self.args(), factory)
        self.assertEqual(code, 0)
        factory.assert_not_called()

    def test_out_of_bounds_commands_never_construct_transport(self):
        for update in [dict(left=0.251), dict(right=-0.251), dict(seconds=1.001),
                       dict(seconds=0), dict(left=float("nan")), dict(right=float("inf"))]:
            factory = Mock()
            with self.assertRaises(ValueError):
                rover.jog(self.args(live=True, **update), factory)
            factory.assert_not_called()

    def test_keyboard_interrupt_during_motion_still_sends_three_stops(self):
        transport = Mock()
        commands = []
        def send(command):
            commands.append(copy.deepcopy(command))
            if command["L"]:
                raise KeyboardInterrupt()
        transport.send.side_effect = send
        with patch.object(rover.time, "sleep"), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = rover.jog(self.args(live=True), lambda args: transport)
        self.assertEqual(code, 130)
        self.assertEqual(commands[-3:], [rover.STOP] * 3)
        self.assertEqual(len(commands), 7)
        transport.close.assert_called_once()

    def test_failed_preflight_prevents_nonzero_command(self):
        transport = Mock()
        commands = []
        def send(command):
            commands.append(copy.deepcopy(command))
            raise OSError("disconnected")
        transport.send.side_effect = send
        with patch.object(rover.time, "sleep"), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = rover.jog(self.args(live=True), lambda args: transport)
        self.assertEqual(code, 1)
        self.assertEqual(commands, [rover.STOP] * 6)

    def test_success_has_only_one_motion_command(self):
        transport = Mock()
        with patch.object(rover.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            code = rover.jog(self.args(live=True), lambda args: transport)
        self.assertEqual(code, 0)
        commands = [call.args[0] for call in transport.send.call_args_list]
        self.assertEqual(sum(bool(c["L"] or c["R"]) for c in commands), 1)
        self.assertEqual(commands[-3:], [rover.STOP] * 3)

    def test_stop_zeros_are_floating_point(self):
        self.assertIsInstance(rover.STOP["L"], float)
        self.assertIsInstance(rover.STOP["R"], float)


if __name__ == "__main__":
    unittest.main()
