import copy
import json
import math
from pathlib import Path
import unittest
from remote_controller import Controller, ControllerError
from station_trials import trial_record, summarize


class StationTests(unittest.TestCase):
    def setUp(self):
        self.plan=json.loads((Path(__file__).resolve().parents[1]/'example_plan.json').read_text())
        self.plan['stations'][0]['x_mm']=250
        self.payload=dict(action='station_trial',station='S1',trial=1,actual_x_mm=253,actual_y_mm=319,
                          heading_deg=0,approach='+X',observed_dwell_s=None,uncertainty_mm=1,
                          notes='Software fixture with ruler datum example',evidence='software_example')

    def test_errors_repeatability_and_evidence_separation(self):
        first=trial_record(self.payload,self.plan,[],'now')
        self.assertEqual(first['radial_error_mm'],5)
        self.assertFalse(first['sensor_measurement_taken'])
        self.assertIsNone(first['observed_dwell_s'])
        second=trial_record(dict(self.payload,trial=2,actual_x_mm=247,actual_y_mm=311),self.plan,[first],'now')
        group=summarize([first,second])[0]
        self.assertEqual(group['bias_x_mm'],0)
        self.assertEqual(group['bias_y_mm'],0)
        self.assertEqual(group['radial_rms_error_mm'],5)
        self.assertAlmostEqual(group['sample_sd_x_mm'],math.sqrt(18))
        self.assertIsNone(summarize([first])[0]['sample_sd_x_mm'])
        physical=trial_record(dict(self.payload,evidence='physical_manual'),self.plan,[first],'now')
        self.assertEqual(len(summarize([first,physical])),2)

    def test_heading_rotates_probe_offset_without_claiming_measurement(self):
        self.plan['profile']['probe']['offset_x_mm']=20
        row=trial_record(dict(self.payload,heading_deg=90),self.plan,[],'now')
        self.assertAlmostEqual(row['inferred_probe_x_mm'],253)
        self.assertAlmostEqual(row['inferred_probe_y_mm'],339)
        self.assertIn('not an independent',row['probe_position_source'])

    def test_rejects_empty_nonfinite_duplicate_and_forged_targets(self):
        for update in [dict(actual_x_mm=None),dict(actual_y_mm=float('nan')),dict(trial=True),dict(heading_deg=181),dict(target_x_mm=0)]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                trial_record(dict(self.payload,**update),self.plan,[],'now')
        row=trial_record(self.payload,self.plan,[],'now')
        with self.assertRaises(ValueError): trial_record(self.payload,self.plan,[row],'now')

    def test_station_records_require_stopped_state_and_lock_plan(self):
        c=Controller();c.tick()
        c.validation_action(dict(action='import_plan',plan=self.plan))
        c.action('arm',dict(seq=1))
        with self.assertRaises(ControllerError):c.validation_action(self.payload)
        c.action('stop',dict(seq=2))
        with self.assertRaises(ControllerError):c.validation_action(self.payload)
        c.tick();report=c.validation_action(self.payload)
        self.assertEqual(len(report['station_trials']),1)
        self.assertEqual(report['next_index'],0)
        with self.assertRaises(ControllerError):c.validation_action(dict(action='import_plan',plan=self.plan))


if __name__=='__main__': unittest.main()
