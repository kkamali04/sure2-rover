import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import motion_calibration as calibration
from remote_controller import Controller, ControllerError

ROOT = Path(__file__).resolve().parents[1]


def payload(direction='forward', displacement=100, **changes):
    return dict(action='calibration_trial', direction=direction, pwm=.1, duration_s=1,
                displacement=displacement, stop_distance_mm=None, surface='software floor',
                configuration='software fixture', evidence='software_example',
                duration_source='stopwatch_video', notes='Synthetic test; not physical evidence', **changes)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.controller = Controller(log_path=Path(self.folder.name)/'controller_log.jsonl')
        self.controller.tick()
        self.plan = json.loads((ROOT/'example_plan_2x6.json').read_text())
        self.profile = {k:payload()[k] for k in ('pwm','surface','configuration','evidence','duration_source')}

    def tearDown(self):
        self.controller.close()
        self.folder.cleanup()

    def record(self, direction='forward', displacement=100):
        return self.controller.validation_action(payload(direction, displacement))

    def compile(self):
        return self.controller.validation_action(dict(action='compile_timed_draft', profile=self.profile))

    def test_trials_and_draft_persist_without_actuation_or_invented_measurements(self):
        self.controller.validation_action(dict(action='import_plan', plan=self.plan))
        for value in (90,100,110): self.record('forward', value)
        for value in (85,90,95): self.record('left', value)
        state = self.compile()
        draft = state['timed_route_draft']
        self.assertFalse(draft['hardware_execution_enabled'])
        self.assertIsNone(draft['measured_position'])
        self.assertEqual(draft['sensor_measurements'], [])
        self.assertEqual(len([s for s in draft['steps'] if s['kind']=='estimated_motion']),13)
        self.assertEqual(len([s for s in draft['steps'] if s['kind']=='manual_position_and_height_check']),36)
        self.assertTrue(any(s.get('extrapolated') for s in draft['steps']))
        self.assertEqual(state['calibration_summary'][0]['mean_effective_rate'],100)
        self.assertEqual(state['calibration_summary'][0]['sample_sd'],10)
        saved = json.loads((self.controller.run_directory/'validation.json').read_text())
        self.assertEqual(saved['timed_route_draft'],draft)
        self.assertFalse(self.controller.status()['armed'])
        self.assertEqual(self.controller.status()['desired'],dict(L=0.,R=0.))
        logs=(self.controller.run_directory/'controller_log.jsonl').read_text()
        self.assertIn('manual_motion_calibration',logs)
        self.assertIn('timed_route_draft_prepared',logs)
        self.assertNotIn('"event": "drive"',logs)
        self.record()
        self.assertIsNone(self.controller.validation_status()['timed_route_draft'])

    def test_missing_mismatched_and_stalled_trials_block_draft(self):
        self.controller.validation_action(dict(action='import_plan',plan=self.plan))
        with self.assertRaisesRegex(ControllerError,'3 non-stalled'): self.compile()
        for _ in range(3): self.record('forward')
        with self.assertRaisesRegex(ControllerError,'left'): self.compile()
        for value in (0,90,90): self.record('left',value)
        with self.assertRaisesRegex(ControllerError,'stalled'): self.compile()
        other = dict(self.profile,surface='another floor')
        with self.assertRaises(ControllerError): self.controller.validation_action(dict(action='compile_timed_draft',profile=other))

    def test_invalid_values_and_false_physical_evidence_are_rejected(self):
        for key,value in [('pwm',float('nan')),('pwm',True),('pwm',.5),('duration_s',0),
                          ('displacement',-1),('surface',''),('evidence','physical_manual')]:
            data=payload();data[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ControllerError):
                self.controller.validation_action(data)
        self.assertEqual(self.controller.validation_status()['calibration_trials'],[])

    def test_arming_blocks_recording_and_session_export(self):
        self.controller.action('arm',dict(seq=1))
        with self.assertRaises(ControllerError):self.record()
        with self.assertRaises(ControllerError):self.controller.export_session()
        self.controller.action('stop',dict(seq=2))
        with self.assertRaises(ControllerError):self.record()
        self.controller.tick();self.record()

    def test_bad_profile_cannot_poison_saved_session_even_with_one_station(self):
        self.plan['stations']=self.plan['stations'][:1]
        self.controller.validation_action(dict(action='import_plan',plan=self.plan))
        for value in (None,[],dict(self.profile,pwm=float('nan')),dict(self.profile,evidence=[])):
            with self.assertRaises(ControllerError):
                self.controller.validation_action(dict(action='compile_timed_draft',profile=value))
            self.assertIsNone(self.controller.validation_status()['timed_route_draft'])
            self.assertFalse(self.controller.status()['armed'])

    def test_session_zip_contains_retained_raw_events_and_calibration_without_tokens(self):
        self.record()
        archive=self.controller.export_session()
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIn('controller_log.jsonl',z.namelist())
            report=json.loads(z.read('validation.json'))
            self.assertEqual(len(report['calibration_trials']),1)
            self.assertIn(b'manual_motion_calibration',z.read('controller_log.jsonl'))
            for name in z.namelist():self.assertNotIn(self.controller.token.encode(),z.read(name))

    def test_reverse_and_right_use_their_own_calibration(self):
        p=copy.deepcopy(self.plan)
        p['stations']=[dict(id='A',x_mm=600,y_mm=350,dwell_s=1,departure='reverse'),
                       dict(id='B',x_mm=500,y_mm=350,dwell_s=1),
                       dict(id='C',x_mm=500,y_mm=250,dwell_s=1)]
        rows=[]
        for direction,amount in [('reverse',50),('right',45),('forward',100)]:
            for _ in range(3):rows.append(calibration.trial(payload(direction,amount),rows,'test'))
        draft=calibration.compile_draft(p,rows,self.profile)
        legs=[s for s in draft['steps'] if s['kind']=='estimated_motion']
        self.assertEqual([(s['direction'],s['estimated_seconds']) for s in legs],
                         [('reverse',2),('right',2),('forward',1)])


if __name__=='__main__':unittest.main()
