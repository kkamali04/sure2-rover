import json
from pathlib import Path
import tempfile
import unittest

from remote_controller import Controller, ControllerError


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 0.0
        self.controller = Controller(clock=lambda: self.now, log_path=Path(self.temp.name)/'controller_log.jsonl')
        self.controller.tick()
        self.plan = json.loads((Path(__file__).resolve().parents[1]/'example_plan.json').read_text())

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def import_plan(self):
        return self.controller.validation_action(dict(action='import_plan', plan=self.plan))

    def arrive(self, index=0):
        return self.controller.validation_action(dict(action='arrived', index=index,
                confirmation='timing_only', notes='Software-only test, no physical arrival'))

    def test_observations_and_full_session_logs_persist_without_tokens(self):
        self.controller.validation_action(dict(action='observation', check='Left pivot', result='fail', notes='No wheel rotation'))
        self.controller.validation_action(dict(action='ui_event', message='Keys: KeyW + KeyD'))
        directory = self.controller.run_directory
        saved = json.loads((directory/'validation.json').read_text())
        self.assertEqual(saved['observations'][0]['evidence'], 'operator_report')
        self.assertEqual(saved['observations'][0]['result'], 'fail')
        events = (directory/'controller_log.jsonl').read_text()
        self.assertIn('operator_observation', events)
        self.assertIn('ui_event', events)
        self.assertNotIn(self.controller.token, events)

    def test_schedule_uses_actual_plan_and_ignores_forged_derived_data(self):
        self.plan['stations'][0].update(x_mm=260, dwell_s=1.5)
        self.plan['derived']['samples'] = []
        report = self.import_plan()
        self.assertEqual(len(report['schedule']), 18)
        self.assertEqual(report['schedule'][0]['x_mm'], 260)
        self.assertEqual(report['schedule'][0]['dwell_s'], 1.5)

    def test_timer_requires_neutral_and_blocks_arming_until_complete(self):
        self.import_plan()
        self.controller.action('arm', {'seq': 1})
        with self.assertRaises(ControllerError): self.arrive()
        self.controller.action('stop', {'seq': 2})
        with self.assertRaises(ControllerError): self.arrive()
        self.controller.tick()
        self.arrive()
        with self.assertRaises(ControllerError): self.controller.action('arm', {'seq': 3})
        self.now = 1.9; self.controller.tick()
        self.assertEqual(self.controller.validation_status()['timer']['phase'], 'settle')
        self.now = 2.0; self.controller.tick()
        self.assertEqual(self.controller.validation_status()['timer']['phase'], 'dwell')
        self.now = 6.99; self.controller.tick()
        self.assertEqual(self.controller.validation_status()['next_index'], 0)
        self.now = 7; self.controller.tick()
        result = self.controller.validation_status()
        self.assertEqual(result['next_index'], 1)
        self.assertFalse(result['samples'][0]['sensor_measurement_taken'])
        self.assertFalse(self.controller.status()['armed'])
        self.assertEqual(self.controller.status()['last_command']['L'], 0)

    def test_stop_cancels_timer_and_requires_new_arrival_confirmation(self):
        self.import_plan(); self.arrive()
        self.controller.action('stop', {'seq': 1})
        self.now = 100; self.controller.tick()
        result = self.controller.validation_status()
        self.assertIsNone(result['timer'])
        self.assertEqual(result['next_index'], 0)
        self.assertEqual(result['samples'][0]['result'], 'cancelled')

    def test_invalid_or_duplicate_actions_do_not_advance_or_replace_records(self):
        self.import_plan(); self.arrive()
        with self.assertRaises(ControllerError): self.arrive()
        self.now = 7; self.controller.tick()
        with self.assertRaises(ControllerError): self.arrive(0)
        with self.assertRaises(ControllerError): self.import_plan()
        with self.assertRaises(ControllerError):
            self.controller.validation_action(dict(action='observation', check='x', result='pass', notes='', host='192.168.4.1'))

    def test_transport_failure_cancels_timer_without_claiming_completion(self):
        self.import_plan(); self.arrive()
        self.controller._latch_stop('Transport failure')
        self.now = 100; self.controller.tick()
        report = self.controller.validation_status()
        self.assertEqual(report['next_index'], 0)
        self.assertEqual(report['samples'][0]['result'], 'cancelled')

    def test_invalid_geometry_rejected_before_any_timer(self):
        self.plan['stations'][0]['x_mm'] = -100
        with self.assertRaises(ControllerError): self.import_plan()
        self.assertIsNone(self.controller.validation_status()['plan'])


if __name__ == '__main__':
    unittest.main()
