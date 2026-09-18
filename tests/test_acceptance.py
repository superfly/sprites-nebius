import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import nebius_acceptance as acceptance


REVISION = "a" * 40
DIGEST = "b" * 64
START = "2026-09-16T01:00:00Z"
FINISH = "2026-09-16T01:02:00Z"


def reference():
    return {"source": "local-tests", "artifact_sha256": DIGEST}


def entry(requirement="S1"):
    return {"requirement": requirement, "status": "pass", "timestamp": FINISH,
            "tested_revision": REVISION, "evidence": [reference()]}


def reconciliation():
    scope = {"project_id": "project-test", "model": "org/test-model",
             "connector_id": "connector-test", "sprite_id": "sprite-test",
             "org_id": 123, "provider": "custom_api", "started_at": START,
             "finished_at": FINISH, "request_ids": ["request-1", "request-2"],
             "isolated": True, "project_binding_sha256": DIGEST}
    records = []
    for request_id in scope["request_ids"]:
        records.append({**{key: scope[key] for key in ("model", "connector_id", "sprite_id",
                                                     "org_id", "provider")},
                        "event": "gateway_inference_usage", "request_id": request_id,
                        "started_at": START, "finished_at": FINISH,
                        "status": 200, "outcome": "completed", "usage_known": True,
                        "unit": "tokens", "input_count": 50, "output_count": 100})
    return {"tested_revision": REVISION, "scope": scope,
            "gateway": {"complete": True, "artifact_sha256": DIGEST, "records": records},
            "billing": {"source": "nebius-billing-usage", "view": "full-numbers",
                        "precision": "exact", "artifact_sha256": DIGEST,
                        "project_id": scope["project_id"], "model": scope["model"],
                        "started_at": START, "finished_at": FINISH,
                        "collected_at": FINISH, "data_through": FINISH,
                        "isolated": True, "unit": "tokens",
                        "input_count": 100, "output_count": 200}}


def day_reconciliation():
    document = reconciliation()
    scope = document["scope"]
    scope.update(accounting_mode="utc-day", started_at="2026-09-16T00:00:00Z",
                 finished_at="2026-09-17T00:00:00Z", isolation_sha256=DIGEST)
    del scope["request_ids"]
    document["gateway"]["export"] = {
        **{key: scope[key] for key in ("connector_id", "sprite_id", "org_id", "provider",
                                      "model", "started_at", "finished_at")},
        "server_count": 2, "truncated": False, "query_sha256": DIGEST,
        "window_basis": "overlapping-requests", "collected_at": "2026-09-17T02:00:00Z",
        "data_through": "2026-09-17T01:00:00Z"}
    document["billing"].update(started_at=scope["started_at"], finished_at=scope["finished_at"],
                               collected_at="2026-09-17T02:00:00Z",
                               data_through="2026-09-17T01:00:00Z")
    return document


class LedgerTests(unittest.TestCase):
    def ledger(self, entries):
        return acceptance.ledger({"tested_revision": REVISION, "entries": entries})

    def test_missing_checks_never_full_pass(self):
        result = self.ledger([entry()])
        self.assertEqual(len(result["results"]), 25)
        self.assertFalse(result["full_spec_verified"])
        self.assertEqual(result["results"][1]["status"], "blocked")

    def test_all_checks_require_current_evidence(self):
        results = self.ledger([entry(requirement) for requirement in acceptance.REQUIREMENTS])
        self.assertTrue(results["full_spec_verified"])
        self.assertTrue(results["evidence_only"])

    def test_duplicate_requirement_inconclusive(self):
        result = self.ledger([entry(), entry()])
        self.assertEqual(result["results"][0]["reason"], "duplicate_requirement")

    def test_fail_wins_over_missing_checks(self):
        result = self.ledger([{**entry(), "status": "fail"}])
        self.assertEqual(result["status"], "fail")

    def test_incomplete_invalid_and_stale_entries_cannot_pass(self):
        for field, value in (("status", "skipped"), ("status", []), ("timestamp", "yesterday"),
                             ("timestamp", "2026-09-16T01:00:00+02:00"),
                             ("timestamp", "2026-09-16T01:00:00"), ("evidence", []),
                             ("evidence", [{"source": [], "artifact_sha256": DIGEST}]),
                             ("tested_revision", "c" * 40)):
            with self.subTest(field=field, value=value):
                result = self.ledger([{**entry(), field: value}])
                self.assertEqual(result["results"][0]["status"], "inconclusive")

    def test_output_drops_untrusted_text(self):
        item = entry()
        item["notes"] = "DO-NOT-PRINT-SECRET"
        item["evidence"][0]["body"] = "DO-NOT-PRINT-SECRET"
        self.assertNotIn("DO-NOT-PRINT-SECRET", json.dumps(self.ledger([item])))

    def test_unknown_requirement_rejected_without_echo(self):
        for requirement in ("SECRET", [], None):
            with self.subTest(requirement=requirement), self.assertRaisesRegex(
                    acceptance.EvidenceError, "^invalid_requirement$"):
                self.ledger([{**entry(), "requirement": requirement}])


class ReconciliationTests(unittest.TestCase):
    def test_exact_totals_pass_only_v10(self):
        result = acceptance.reconcile(reconciliation())
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["full_spec_verified"])
        self.assertEqual(result["requirement"], "V10")
        self.assertEqual(result["request_count"], 2)

    def test_each_direction_has_independent_five_percent_tolerance(self):
        document = reconciliation()
        document["gateway"]["records"][0]["input_count"] = 55
        self.assertEqual(acceptance.reconcile(document)["status"], "pass")
        document["gateway"]["records"][0]["input_count"] = 56
        result = acceptance.reconcile(document)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["counts"]["output_count"]["within_five_percent"])

    def test_million_token_display_converts_exact_decimal_text(self):
        document = reconciliation()
        document["billing"].update(unit="million-tokens", input_count="0.000100", output_count="0.000200")
        result = acceptance.reconcile(document)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["counts"]["input_count"]["nebius"], 100)

    def test_inexact_million_tokens_never_rounded_to_pass(self):
        for count in (0.0001, "0.0000001", "NaN", "Infinity", "1e-4", "-0.0001",
                      "0.00000099999999999999999999999999999999"):
            document = reconciliation()
            document["billing"].update(unit="million-tokens", input_count=count, output_count="0.000200")
            with self.subTest(count=count):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_missing_duplicate_extra_conflicting_requests_inconclusive(self):
        for change in ("missing", "duplicate", "conflicting", "extra"):
            document = reconciliation()
            records = document["gateway"]["records"]
            if change == "missing":
                records.pop()
            else:
                records.append(copy.deepcopy(records[0]))
                if change == "conflicting":
                    records[-1]["input_count"] = 999
                if change == "extra":
                    records[-1]["request_id"] = "request-3"
            with self.subTest(change=change):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_unknown_and_mixed_scope_records_inconclusive(self):
        mutations = (("input_count", None), ("output_count", True), ("input_count", -1),
                     ("input_count", "50"), ("input_count", 2**64), ("usage_known", False),
                     ("input_count", float("nan")), ("input_count", float("inf")),
                     ("outcome", None), ("status", 600),
                     ("status", True), ("unit", "requests"), ("event", "other"),
                     ("sprite_id", "other"), ("connector_id", "other"), ("model", "other"),
                     ("org_id", "other"), ("provider", "other"), ("request_id", None),
                     ("started_at", "2026-09-16T00:59:59Z"),
                     ("finished_at", "2026-09-16T01:02:01Z"),
                     ("finished_at", "2026-09-16T00:59:59Z"))
        for key, value in mutations:
            document = reconciliation()
            document["gateway"]["records"][0][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_known_usage_on_unsuccessful_requests_is_counted_not_dropped(self):
        for outcome, status in (("error", 500), ("interrupted", 200), ("incomplete", 200),
                                ("client_closed", 499), ("upstream_error", 502)):
            document = reconciliation()
            document["gateway"]["records"][0].update(outcome=outcome, status=status)
            with self.subTest(outcome=outcome):
                result = acceptance.reconcile(document)
                self.assertEqual(result["status"], "pass")
                self.assertEqual(result["noncompleted_request_count"], 1)
                self.assertEqual(result["counts"]["input_count"]["gateway"], 100)
                document["gateway"]["records"][0]["usage_known"] = False
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_complete_utc_day_needs_no_fabricated_settled_flag_or_client_request_set(self):
        result = acceptance.reconcile(day_reconciliation())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["accounting_mode"], "utc-day")
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(len(result["evidence"]), 5)

    def test_day_export_scope_count_and_coverage_cannot_be_assumed(self):
        changes = (("server_count", None), ("server_count", 1), ("server_count", 3),
                   ("server_count", 2.0), ("server_count", True), ("server_count", float("inf")),
                   ("truncated", True), ("truncated", None), ("query_sha256", None),
                   ("window_basis", "started-in-window"), ("model", "another-model"),
                   ("sprite_id", "another-sprite"), ("connector_id", "another-connector"),
                   ("org_id", 456), ("provider", "another-provider"),
                   ("started_at", START), ("finished_at", FINISH),
                   ("collected_at", FINISH), ("data_through", FINISH), ("data_through", None))
        for key, value in changes:
            document = day_reconciliation()
            document["gateway"]["export"][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")
        document = day_reconciliation()
        del document["gateway"]["export"]
        self.assertEqual(acceptance.reconcile(document)["reason"], "missing_scoped_gateway_export")

    def test_day_mode_requires_binding_isolation_and_real_billing_freshness(self):
        for group, key, value in (("scope", "project_binding_sha256", None),
                                  ("scope", "isolation_sha256", None),
                                  ("scope", "isolated", False), ("billing", "isolated", False),
                                  ("billing", "data_through", FINISH),
                                  ("billing", "data_through", None)):
            document = day_reconciliation()
            document[group][key] = value
            with self.subTest(group=group, key=key):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_day_must_be_exact_closed_utc_midnight_window(self):
        for start, finish in ((START, FINISH), (START, "2026-09-17T01:00:00Z"),
                              ("2026-09-16T00:00:00Z", "2026-09-18T00:00:00Z"),
                              ("2999-09-16T00:00:00Z", "2999-09-17T00:00:00Z")):
            document = day_reconciliation()
            document["scope"].update(started_at=start, finished_at=finish)
            with self.subTest(start=start, finish=finish):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_day_cannot_assign_a_request_that_crosses_midnight(self):
        for key, value in (("started_at", "2026-09-15T23:59:59Z"),
                           ("finished_at", "2026-09-17T00:00:00Z"),
                           ("finished_at", "2026-09-17T00:00:01Z")):
            document = day_reconciliation()
            document["gateway"]["records"][0][key] = value
            with self.subTest(key=key):
                self.assertEqual(acceptance.reconcile(document)["reason"],
                                 "gateway_request_crosses_midnight")

    def test_day_duplicates_omissions_and_optional_expected_set_are_checked(self):
        for change in ("duplicate", "missing", "expected-mismatch"):
            document = day_reconciliation()
            if change == "duplicate":
                document["gateway"]["records"].append(copy.deepcopy(document["gateway"]["records"][0]))
            elif change == "missing":
                document["gateway"]["records"].pop()
            else:
                document["scope"]["request_ids"] = ["not-the-exported-requests"]
            with self.subTest(change=change):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_usage_comparison_does_not_require_financial_settlement(self):
        for fixture in (reconciliation, day_reconciliation):
            self.assertEqual(acceptance.reconcile(fixture())["status"], "pass")
            for settled in (True, False, None):
                with self.subTest(mode=fixture.__name__, settled=settled):
                    document = fixture()
                    document["billing"]["settled"] = settled
                    result = acceptance.reconcile(document)
                    self.assertEqual(result["status"], "pass")
                    self.assertFalse(result["full_spec_verified"])
                    document["billing"]["input_count"] = 200
                    self.assertEqual(acceptance.reconcile(document)["status"], "fail")
                    document["billing"]["data_through"] = START
                    self.assertEqual(acceptance.reconcile(document)["reason"], "stale_billing_evidence")

    def test_non_authoritative_rounded_billing_inconclusive(self):
        for key, value in (("source", "observability"), ("view", "chart"), ("precision", "rounded"),
                           ("isolated", False), ("artifact_sha256", "bad"),
                           ("model", "other"), ("project_id", "other"),
                           ("finished_at", "2026-09-16T01:03:00Z")):
            document = reconciliation()
            document["billing"][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_scope_and_gateway_completeness_required(self):
        for group, key, value in (("scope", "isolated", False), ("gateway", "complete", False),
                                  ("scope", "project_binding_sha256", None),
                                  ("scope", "request_ids", []), ("scope", "request_ids", ["x", "x"]),
                                  ("gateway", "artifact_sha256", None)):
            document = reconciliation()
            document[group][key] = value
            with self.subTest(group=group, key=key):
                self.assertEqual(acceptance.reconcile(document)["status"], "inconclusive")

    def test_stale_billing_cannot_pass_even_with_matching_totals(self):
        document = reconciliation()
        document["billing"]["data_through"] = START
        self.assertEqual(acceptance.reconcile(document)["reason"], "stale_billing_evidence")
        document["billing"].update(data_through=FINISH, collected_at=START)
        self.assertEqual(acceptance.reconcile(document)["reason"], "stale_billing_evidence")

    def test_all_zero_usage_is_not_a_successful_reconciliation(self):
        document = reconciliation()
        for record in document["gateway"]["records"]:
            record.update(input_count=0, output_count=0)
        document["billing"].update(input_count=0, output_count=0)
        self.assertEqual(acceptance.reconcile(document)["reason"], "no_billable_usage_to_reconcile")

    def test_one_zero_dimension_and_one_nonzero_dimension_supported(self):
        document = reconciliation()
        for record in document["gateway"]["records"]:
            record["output_count"] = 0
        document["billing"]["output_count"] = 0
        self.assertEqual(acceptance.reconcile(document)["status"], "pass")
        document["gateway"]["records"][0]["output_count"] = 1
        self.assertEqual(acceptance.reconcile(document)["status"], "fail")

    def test_unknown_private_fields_are_never_echoed(self):
        document = reconciliation()
        for object_ in (document, document["billing"], document["gateway"]["records"][0]):
            object_["secret"] = "DO-NOT-PRINT-SECRET"
        self.assertNotIn("DO-NOT-PRINT-SECRET", json.dumps(acceptance.reconcile(document)))


class FileAndCliTests(unittest.TestCase):
    def run_cli(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(content)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = acceptance.main(["reconcile", str(path)])
            return code, json.loads(output.getvalue())

    def test_good_input_exits_zero(self):
        self.assertEqual(self.run_cli(json.dumps(reconciliation()))[0], 0)

    def test_missing_evidence_exits_nonzero(self):
        self.assertEqual(self.run_cli(json.dumps({"tested_revision": REVISION}))[0], 1)

    def test_invalid_json_never_echoes_contents(self):
        code, result = self.run_cli("PRIVATE-CREDENTIAL")
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE-CREDENTIAL", json.dumps(result))

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        for text in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}'):
            with self.subTest(text=text):
                self.assertEqual(self.run_cli(text)[0], 1)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.fake_key = b"FAKE-TEST-ONLY-0123456789"
        self.key_file = self.directory / "key"
        self.key_file.write_bytes(self.fake_key + b"\n")
        self.key_file.chmod(0o600)
        self.manifest = {"tested_revision": REVISION, "started_at": START, "finished_at": FINISH,
                         "coverage": [], "artifacts": []}
        for phase in ("before", "after"):
            for scope in ("filesystem", "process-environment"):
                path = self.directory / (phase + "-" + scope)
                path.write_bytes(b"safe capture")
                path.chmod(0o600)
                self.manifest["coverage"].append({"phase": phase, "scope": scope,
                    "captured_at": START if phase == "before" else FINISH,
                    "complete": True, "unreadable_count": 0, "excluded_count": 0, "race_count": 0})
                self.manifest["artifacts"].append({"phase": phase, "scope": scope,
                    "path": str(path), "encoding": "raw", "sha256": hashlib.sha256(b"safe capture").hexdigest()})

    def scan(self):
        return acceptance.scan(self.manifest, str(self.key_file))

    def test_complete_raw_captures_no_match_pass_only_v1(self):
        result = self.scan()
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["full_spec_verified"])
        self.assertEqual(result["artifacts_scanned"], 4)
        self.assertEqual(result["bytes_scanned"], 48)

    def test_key_match_fails_without_echoing_match_or_path(self):
        artifact = self.manifest["artifacts"][0]
        data = b"prefix" + self.fake_key + b"suffix"
        Path(artifact["path"]).write_bytes(data)
        artifact["sha256"] = hashlib.sha256(data).hexdigest()
        result = self.scan()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["matching_artifacts"], 1)
        self.assertNotIn(self.fake_key.decode(), json.dumps(result))
        self.assertNotIn(str(self.directory), json.dumps(result))

    def test_match_spanning_chunk_boundaries_detected(self):
        path = self.directory / "chunked"
        path.write_bytes(b"123456" + self.fake_key + b"tail")
        path.chmod(0o600)
        found, count, _ = acceptance._scan_artifact(str(path), self.fake_key, chunk_size=8)
        self.assertTrue(found)
        self.assertEqual(count, 10 + len(self.fake_key))

    def test_unreadable_artifact_makes_scan_inconclusive(self):
        Path(self.manifest["artifacts"][0]["path"]).unlink()
        result = self.scan()
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["unreadable_artifacts"], 1)

    def test_coverage_omissions_exclusions_and_races_are_inconclusive(self):
        for key in ("unreadable_count", "excluded_count", "race_count"):
            self.manifest["coverage"][0][key] = 1
            with self.subTest(key=key):
                self.assertEqual(self.scan()["status"], "inconclusive")
            self.manifest["coverage"][0][key] = 0
        self.manifest["coverage"].pop()
        self.assertEqual(self.scan()["status"], "inconclusive")

    def test_missing_process_environment_capture_is_inconclusive(self):
        self.manifest["artifacts"] = [item for item in self.manifest["artifacts"]
                                      if item["scope"] == "filesystem"]
        self.assertEqual(self.scan()["status"], "inconclusive")

    def test_hash_mismatch_or_reused_capture_is_inconclusive(self):
        self.manifest["artifacts"][0]["sha256"] = "c" * 64
        self.assertEqual(self.scan()["status"], "inconclusive")
        self.manifest["artifacts"].append(copy.deepcopy(self.manifest["artifacts"][1]))
        self.assertGreater(self.scan()["coverage_gaps"], 1)

    def test_scan_requires_before_and_after_agent_run(self):
        self.manifest["coverage"][0]["captured_at"] = FINISH
        self.assertEqual(self.scan()["status"], "inconclusive")

    def test_nonprivate_or_symlink_key_is_not_read(self):
        self.key_file.chmod(0o644)
        self.assertEqual(self.scan()["status"], "inconclusive")
        self.key_file.chmod(0o600)
        link = self.directory / "key-link"
        link.symlink_to(self.key_file)
        self.assertEqual(acceptance.scan(self.manifest, str(link))["status"], "inconclusive")

    def test_nonprivate_capture_is_not_read(self):
        Path(self.manifest["artifacts"][0]["path"]).chmod(0o644)
        self.assertEqual(self.scan()["unreadable_artifacts"], 1)

    def test_compressed_capture_cannot_pass(self):
        self.manifest["artifacts"][0]["encoding"] = "gzip"
        self.assertEqual(self.scan()["status"], "inconclusive")

    def test_empty_captures_cannot_establish_full_coverage(self):
        for artifact in self.manifest["artifacts"]:
            Path(artifact["path"]).write_bytes(b"")
            artifact["sha256"] = hashlib.sha256(b"").hexdigest()
        self.assertEqual(self.scan()["status"], "inconclusive")

    def test_oversized_key_file_cannot_match_only_its_prefix(self):
        self.key_file.write_bytes(b"x" * 4096 + b"\nmore")
        self.assertEqual(self.scan()["reason"], "invalid_private_key_file")

    def test_scan_cli_emits_only_sanitized_json(self):
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(self.manifest))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = acceptance.main(["scan", str(path), "--key-file", str(self.key_file)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["requirement"], "V1")
        self.assertNotIn(str(self.directory), output.getvalue())
        self.assertNotIn(self.fake_key.decode(), output.getvalue())


if __name__ == "__main__":
    unittest.main()
