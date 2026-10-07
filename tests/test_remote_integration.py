"""Local HTTP + fake-motor integration checks. Never connects to a rover.

Run: python -m unittest discover -s tests -p 'test_remote_integration.py' -v
"""
import copy
import http.client
import json
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_controller as remote


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError("Timed out waiting for controller test condition")


class FakeMotor:
    def __init__(self):
        self.lock = threading.Lock()
        self.commands = []
        self.thread_ids = set()
        self.active = 0
        self.max_active = 0
        self.block_motion = False
        self.motion_entered = threading.Event()
        self.release_motion = threading.Event()
        self.fail_next_motion = False
        self.opens = 0

    def open(self):
        self.opens += 1

    def send(self, command):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.thread_ids.add(threading.get_ident())
            self.commands.append(copy.deepcopy(command))
        try:
            moving = bool(command["L"] or command["R"])
            if moving and self.fail_next_motion:
                self.fail_next_motion = False
                raise OSError("Simulated rover disconnection")
            if moving and self.block_motion:
                self.motion_entered.set()
                if not self.release_motion.wait(2):
                    raise OSError("Fake blocked write exceeded test deadline")
        finally:
            with self.lock:
                self.active -= 1

    def close(self):
        pass

    def moving_commands(self):
        with self.lock:
            return [c for c in self.commands if c["L"] or c["R"]]


class RemoteHTTPIntegration(unittest.TestCase):
    def setUp(self):
        self.motor = FakeMotor()
        self.controller = remote.Controller(self.motor, live=True, period_s=0.02)
        self.server = remote.LocalServer(("127.0.0.1", 0), self.controller)
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.server_thread = threading.Thread(target=self.server.serve_forever,
                                              kwargs={"poll_interval": 0.01}, daemon=True)
        self.controller.start()
        self.server_thread.start()
        wait_for(lambda: not self.controller.status()["neutral_pending"])
        status, body, _ = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.token = body["token"]
        self.seq = body["seq"]

    def tearDown(self):
        self.motor.release_motion.set()
        self.controller.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(1)

    def request(self, method, path, payload=None, header_changes=None):
        headers = {"Host": self.host}
        if method == "POST":
            headers.update({"Origin": "http://" + self.host,
                            "X-Controller-Token": self.token,
                            "Content-Type": "application/json"})
        headers.update(header_changes or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            body = None if payload is None else json.dumps(payload)
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            data = json.loads(raw) if raw and "application/json" in response.getheader("Content-Type", "") else raw
            return response.status, data, dict(response.getheaders())
        finally:
            conn.close()

    def post(self, action, **fields):
        self.seq += 1
        return self.request("POST", "/api/" + action, {"seq": self.seq, **fields})

    def arm(self):
        status, data, _ = self.post("arm")
        self.assertEqual(status, 200, data)
        self.assertTrue(data["armed"])

    def test_start_disarmed_and_bootstrap_not_cacheable_or_frameable(self):
        status, session, headers = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(session["armed"])
        self.assertEqual(session["deadman_ms"], 350)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.post("drive", left=0.1, right=0.1)[0], 409)
        self.assertEqual(self.motor.moving_commands(), [])

    def test_host_origin_and_csrf_guards_reject_mutations(self):
        for headers in [{"Host": "attacker.invalid"},
                        {"Origin": "http://attacker.invalid"},
                        {"Origin": "null"},
                        {"X-Controller-Token": "wrong-token"}]:
            with self.subTest(headers=headers):
                status, _, _ = self.request("POST", "/api/arm", {"seq": 99}, headers)
                self.assertEqual(status, 403)
        self.assertFalse(self.controller.status()["armed"])
        self.assertEqual(self.motor.moving_commands(), [])

    def test_bad_numbers_target_fields_and_sequence_types_rejected(self):
        self.arm()
        for value in [float("nan"), float("inf"), 0.251, -0.251, True, "0.1"]:
            with self.subTest(value=value):
                self.assertIn(self.post("drive", left=value, right=0)[0], (400, 422))
        self.assertEqual(self.post("drive", left=0.1, right=0.1,
                                   host="http://203.0.113.1")[0], 400)
        self.assertEqual(self.request("POST", "/api/drive",
                                     {"seq": "999", "left": 0.1, "right": 0.1})[0], 400)
        self.assertEqual(self.motor.moving_commands(), [])

    def test_lost_browser_heartbeat_stops_and_requires_explicit_rearm(self):
        self.arm()
        self.assertEqual(self.post("drive", left=0.1, right=0.1)[0], 200)
        wait_for(lambda: bool(self.motor.moving_commands()))
        wait_for(lambda: not self.controller.status()["armed"])
        wait_for(lambda: not self.controller.status()["neutral_pending"])
        self.assertEqual(self.motor.commands[-1], remote.STOP)
        n = len(self.motor.moving_commands())
        self.assertEqual(self.post("drive", left=0.1, right=0.1)[0], 409)
        self.assertEqual(len(self.motor.moving_commands()), n)

    def test_release_sends_neutral_but_keeps_operator_armed(self):
        self.arm()
        self.post("drive", left=0.1, right=0.1)
        wait_for(lambda: bool(self.motor.moving_commands()))
        self.assertEqual(self.post("drive", left=0, right=0)[0], 200)
        wait_for(lambda: not self.controller.status()["neutral_pending"])
        self.assertEqual(self.motor.commands[-1], remote.STOP)
        self.assertTrue(self.controller.status()["armed"])

    def test_stop_latches_rejects_older_commands_and_has_one_writer(self):
        self.motor.block_motion = True
        self.arm()
        self.post("drive", left=0.1, right=0.1)
        self.assertTrue(self.motor.motion_entered.wait(1))
        start = time.monotonic()
        status, body, _ = self.post("stop")
        self.assertLess(time.monotonic() - start, 0.2, "STOP waited for blocked motor I/O")
        self.assertEqual(status, 200)
        self.assertFalse(body["armed"])
        self.assertEqual(self.request("POST", "/api/drive",
                                     {"seq": self.seq - 1, "left": 0.2, "right": 0.2})[0], 409)
        self.controller.tick()  # Must not overlap the active motor-worker send.
        self.motor.release_motion.set()
        wait_for(lambda: not self.controller.status()["neutral_pending"])
        self.assertEqual(self.motor.commands[-1], remote.STOP)
        self.assertEqual(len(self.motor.moving_commands()), 1)
        self.assertEqual(self.motor.max_active, 1)
        self.assertEqual(len(self.motor.thread_ids), 1)

    def test_io_failure_never_retries_motion_or_restarts_automatically(self):
        self.arm()
        self.motor.fail_next_motion = True
        self.post("drive", left=0.1, right=0.1)
        wait_for(lambda: bool(self.motor.moving_commands()))
        wait_for(lambda: not self.controller.status()["armed"])
        wait_for(lambda: not self.controller.status()["neutral_pending"])
        self.assertEqual(len(self.motor.moving_commands()), 1)
        self.assertEqual(self.motor.commands[-1], remote.STOP)
        self.assertEqual(self.post("drive", left=0.1, right=0.1)[0], 409)
        self.assertFalse(self.controller.status()["armed"])

    def test_validation_requests_share_origin_token_guards_and_do_not_consume_drive_sequence(self):
        payload = dict(action='observation', check='Pivot', result='not_tested', notes='Test only')
        self.assertEqual(self.request('POST', '/api/validation', payload,
                                     {'X-Controller-Token': 'wrong'})[0], 403)
        self.assertEqual(self.request('POST', '/api/validation', payload,
                                     {'Origin': 'http://attacker.invalid'})[0], 403)
        seq = self.controller.seq
        self.assertEqual(self.request('POST', '/api/validation', payload)[0], 200)
        self.assertEqual(self.controller.seq, seq)
        self.assertFalse(self.controller.status()['armed'])
        self.assertEqual(self.motor.moving_commands(), [])
        status, report, _ = self.request('GET', '/api/validation')
        self.assertEqual(status, 200)
        self.assertNotIn('token', report)
        self.assertEqual(report['observations'][0]['result'], 'not_tested')

    def test_planner_and_validation_script_are_served_without_arbitrary_files(self):
        self.assertEqual(self.request('GET', '/planner')[0], 200)
        self.assertIn(b'id="planSvg"', self.request('GET', '/')[1])
        self.assertIn(b'id="armButton"', self.request('GET', '/debug.html')[1])
        self.assertEqual(self.request('GET', '/preview/scene.js')[0], 200)
        self.assertEqual(self.request('GET', '/preview/vendor/three.min.js')[0], 200)
        self.assertEqual(self.request('GET', '/validation_panel.js')[0], 200)
        self.assertEqual(self.request('GET', '/validation_run.py')[0], 404)
        self.assertEqual(self.request('GET', '/test_runs/anything')[0], 404)

    def test_repeated_arm_during_motion_does_not_silently_drop_stop(self):
        self.arm()
        self.post("drive", left=0.1, right=0.1)
        wait_for(lambda: bool(self.motor.moving_commands()))
        status, _, _ = self.post("arm")
        self.assertIn(status, (200, 409))
        # Rejecting ARM preserves a timed demand; accepting must queue neutral.
        # Either path must transmit neutral by the ordinary heartbeat deadline.
        wait_for(lambda: bool(self.motor.commands) and self.motor.commands[-1] == remote.STOP)


class RemoteSimulationBoundary(unittest.TestCase):
    def test_simulation_ignores_real_transport_entirely(self):
        class ForbiddenTransport:
            def open(self): raise AssertionError("Simulation opened transport")
            def send(self, _): raise AssertionError("Simulation used transport")
            def close(self): raise AssertionError("Simulation closed transport")
        controller = remote.Controller(ForbiddenTransport(), live=False)
        controller.tick()
        controller.action("arm", {"seq": 1})
        controller.action("drive", {"seq": 2, "left": 0.1, "right": 0.1})
        controller.tick()
        self.assertEqual(controller.status()["transport_state"], "simulated")
        self.assertFalse(controller.status()["live"])

    def test_server_cannot_bind_to_external_interfaces(self):
        with self.assertRaises(ValueError):
            remote.LocalServer(("0.0.0.0", 0), remote.Controller())

    def test_rover_target_must_be_literal_http_ip_not_arbitrary_url(self):
        for target in ["example.com", "http://127.0.0.1/path", "file:///etc/passwd",
                       "http://user:pass@127.0.0.1", "http://127.0.0.1/?x=y"]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                remote.RoverHTTP(target)


if __name__ == "__main__":
    unittest.main()
