import http.server
import json
import tempfile
import threading
import subprocess
import sys
import unittest
import contextlib
import io
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from remote_controller import RoverHTTP, Controller, ControllerError
from telemetry import Telemetry,decode_response
from telemetry_capture import capture
from hardware_owner import HardwareOwner
from hardware_check import bounded_check,main,ask_observation
from telemetry_capture import main as telemetry_main


class TelemetryTests(unittest.TestCase):
    def test_json_null_motor_reply_is_absent_feedback_not_a_sensor_failure(self):
        r=decode_response(b'null');self.assertIsNone(r['parsed']);self.assertIsNone(r['parse_error'])
        t=Telemetry(lambda:0);t.receive(r)
        self.assertTrue(all(f['value'] is None for f in t.status()['fields']))

    def test_busy_capture_prints_recovery_steps_without_opening_rover(self):
        with patch('telemetry_capture.HardwareOwner',side_effect=OSError('Close the other PowerShell window')), \
             patch('telemetry_capture.RoverHTTP',side_effect=AssertionError('Network attempted')):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(telemetry_main(['--capture']),2)
            self.assertIn('TELEMETRY NOT STARTED',output.getvalue())
            self.assertNotIn('Traceback',output.getvalue())

    def test_busy_real_cli_process_exits_cleanly_before_any_hardware_connection(self):
        owner=None
        try:
            try:owner=HardwareOwner()
            except OSError:pass  # An existing owner also provides the conflict; never close it.
            result=subprocess.run([sys.executable,'telemetry_capture.py','--capture','--host','127.0.0.1:9','--seconds','1'],
                                  cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertIn('Ctrl+C',result.stdout)
            self.assertIn('Closing only the browser',result.stdout)
            self.assertNotIn('Traceback',result.stderr)
        finally:
            if owner:owner.close()

    def test_stop_during_inflight_read_cancels_second_read_and_never_arms(self):
        entered=threading.Event();release=threading.Event();commands=[]
        class SlowRead(RoverHTTP):
            def __init__(self):pass
            def send(self,c):
                commands.append(c)
                if c['T']==130:
                    entered.set();release.wait(2)
                return decode_response(b'null')
        c=Controller(SlowRead(),live=True);c.tick();c.request_telemetry({'action':'read'})
        worker=threading.Thread(target=c.tick);worker.start()
        try:
            self.assertTrue(entered.wait(1))
            c.action('stop',{'seq':1})
            with self.assertRaises(ControllerError):c.action('arm',{'seq':2})
        finally:release.set();worker.join(2)
        c.tick()
        self.assertEqual([x['T'] for x in commands],[1,130,1])
        self.assertFalse(c.armed);self.assertFalse(c.status()['telemetry_busy'])

    def test_controller_reads_telemetry_only_stopped_and_blocks_rearm_until_done(self):
        class RecordedRover(RoverHTTP):
            def __init__(self):self.commands=[]
            def send(self,c):
                self.commands.append(c)
                return decode_response(b'{"T":1001,"v":10.34080029}' if c['T']==130 else b'{"T":1002,"r":0.169825897}' if c['T']==126 else b'null')
        motor=RecordedRover();c=Controller(motor,live=True);c.tick()
        c.action('arm',{'seq':1})
        with self.assertRaises(ControllerError):c.request_telemetry({'action':'read'})
        c.action('stop',{'seq':2,'reason':'Window lost focus. Controls disarmed.'});c.tick()
        self.assertIn('Window lost focus',c.status()['last_stop_reason'])
        c.request_telemetry({'action':'read'})
        with self.assertRaises(ControllerError):c.action('arm',{'seq':3})
        c.tick();c.tick()
        self.assertFalse(c.status()['telemetry_busy']);self.assertFalse(c.status()['armed'])
        self.assertEqual([x['T'] for x in motor.commands],[1,1,130,126])
        self.assertEqual(next(f for f in c.status()['telemetry']['fields'] if f['field']=='v')['value'],10.34080029)
        c.action('arm',{'seq':4});self.assertTrue(c.armed)

    def test_stop_cancels_queued_telemetry_and_takes_priority(self):
        c=Controller();c.tick();c.request_telemetry({'action':'read'})
        c.action('stop',{'seq':1});c.tick()
        self.assertFalse(c.status()['telemetry_busy']);self.assertEqual(c.status()['last_command']['T'],1)

    def test_move_stop_dwell_uses_requested_time_without_claiming_distance(self):
        commands=[];events=[];now=[0.]
        class Motor:
            def send(self,c):commands.append(c)
        bounded_check(Motor(),'w',lambda e,**k:events.append((e,k)),sleep=lambda seconds:now.__setitem__(0,now[0]+seconds),clock=lambda:now[0],pwm=.2,seconds=.5,dwell_s=2)
        self.assertEqual(commands[1],dict(T=1,L=.2,R=.2))
        self.assertAlmostEqual(now[0],2.6)
        self.assertEqual(events[-1][0],'stopped_dwell_completed')
        self.assertFalse(events[-1][1]['sensor_measurement_taken'])
        with self.assertRaises(ValueError):bounded_check(Motor(),'w',lambda *a,**k:None,pwm=.5)

    def test_result_prompt_retries_movement_key_instead_of_losing_the_run(self):
        answers=iter(['s','pass both sides turned and stopped'])
        self.assertEqual(ask_observation(lambda _:next(answers))[0],'pass')
    def test_missing_stale_response_and_sensor_age_are_distinct(self):
        now=[0.]
        t=Telemetry(lambda:now[0]);self.assertTrue(all(r['value'] is None for r in t.status()['fields']))
        t.receive(decode_response(b'{"T":1001,"v":12.1,"L":0.1,"y":0}'))
        now[0]=1;t.receive(decode_response(b'{"T":1001,"v":12.1}'))
        rows={r['field']:r for r in t.status()['fields']}
        self.assertEqual(rows['v']['observed_receive_hz'],1)
        self.assertIsNone(rows['v']['sensor_update_hz'])
        self.assertEqual(rows['L']['kind'],'commanded')
        self.assertEqual(rows['v']['last_value_change_age_s'],1)
        now[0]=4
        self.assertEqual(next(r for r in t.status()['fields'] if r['field']=='v')['receive_status'],'stale')

    def test_malformed_and_nonfinite_data_preserve_raw_without_invention(self):
        for raw in (b'',b'{}',b'<html>error</html>',b'{"v":NaN}',b'{"v":1e400}',b'[]',b'\xff'):
            t=Telemetry(lambda:0);r=decode_response(raw);t.receive(r)
            self.assertTrue(all(f['value'] is None for f in t.status()['fields']))
            self.assertIn('raw_base64',r)

    def test_real_loopback_http_capture_only_sends_read_requests_and_exports(self):
        commands=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                command=json.loads(parse_qs(urlsplit(self.path).query)['json'][0]);commands.append(command)
                raw=b'{"T":1001,"v":12.4}' if command['T']==130 else b'{"T":1002,"ax":0,"r":0}'
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                report=capture(RoverHTTP('127.0.0.1:'+str(server.server_port)),directory,seconds=.12,interval=.02)
                self.assertTrue(commands)
                self.assertEqual({c['T'] for c in commands},{130,126})
                self.assertTrue((Path(directory)/'telemetry_fields.csv').is_file())
                events=[json.loads(s) for s in (Path(directory)/'raw_responses.jsonl').read_text().splitlines()]
                self.assertTrue(any(e['event']=='response' and e['raw_text'] for e in events))
                self.assertFalse(report['firmware_identified'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_hardware_ownership_rejects_competing_process_before_connection(self):
        owner=HardwareOwner(0);port=owner.socket.getsockname()[1]
        try:
            with self.assertRaises(OSError):HardwareOwner(port)
        finally:owner.close()
        second=HardwareOwner(port);second.close()

    def test_hardware_diagnostic_preview_never_constructs_transport(self):
        with patch('hardware_check.RoverHTTP',side_effect=AssertionError('Network attempted')):
            self.assertEqual(main([]),0)

    def test_selected_diagnostic_move_is_not_retried_and_stops_after_fault(self):
        class Motor:
            def __init__(self):self.commands=[]
            def send(self,c):
                self.commands.append(c)
                if c['L'] or c['R']:raise OSError('test fault')
        motor=Motor();events=[]
        with self.assertRaises(OSError):bounded_check(motor,'a',lambda e,**k:events.append(e),sleep=lambda _:None)
        self.assertEqual(sum(bool(c['L'] or c['R']) for c in motor.commands),1)
        self.assertEqual(motor.commands[1],dict(T=1,L=-.1,R=.1))
        self.assertTrue(all(c['L']==c['R']==0 for c in motor.commands[-3:]))
        self.assertIn('transport_fault',events)

    def test_failed_diagnostic_preflight_never_sends_motion(self):
        class Motor:
            def send(self,c):
                self.assert_neutral(c)
                raise OSError('no link')
            def assert_neutral(self,c):assert c['L']==c['R']==0
        with self.assertRaises(OSError):bounded_check(Motor(),'w',lambda *a,**k:None,sleep=lambda _:None)


if __name__=='__main__':unittest.main()
