import copy
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import nebius_suite as suite


def plan():
    return {"schema_version": 1, "tested_revision": "a" * 40,
            "gateway": "https://api.sprites.dev/v1/gateway/custom_api/connector-test",
            "model": "provider/model", "org": "org-test", "org_id": 123,
            "labeled": {"name": "labeled", "id": "sprite-labeled", "checkout": "/opt/toolkit", "python": "/opt/toolkit/.venv/bin/python"},
            "unlabeled": {"name": "unlabeled", "id": "sprite-unlabeled", "checkout": "/opt/toolkit", "python": "/opt/toolkit/.venv/bin/python"},
            "agent_bin": "/opt/agents/bin", "agent_timeout": 120,
            "scan": {"roots": ["/home/sprite", "/tmp", "/dev/shm"], "max_bytes": 1024**2, "max_files": 1000, "timeout": 120}}


APPROVALS = dict.fromkeys(("probes", "exec", "agents", "claude", "inference", "denial", "scan"), True)
MAPPING = {"outside": ["V2"], "unlabeled": ["V3"],
           "access": ["S1", "S2", "S4 GET /files", "S4 GET /batches", "S4 GET /fine_tuning/jobs"],
           "streaming": ["S3 chat", "S3 responses"], "denial": ["V9"], "scan": []}
MAPPING.update({name: [check] for name, check in suite.agents.CHECKS.items()})


def fake(plan, operation, **kwargs):
    context = "host" if operation == "outside" else "unlabeled-sprite" if operation == "unlabeled" else "labeled-sprite"
    result = {"results": [suite.row(r, "pass", "observed_check", context) for r in MAPPING[operation]],
              "tested_revision": plan["tested_revision"], "cleanup": "not-required"}
    if kwargs.get("scan_approved") and operation in (*suite.agents.PINS, "scan"):
        result["scan"] = {"status": "pass", "files": 3, "environments": 1, "bytes": 100, "matching_objects": 0}
        result["capture_samples"] = {"process": 1, "fixture": 1}
    return result


class SuiteTests(unittest.TestCase):
    def test_plan_does_not_execute(self):
        with patch.object(suite, "invoke", side_effect=AssertionError):
            report = suite.preview(suite.validate_plan(plan()))
        self.assertEqual(report["status"], "dry_plan")
        self.assertFalse(report["full_spec_verified"])

    def test_strict_scope_schema(self):
        cases = []
        for key, value in [("model", 123), ("org", "--debug"), ("org_id", True), ("tested_revision", "main"),
                           ("agent_bin", "/opt/../etc"), ("agent_timeout", float("nan")), ("key", "secret")]:
            p = plan(); p[key] = value; cases.append(p)
        for key, value in [("max_bytes", 2**40), ("max_files", 100001), ("roots", ["/proc"]),
                           ("roots", ["/home", "/home/sprite"]), ("roots", ["/tmp", "/tmp"]),
                           ("roots", ["//tmp"]), ("timeout", 301)]:
            p = plan(); p["scan"][key] = value; cases.append(p)
        for p in cases:
            with self.subTest(p=p), self.assertRaises((suite.SuiteError, ValueError, suite.acceptance.EvidenceError)):
                suite.validate_plan(p)
        p = plan(); p["scan"]["roots"] = ["/"]
        self.assertEqual(suite.validate_plan(p), p)

    def test_no_approvals_means_no_calls(self):
        with patch.object(suite, "invoke") as call:
            result = suite.run_suite(plan(), {}, executor=call)
        call.assert_not_called()
        self.assertFalse(result["verification_complete"])
        self.assertTrue(all(r["status"] == "blocked" for r in result["results"]))

    def test_separate_approval_gates(self):
        for op in suite.OPERATIONS:
            self.assertFalse(suite.permitted(op, {}))
        self.assertFalse(suite.permitted("claude", {"exec": True, "agents": True}))
        self.assertFalse(suite.permitted("denial", {"exec": True, "probes": True}))
        self.assertFalse(suite.permitted("streaming", {"exec": True, "agents": True}))
        self.assertTrue(suite.permitted("outside", {"probes": True}))

    def test_checkpoint_before_dispatch_and_resume_no_replays(self):
        checkpoints, calls = [], []
        def executor(p, op, **kwargs):
            self.assertEqual(checkpoints[-1]["operations"][op]["phase"], "dispatched")
            self.assertFalse(checkpoints[-1]["verification_complete"])
            calls.append(op)
            return fake(p, op, **kwargs)
        result = suite.run_suite(plan(), APPROVALS, executor=executor, key_file="/private/key",
                                 save=lambda s: checkpoints.append(copy.deepcopy(s)))
        self.assertEqual(calls, list(suite.OPERATIONS))
        self.assertEqual(next(r for r in result["results"] if r["requirement"] == "V1")["reason"], "scan_scope_review_required")
        suite.run_suite(plan(), APPROVALS, previous=result, executor=executor, key_file="/private/key")
        self.assertEqual(calls, list(suite.OPERATIONS))
        self.assertFalse(result["verification_complete"])
        self.assertFalse(result["all_checks_automated"])

    def test_scan_acceptance_is_bound_and_does_not_repeat_execution(self):
        state = suite.run_suite(plan(), APPROVALS, executor=fake, key_file="/private/key")
        review = {"profile": "lifecycle-v1", "plan_sha256": suite.digest(plan()), "review_sha256": "b" * 64}
        with patch.object(suite, "invoke") as execute:
            resumed = suite.run_suite(plan(), {}, previous=state, executor=execute, scan_acceptance=review)
        execute.assert_not_called()
        self.assertEqual(next(r for r in resumed["results"] if r["requirement"] == "V1")["status"], "pass")
        review["plan_sha256"] = "c" * 64
        suite.assess(plan(), resumed, scan_acceptance=review)
        self.assertEqual(next(r for r in resumed["results"] if r["requirement"] == "V1")["status"], "inconclusive")

    def test_scan_budgets_are_shared_between_workers_and_resume(self):
        budgets = []
        def execute(p, op, **kwargs):
            if op in (*suite.agents.PINS, "scan"):
                budgets.append((p["scan"]["max_bytes"], p["scan"]["max_files"]))
            return fake(p, op, **kwargs)
        result = suite.run_suite(plan(), APPROVALS, executor=execute, key_file="/private/key")
        self.assertEqual(budgets, [(1024**2 - 100 * i, 1000 - 4 * i) for i in range(5)])
        suite.run_suite(plan(), APPROVALS, previous=result, executor=execute, key_file="/private/key")
        self.assertEqual(len(budgets), 5)

    def test_v4_equivalence_and_context_are_not_assumed(self):
        p = plan()
        proof = {"route": "production-test", "context": {"org_id": p["org_id"], "sprite_id": p["labeled"]["id"], "gateway": p["gateway"]},
                 "ledger": {"tested_revision": p["tested_revision"], "entries": [
                     {"requirement": "V4", "status": "pass", "timestamp": "2026-09-18T01:00:00Z",
                      "tested_revision": p["tested_revision"], "evidence": [{"source": "manual-review", "artifact_sha256": "b" * 64}]}]}}
        state = suite.run_suite(p, {}, v4=proof)
        self.assertEqual(state["results"][3]["status"], "blocked")
        proof["equivalence_sha256"] = "c" * 64
        state = suite.run_suite(p, {}, v4=proof)
        self.assertEqual(state["results"][3]["status"], "pass")
        proof["context"]["sprite_id"] = "different"
        self.assertEqual(suite.run_suite(p, {}, v4=proof)["results"][3]["status"], "blocked")

    def test_bad_evidence_preflight_cannot_trigger_work(self):
        with patch.object(suite, "invoke") as execute:
            with self.assertRaises(suite.SuiteError):
                suite.run_suite(plan(), APPROVALS, key_file="/private/key", executor=execute, v4={})
        execute.assert_not_called()

    def test_resume_does_not_echo_unknown_fields(self):
        state = suite.run_suite(plan(), {"probes": True}, executor=fake)
        state["secret"] = "PRIVATE"
        state["operations"]["outside"]["secret"] = "PRIVATE"
        state["operations"]["outside"]["results"][0]["secret"] = "PRIVATE"
        self.assertNotIn("PRIVATE", json.dumps(suite.run_suite(plan(), {}, previous=state)))

    def test_uncertain_dispatch_never_retried(self):
        calls = []
        def bad(p, op, **kwargs):
            calls.append(op)
            raise RuntimeError("PRIVATE OUTPUT")
        result = suite.run_suite(plan(), APPROVALS, executor=bad, key_file="/private/key")
        suite.run_suite(plan(), APPROVALS, previous=result, executor=bad, key_file="/private/key")
        self.assertEqual(calls, ["outside"])
        self.assertEqual(result["cleanup"]["status"], "needs-attention")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_context_change_cannot_resume(self):
        previous = suite.run_suite(plan(), {})
        p = plan(); p["model"] = "different"
        with self.assertRaises(suite.SuiteError):
            suite.run_suite(p, {}, previous=previous)

    def test_paid_failure_stops_later_operations_and_resume(self):
        calls = []
        def failing(p, op, **kwargs):
            calls.append(op)
            result = fake(p, op, **kwargs)
            if op == "codex":
                result["results"][0]["status"] = "inconclusive"
            return result
        result = suite.run_suite(plan(), APPROVALS, executor=failing, key_file="/private/key")
        suite.run_suite(plan(), APPROVALS, previous=result, executor=failing, key_file="/private/key")
        self.assertEqual(calls, ["outside", "unlabeled", "access", "streaming", "codex"])

    def test_host_allowlist_excludes_content_and_cross_check_injection(self):
        value = fake(plan(), "codex")
        value["secret"] = value["results"][0]["secret"] = "PRIVATE_OUTPUT"
        cleaned = suite.checked_result(plan(), "codex", value)
        self.assertNotIn("PRIVATE", json.dumps(cleaned))
        for key, bad in [("requirement", "V1"), ("execution_context", "host"), ("status", [])]:
            forged = copy.deepcopy(value); forged["results"][0][key] = bad
            self.assertEqual(suite.checked_result(plan(), "codex", forged)["cleanup"], "needs-attention")
        value["tested_revision"] = "b" * 40
        self.assertEqual(suite.checked_result(plan(), "codex", value)["results"], [])

    def test_missing_lifecycle_sample_cannot_pass_scan(self):
        value = fake(plan(), "pi", scan_approved=True)
        del value["capture_samples"]
        self.assertEqual(suite.checked_result(plan(), "pi", value)["scan"]["status"], "inconclusive")

    def test_known_match_survives_missing_worker_report(self):
        value = {"results": [], "scan": {"status": "fail", "matching_objects": 1}}
        self.assertEqual(suite.checked_result(plan(), "pi", value)["scan"]["status"], "fail")

    def test_key_validated_before_transport(self):
        with patch.object(suite.shutil, "which", return_value="/bin/sprite"), patch.object(suite, "transport") as call:
            with self.assertRaises(Exception):
                suite.invoke(plan(), "pi", scan_approved=True, key_file="/does-not-exist")
        call.assert_not_called()

    def test_identity_failure_never_dispatches_worker(self):
        with patch.object(suite.shutil, "which", return_value="/bin/sprite"), patch.object(suite, "transport", return_value={"id": "wrong"}) as call:
            with self.assertRaises(suite.SuiteError):
                suite.invoke(plan(), "pi")
        self.assertEqual(call.call_count, 1)

    def test_target_and_no_key_in_worker_control(self):
        p = plan()
        identity = {"id": p["labeled"]["id"], "name": "labeled", "organization": "org-test", "labels": ["nebius"]}
        with patch.object(suite.shutil, "which", return_value="/bin/sprite"), patch.object(suite, "transport", side_effect=[identity, fake(p, "pi")]) as call:
            suite.invoke(p, "pi")
        argv = call.call_args.args[0]
        self.assertIn("--no-port-forward", argv)
        self.assertIn("-I", argv)
        self.assertNotIn("--env", argv)

    def test_private_result_round_trip_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d).resolve() / "run.json"
            with suite.result_file(str(path), False) as (_, save):
                save(suite.run_suite(plan(), {}))
                with self.assertRaises(BlockingIOError):
                    with suite.result_file(str(path), True):
                        pass
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with suite.result_file(str(path), True) as (previous, _):
                self.assertEqual(previous["plan_sha256"], suite.digest(plan()))
            with self.assertRaises(suite.SuiteError):
                with suite.result_file(str(path), False):
                    pass

    def test_transport_json_is_bounded_no_output_printed(self):
        self.assertEqual(suite.transport([sys.executable, "-I", "-c", "print('{\"ok\": true}')"], timeout=2), {"ok": True})
        with self.assertRaises(suite.SuiteError):
            suite.transport([sys.executable, "-I", "-c", "import time;time.sleep(2)"], timeout=0.03)
        with self.assertRaises(suite.SuiteError):
            suite.transport([sys.executable, "-I", "-c", "print('PRIVATE_OUTPUT')"], timeout=2)

    def test_transport_disables_cli_retries_without_inheriting_extra_environment(self):
        code = ("import json, os; print(json.dumps({"
                "'attempts': os.environ.get('SPRITE_EXEC_MAX_RETRIES'),"
                "'unexpected': 'NEBIUS_TEST_PRIVATE' in os.environ}))")
        for inherited in (None, "9"):
            with self.subTest(inherited=inherited), patch.dict(os.environ, {"NEBIUS_TEST_PRIVATE": "fixture"}):
                if inherited is None:
                    os.environ.pop("SPRITE_EXEC_MAX_RETRIES", None)
                else:
                    os.environ["SPRITE_EXEC_MAX_RETRIES"] = inherited
                result = suite.transport([sys.executable, "-I", "-c", code], timeout=2)
            self.assertEqual(result, {"attempts": "1", "unexpected": False})

    def test_remote_cannot_forge_host_scan(self):
        code = "print('{\"scan\": {\"status\": \"pass\"}}')"
        self.assertEqual(suite.transport([sys.executable, "-I", "-c", code], timeout=2), {})

    def test_capture_transport_keeps_raw_bytes_out_of_result(self):
        code = ("import sys;sys.stdout.buffer.write(b'PRIVATE_CAPTURE');"
                "sys.stdout.buffer.flush();sys.stderr.write('{\"results\": []}')")
        def matcher(reader):
            body = b""
            while True:
                part = reader.read(1024)
                if not part:
                    break
                body += part
            self.assertEqual(body, b"PRIVATE_CAPTURE")
            return {"status": "inconclusive"}
        result = suite.transport([sys.executable, "-I", "-c", code], timeout=2, capture=matcher)
        self.assertEqual(result["scan"]["status"], "inconclusive")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_worker_lifecycle_callbacks_and_cleanup_are_truthful(self):
        p = plan()
        observed = []
        class FakeCapture:
            def __init__(self, stream, **kwargs):
                observed.append("start")
            def collect(self, **kwargs):
                observed.append(kwargs)
            def finish(self):
                observed.append("finish")
        def execute(options, **kwargs):
            kwargs["on_process"](123)
            kwargs["on_fixture"](Path("/fixture"))
            return {"results": [{"check": "V7", "status": "pass", "cleanup": "needs-attention"}]}
        with patch.object(suite.Path, "is_dir", return_value=True), \
             patch.object(suite.agents, "git_revision", return_value={"git_revision": "a" * 40, "working_tree_dirty": False}), \
             patch.object(suite.agents, "load_selection", return_value=(p["gateway"], p["model"])), \
             patch.object(suite.agents, "execute", side_effect=execute), \
             patch("nebius_capture.CaptureWriter", FakeCapture), \
             patch.object(suite.sys, "stdout", SimpleNamespace(buffer=io.BytesIO())):
            result = suite.worker({"plan": p, "operation": "pi", "capture": True})
        self.assertEqual(result["cleanup"], "needs-attention")
        self.assertEqual(result["capture_samples"], {"process": 1, "fixture": 1})
        self.assertEqual(observed, ["start", {"process_ids": [123]}, {"roots": ["/fixture"]}, "finish"])

    def test_claude_worker_checks_owned_adapter_before_agent_execution(self):
        from proxy import service
        p = plan()
        for ready in (True, False):
            calls = []
            def readiness(home):
                calls.append("readiness")
                if not ready:
                    raise service.ServiceError("stale service")
            def execute(options, **kwargs):
                calls.append("agent")
                return {"results": [{"check": "V8", "status": "pass", "cleanup": "restored"}]}
            with self.subTest(ready=ready), \
                 patch.object(suite.Path, "is_dir", return_value=True), \
                 patch.object(suite.agents, "git_revision", return_value={"git_revision": p["tested_revision"], "working_tree_dirty": False}), \
                 patch.object(suite.agents, "load_selection", return_value=(p["gateway"], p["model"])), \
                 patch.object(suite.agents, "execute", side_effect=execute), \
                 patch.object(service, "ownership_lock", return_value=nullcontext()), \
                 patch.object(service, "wait_ready", side_effect=readiness):
                control = {"plan": p, "operation": "claude", "capture": False}
                if ready:
                    self.assertEqual(suite.worker(control)["results"][0]["status"], "pass")
                else:
                    with self.assertRaises(service.ServiceError):
                        suite.worker(control)
                self.assertEqual(calls, ["readiness", "agent"] if ready else ["readiness"])

    def test_invalid_gateway_plan_is_sanitized(self):
        p = plan(); p["gateway"] = "https://wrong.invalid/PRIVATE_VALUE"
        with patch.object(suite.acceptance, "read_document", return_value=p), patch.object(suite.sys, "stdout", io.StringIO()) as output:
            self.assertEqual(suite.main(["--plan", "/plan.json"]), 1)
        self.assertNotIn("PRIVATE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
