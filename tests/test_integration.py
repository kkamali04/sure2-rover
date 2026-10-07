"""Independent planner-export / Python-runner integration checks.

Run from the kit directory: python -m unittest discover -s tests -p 'test_integration.py' -v
No test opens a device or sends a network request.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


KIT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ciq_rover_test", KIT / "rover_test.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def example_plan():
    """Use the actual distributed planner example, not a duplicated fixture."""
    for path in sorted(KIT.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(data, dict) and data.get("schema") == runner.SCHEMA:
            return path, data
    raise AssertionError("No exported example mission JSON found beside the planner")


class PlannerRunnerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example_path, cls.original = example_plan()

    def setUp(self):
        self.plan = copy.deepcopy(self.original)

    def test_actual_planner_example_is_six_by_three(self):
        result = runner.validate_plan(self.plan)
        self.assertEqual((result["stations"], result["heights"]), (6, 3))
        self.assertEqual(len(result["schedule"]), 18)
        self.assertEqual(result["chamber_mm"], (1800, 630, 780))
        self.assertEqual(len(set(s["y_mm"] for s in self.plan["stations"])), 1)
        for station in self.plan["stations"]:
            samples = [s for s in result["schedule"] if s["station"] == station["id"]]
            self.assertEqual([s["sensor_z_mm"] for s in samples], self.plan["heights_mm"])

    def test_mm_axes_and_sensor_offset_are_preserved(self):
        result = runner.validate_plan(self.plan)
        probe = self.plan["profile"]["probe"]
        stations = {s["id"]: s for s in self.plan["stations"]}
        for sample in result["schedule"]:
            station = stations[sample["station"]]
            self.assertEqual(sample["x_mm"], station["x_mm"])
            self.assertEqual(sample["y_mm"], station["y_mm"])
            self.assertAlmostEqual(sample["sensor_x_mm"], station["x_mm"] + probe["offset_x_mm"])
            self.assertAlmostEqual(sample["sensor_y_mm"], station["y_mm"] + probe["offset_y_mm"])

    def test_dwell_is_per_sample_and_settle_is_separate(self):
        self.plan["stations"][0]["dwell_s"] = 7.25
        self.plan["settle_s"] = 1.5
        result = runner.validate_plan(self.plan)
        first = result["schedule"][0]
        self.assertEqual(first["sample_start_s"], 1.5)
        self.assertEqual(first["sample_end_s"], 8.75)
        expected = sum(3 * (s["dwell_s"] + 1.5) for s in self.plan["stations"])
        self.assertAlmostEqual(result["acquisition_seconds"], expected)

    def test_station_outside_deck_rejected_even_with_forged_bounds(self):
        self.plan["stations"][0]["x_mm"] = -1
        self.plan["center_bounds_mm"] = dict(xmin=-1e9, xmax=1e9, ymin=-1e9, ymax=1e9)
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_original_tall_mount_cannot_fit(self):
        self.plan["profile"]["mount"]["max_height_mm"] = 1064.4
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_original_wide_mount_cannot_fit(self):
        self.plan["profile"]["mount"].update(length_mm=760, width_mm=760)
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_offset_sensor_cannot_cross_wall(self):
        self.plan["profile"]["probe"]["offset_y_mm"] = 10000
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_height_above_chamber_rejected(self):
        self.plan["heights_mm"][0] = 10000
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_nan_infinity_and_boolean_coordinates_rejected(self):
        for bad in [float("nan"), float("inf"), -float("inf"), True, "200"]:
            with self.subTest(value=bad):
                plan = copy.deepcopy(self.original)
                plan["stations"][0]["x_mm"] = bad
                with self.assertRaises(ValueError):
                    runner.validate_plan(plan)

    def test_nan_from_json_file_rejected(self):
        self.plan["heights_mm"][0] = float("nan")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nan.json"
            path.write_text(json.dumps(self.plan), encoding="utf-8")
            with self.assertRaises(ValueError):
                runner.dry_run(path)

    def test_units_and_heading_rejected_when_incompatible(self):
        self.plan["units"]["length"] = "m"
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)
        self.plan = copy.deepcopy(self.original)
        self.plan["motion"]["heading_deg"] = 90
        with self.assertRaises(ValueError):
            runner.validate_plan(self.plan)

    def test_y_changes_warn_that_turning_model_is_missing(self):
        result = runner.validate_plan(self.plan)
        bounds = result["center_bounds_mm"]
        current = self.plan["stations"][0]["y_mm"]
        alternate = bounds["ymin"] if current != bounds["ymin"] else bounds["ymax"]
        self.assertNotEqual(alternate, current, "Example needs nonzero usable Y range")
        self.plan["stations"][0]["y_mm"] = alternate
        warnings = runner.validate_plan(self.plan)["warnings"]
        self.assertTrue(any("turn" in text.lower() for text in warnings))

    def test_plan_dry_run_never_opens_hardware_or_network(self):
        with patch.object(runner.SerialTransport, "open", side_effect=AssertionError("Serial used")), \
             patch.object(runner.HttpTransport, "open", side_effect=AssertionError("HTTP used")), \
             patch.object(runner, "urlopen", side_effect=AssertionError("Network used")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.dry_run(self.example_path), 0)
        self.assertIn("18 planned samples", output.getvalue())
        self.assertIn("no hardware commands", output.getvalue())

    def test_jog_is_dry_without_explicit_live(self):
        args = SimpleNamespace(left=0.10, right=0.10, seconds=0.25, live=False)
        def forbidden_factory(_):
            self.fail("Dry jog constructed a live transport")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.jog(args, factory=forbidden_factory), 0)


if __name__ == "__main__":
    unittest.main()
