import json
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from nebius_configure import STATE, atomic_write
from nebius_verify import PLACEHOLDER
from proxy import service


class Runtime:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.stall_stop = False

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return json.dumps(self.rows).encode()
        if args[0] == "create":
            self.rows.append({"name": args[1], "cmd": args[3], "args": args[5].split(","),
                              "dir": args[7], "state": {"status": "running"}})
        elif args[0] == "stop" and not self.stall_stop:
            self.rows[0]["state"]["status"] = "stopped"
        elif args[0] == "delete":
            self.rows = [row for row in self.rows if row["name"] != args[1]]
        return b""


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.state = self.home / STATE
        config = {"OPENAI_BASE_URL": "https://api.sprites.dev/v1/gateway/custom_api/test",
                  "OPENAI_API_KEY": PLACEHOLDER, "ANTHROPIC_API_KEY": PLACEHOLDER,
                  "BIG_MODEL": "test-model", "MIDDLE_MODEL": "test-model", "SMALL_MODEL": "test-model"}
        atomic_write(self.state / "proxy.json", json.dumps(config).encode())
        atomic_write(self.state / "active.json", b"{}")
        self.run = Runtime()
        self.port_patch = patch.object(service, 'port_available')
        self.port_patch.start()
        self.addCleanup(self.port_patch.stop)

    def test_owned_service_lifecycle_no_public_port_or_inference(self):
        result = service.start_owned(self.home, run=self.run)
        self.assertEqual(result["status"], "created")
        self.assertFalse(result["live_agent_verified"])
        self.assertEqual(service.start_owned(self.home, run=self.run)["status"], "already_running")
        self.assertTrue(service.stop_owned(self.home, run=self.run))
        self.assertEqual(self.run.rows, [])
        self.assertFalse(service.stop_owned(self.home, run=self.run))
        self.assertNotIn("--http-port", str(self.run.calls))
        create = next(call for call in self.run.calls if call[0] == "create")
        self.assertEqual(create[3], "/usr/bin/env")
        self.assertIn("-i,PATH=", create[5])
        self.assertIn(",-I,", create[5])
        self.assertEqual(sum(call[0] == "create" for call in self.run.calls), 1)

    def test_changed_definition_not_stopped_or_deleted(self):
        service.start_owned(self.home, run=self.run)
        self.run.rows[0]["cmd"] = "/someone/elses/service"
        with self.assertRaises(service.ServiceError):
            service.stop_owned(self.home, run=self.run)
        self.assertFalse(any(call[0] in ("stop", "delete") for call in self.run.calls))

    def test_added_public_route_or_environment_conflicts(self):
        for field, value in (("http_port", 8083), ("env", {"OTHER": "value"}), ("needs", ["other"])):
            with self.subTest(field=field):
                self.run = Runtime()
                marker = self.state / "service-owned.json"
                if marker.exists():
                    marker.unlink()
                service.start_owned(self.home, run=self.run)
                self.run.rows[0][field] = value
                with self.assertRaises(service.ServiceError):
                    service.stop_owned(self.home, run=self.run)

    def test_unconfirmed_stop_retains_marker_and_definition(self):
        service.start_owned(self.home, run=self.run)
        self.run.stall_stop = True
        with self.assertRaises(service.ServiceError):
            service.stop_owned(self.home, run=self.run)
        self.assertTrue((self.state / "service-owned.json").exists())
        self.assertFalse(any(call[0] == "delete" for call in self.run.calls))

    def test_explicit_stop_nonzero_exit_is_terminal(self):
        service.start_owned(self.home, run=self.run)
        def run(args):
            result = self.run(args)
            if args[0] == "stop":
                self.run.rows[0]["state"] = {"status": "failed", "error": "exited with code 143"}
            return result
        self.assertTrue(service.stop_owned(self.home, run=run))
        self.assertEqual(self.run.rows, [])

    def test_terminal_label_with_live_pid_is_not_confirmed(self):
        service.start_owned(self.home, run=self.run)
        def run(args):
            result = self.run(args)
            if args[0] == "stop":
                self.run.rows[0]["state"] = {"status": "failed", "pid": 123}
            return result
        with self.assertRaises(service.ServiceError):
            service.stop_owned(self.home, run=run)
        self.assertFalse(any(call[0] == "delete" for call in self.run.calls))

    def test_resume_cleanup_does_not_stop_exited_service_again(self):
        service.start_owned(self.home, run=self.run)
        self.run.rows[0]["state"] = {"status": "failed", "error": "exited with code 143"}
        def run(args):
            if args[0] == "stop":
                raise service.ServiceError("HTTP 409: already exited")
            return self.run(args)
        self.assertTrue(service.stop_owned(self.home, run=run))
        self.assertEqual(self.run.rows, [])

    def test_unknown_create_result_is_not_retried(self):
        def uncertain(args):
            if args[0] == "create":
                raise service.ServiceError("uncertain")
            return self.run(args)
        with self.assertRaises(service.ServiceError):
            service.start_owned(self.home, run=uncertain)
        self.assertTrue((self.state / "service-owned.json").exists())
        with self.assertRaises(service.ServiceError):
            service.start_owned(self.home, run=self.run)
        with self.assertRaises(service.ServiceError):
            service.stop_owned(self.home, run=self.run)
        self.assertTrue((self.state / "service-owned.json").exists())

    def test_concurrent_start_shares_configuration_lock(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: service.start_owned(self.home, run=self.run), range(2)))
        self.assertEqual({row["status"] for row in results}, {"created", "already_running"})
        self.assertEqual(sum(call[0] == "create" for call in self.run.calls), 1)

    def test_malformed_marker_and_runtime_are_sanitized(self):
        atomic_write(self.state / "service-owned.json", b"[]")
        with self.assertRaises(service.ServiceError):
            service.stop_owned(self.home, run=self.run)
        (self.state / "service-owned.json").unlink()
        service.start_owned(self.home, run=self.run)
        self.run.rows[0]["state"] = None
        with self.assertRaises(service.ServiceError):
            service.start_owned(self.home, run=self.run)

    def test_no_cli_action_without_approval(self):
        with patch.object(service, "start_owned") as start, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                service.main(["--start"])
            start.assert_not_called()

    def test_start_can_reuse_configuration_lock(self):
        with service.ownership_lock(self.home), patch.object(service, 'ownership_lock', wraps=service.ownership_lock) as lock:
            service.start_owned(self.home, run=self.run, locked=True)
        lock.assert_called_once_with(self.home, locked=True)

    def test_port_collision_prevents_service_creation(self):
        with patch.object(service, 'port_available', side_effect=service.ServiceError('occupied')):
            with self.assertRaises(service.ServiceError):
                service.start_owned(self.home, run=self.run)
        self.assertFalse(any(call[0] == 'create' for call in self.run.calls))
        self.assertFalse((self.state / 'service-owned.json').exists())

    def test_readiness_requires_health_and_matching_running_definition(self):
        service.start_owned(self.home, run=self.run)
        probes = []
        service.wait_ready(self.home, run=self.run, probe=lambda timeout: probes.append(timeout) or True)
        self.assertTrue(probes)
        self.assertLessEqual(probes[0], 0.5)
        self.run.rows[0]['cmd'] = '/other/process'
        with self.assertRaises(service.ServiceError):
            service.wait_ready(self.home, run=self.run, probe=lambda _: self.fail('must not probe'))

    def test_readiness_failed_state_and_timeout(self):
        service.start_owned(self.home, run=self.run)
        start = time.monotonic()
        with self.assertRaisesRegex(service.ServiceError, 'deadline'):
            service.wait_ready(self.home, run=self.run, timeout=0.02, probe=lambda _: False)
        self.assertLess(time.monotonic() - start, 0.5)
        self.run.rows[0]['state']['status'] = 'failed'
        with self.assertRaisesRegex(service.ServiceError, 'exited'):
            service.wait_ready(self.home, run=self.run, probe=lambda _: self.fail('must not probe'))

    def test_readiness_rechecks_identity_and_running_state_after_health(self):
        service.start_owned(self.home, run=self.run)
        original = dict(self.run.rows[0])
        for mutation in ('definition', 'state'):
            self.run.rows[0] = {**original, 'state': {'status': 'running'}}
            def probe(_):
                if mutation == 'definition':
                    self.run.rows[0]['cmd'] = '/replacement'
                else:
                    self.run.rows[0]['state']['status'] = 'failed'
                return True
            with self.subTest(mutation=mutation), self.assertRaises(service.ServiceError):
                service.wait_ready(self.home, run=self.run, probe=probe)

    def test_health_disables_proxies_redirects_and_bounds_body(self):
        import asyncio
        import httpx
        original = httpx.AsyncClient
        for payload, status, expected in ((b'{"status":"ok","scope":"local adapter only"}', 200, True),
                                          (b'{}', 200, False), (b'x' * 1025, 200, False),
                                          (b'', 302, False)):
            def client(**kwargs):
                self.assertFalse(kwargs['trust_env'])
                self.assertFalse(kwargs['follow_redirects'])
                def respond(request):
                    self.assertEqual(str(request.url), 'http://127.0.0.1:8083/health')
                    self.assertEqual(request.method, 'GET')
                    return httpx.Response(status, stream=httpx.ByteStream(payload))
                return original(**kwargs, transport=httpx.MockTransport(respond))
            with self.subTest(status=status, payload=len(payload)), patch('httpx.AsyncClient', side_effect=client):
                self.assertEqual(asyncio.run(service._health(0.5)), expected)

    def test_health_deadline_covers_slow_body(self):
        import asyncio
        import httpx
        original = httpx.AsyncClient
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{'
                await asyncio.sleep(1)
                yield b'}'
        def client(**kwargs):
            return original(**kwargs, transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=SlowBody())))
        start = time.monotonic()
        with patch('httpx.AsyncClient', side_effect=client):
            self.assertFalse(service.healthy(0.02))
        self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
