"""Planning math only: no rover, serial, network or actuation."""
import copy
import json
from pathlib import Path
import unittest
from rover_test import validate_plan


class RoutePreviewTests(unittest.TestCase):
    def plan(self):
        p = json.loads((Path(__file__).parents[1] / 'example_plan.json').read_text())
        p['motion']['heading_axis'] = 'route'
        p['stations'] = [dict(id=f'S{i+1}', x_mm=x, y_mm=y, dwell_s=1)
                         for i, (x, y) in enumerate([(400, 250), (1400, 250), (1400, 380), (400, 380)])]
        return p

    def test_two_left_turns_and_rotated_probe_targets(self):
        p = self.plan()
        p['profile']['probe']['offset_x_mm'] = 40
        result = validate_plan(p)
        self.assertEqual([r['turn_deg'] for r in result['route_preview']], [0, 90, 90, 0])
        self.assertAlmostEqual(result['schedule'][3]['sensor_x_mm'], 1400)
        self.assertAlmostEqual(result['schedule'][3]['sensor_y_mm'], 290)
        self.assertAlmostEqual(result['schedule'][6]['sensor_x_mm'], 1360)

    def test_backward_keeps_heading_and_wrong_fixed_turn_is_rejected(self):
        p = self.plan()
        p['stations'] = [dict(id='A', x_mm=700, y_mm=300, dwell_s=1, departure='reverse'),
                         dict(id='B', x_mm=400, y_mm=300, dwell_s=1)]
        r = validate_plan(p)['route_preview'][0]
        self.assertTrue(r['reverse'])
        self.assertEqual(r['turn_deg'], 0)
        p = self.plan()
        p['stations'][1]['departure'] = 'right90'
        with self.assertRaisesRegex(ValueError, 'does not point'):
            validate_plan(p)

    def test_turn_sweep_is_stricter_than_fixed_heading_footprint(self):
        p = self.plan()
        p['stations'][0]['y_mm'] = 175
        p['motion']['heading_axis'] = '+X'
        validate_plan(p)
        p['motion']['heading_axis'] = 'route'
        with self.assertRaises(ValueError):
            validate_plan(p)

    def test_bad_presets_and_coincident_stations_fail(self):
        for action in ['strafe', [], None, 1]:
            p = self.plan()
            p['stations'][0]['departure'] = action
            with self.assertRaises(ValueError):
                validate_plan(p)
        p = self.plan()
        p['stations'][1].update(x_mm=400, y_mm=250)
        with self.assertRaisesRegex(ValueError, 'different XY'):
            validate_plan(p)
