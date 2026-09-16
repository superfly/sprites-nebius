"""Offline, metadata-only acceptance evidence and Nebius usage reconciliation.

This module never contacts a service or runs agents. Only scan reads the explicitly
supplied host-only key file. Evidence must be collected and reviewed separately;
a ledger is not a test run.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


REQUIREMENTS = tuple("%s%d" % (prefix, number)
                     for prefix, count in (("S", 6), ("B", 6), ("L", 3), ("V", 10))
                     for number in range(1, count + 1))
STATUSES = {"pass", "fail", "inconclusive", "blocked"}
SOURCES = {"local-tests", "gateway-log", "gateway-playground", "nebius-billing",
           "agent-run", "host-scan", "manual-review", "publication", "outreach"}
MAX_BYTES = 8 * 1024 * 1024
MAX_COUNT = 2**63 - 1


class EvidenceError(Exception):
    """Deliberately excludes untrusted input and file contents from messages."""


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value, length=64):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{%d}" % length, value) is not None


def _instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise EvidenceError("invalid_utc_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
        return parsed
    except (ValueError, OverflowError):
        raise EvidenceError("invalid_utc_timestamp") from None


def _revision(value):
    if not _digest(value, 40):
        raise EvidenceError("invalid_tested_revision")
    return value


def _reference(value):
    if (not isinstance(value, dict) or not isinstance(value.get("source"), str)
            or value["source"] not in SOURCES):
        raise EvidenceError("invalid_evidence_reference")
    if not _digest(value.get("artifact_sha256")):
        raise EvidenceError("invalid_evidence_reference")
    # Do not echo unknown fields, paths, URLs, notes, prompts, headers, or bodies.
    return {"source": value["source"], "artifact_sha256": value["artifact_sha256"]}


def ledger(document):
    """Normalize all 25 requirements; missing/stale/duplicate evidence cannot pass."""
    if not isinstance(document, dict):
        raise EvidenceError("invalid_ledger")
    revision = _revision(document.get("tested_revision"))
    entries = document.get("entries")
    if not isinstance(entries, list) or len(entries) > 1000:
        raise EvidenceError("invalid_ledger_entries")
    grouped = {requirement: [] for requirement in REQUIREMENTS}
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("requirement"), str)
                or entry["requirement"] not in grouped):
            raise EvidenceError("invalid_requirement")
        grouped[entry["requirement"]].append(entry)
    results = []
    for requirement, matches in grouped.items():
        result = {"requirement": requirement, "status": "blocked", "timestamp": None,
                  "tested_revision": revision, "evidence": [], "reason": "missing_evidence"}
        if len(matches) > 1:
            result.update(status="inconclusive", reason="duplicate_requirement")
        elif matches:
            entry = matches[0]
            try:
                _instant(entry.get("timestamp"))
                _revision(entry.get("tested_revision"))
                if not isinstance(entry.get("status"), str) or entry["status"] not in STATUSES:
                    raise EvidenceError("invalid_status")
                references = entry.get("evidence")
                if not isinstance(references, list) or not references or len(references) > 100:
                    raise EvidenceError("missing_evidence_reference")
                result.update(timestamp=entry["timestamp"],
                              tested_revision=entry["tested_revision"],
                              evidence=[_reference(item) for item in references],
                              status=entry["status"], reason="recorded_evidence")
                if entry["tested_revision"] != revision:
                    result.update(status="inconclusive", reason="stale_revision")
            except EvidenceError as error:
                result.update(status="inconclusive", reason=str(error))
        results.append(result)
    statuses = {result["status"] for result in results}
    full = statuses == {"pass"}
    return {"mode": "evidence-ledger", "timestamp": utc_now(), "tested_revision": revision,
            "status": "pass" if full else "fail" if "fail" in statuses else "inconclusive",
            "full_spec_verified": full,
            "evidence_only": True, "results": results}


def _identifier(value):
    return (isinstance(value, str) and len(value) <= 200
            and re.fullmatch(r"[A-Za-z0-9_.:/-]+", value) is not None)


def _window(value):
    start, end = _instant(value.get("started_at")), _instant(value.get("finished_at"))
    if start >= end:
        raise EvidenceError("invalid_window")
    return start, end


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise EvidenceError("unknown_usage")
    return value


def _billing_count(value, unit):
    if unit == "tokens":
        return _count(value)
    if unit != "million-tokens" or not isinstance(value, str) or len(value) > 40:
        raise EvidenceError("invalid_billing_unit_or_count")
    # Console decimal text, not binary floating point. Full numbers only: an
    # integral conversion does not by itself establish that a value was exact.
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise EvidenceError("invalid_billing_unit_or_count")
    try:
        with localcontext() as context:
            context.prec = 80
            tokens = Decimal(value) * 1_000_000
        if tokens != tokens.to_integral_value() or not 0 <= tokens <= MAX_COUNT:
            raise EvidenceError("inexact_billing_count")
        return int(tokens)
    except InvalidOperation:
        raise EvidenceError("invalid_billing_unit_or_count") from None


def _reconcile(document):
    scope, gateway, billing = (document.get(key) for key in ("scope", "gateway", "billing"))
    if not all(isinstance(item, dict) for item in (scope, gateway, billing)):
        raise EvidenceError("missing_reconciliation_evidence")
    identity = ("project_id", "model", "connector_id", "sprite_id", "provider")
    if not all(_identifier(scope.get(key)) for key in identity):
        raise EvidenceError("invalid_scope_identity")
    org_id = scope.get("org_id")
    if not (_identifier(org_id) or type(org_id) is int and org_id > 0):
        raise EvidenceError("invalid_scope_identity")
    window = _window(scope)
    if scope.get("isolated") is not True or not _digest(scope.get("project_binding_sha256")):
        raise EvidenceError("unverified_project_binding_or_isolation")
    expected = scope.get("request_ids")
    if (not isinstance(expected, list) or not expected or len(expected) > 10000
            or not all(_identifier(item) for item in expected) or len(set(expected)) != len(expected)):
        raise EvidenceError("invalid_expected_requests")
    if gateway.get("complete") is not True or not _digest(gateway.get("artifact_sha256")):
        raise EvidenceError("incomplete_gateway_evidence")
    records = gateway.get("records")
    if not isinstance(records, list) or not records or len(records) > 10000:
        raise EvidenceError("missing_gateway_records")
    seen = set()
    totals = {"input_count": 0, "output_count": 0}
    for record in records:
        if not isinstance(record, dict) or record.get("event") != "gateway_inference_usage":
            raise EvidenceError("invalid_gateway_record")
        request_id = record.get("request_id")
        if not _identifier(request_id):
            raise EvidenceError("missing_request_identity")
        if request_id in seen:
            # Even identical duplicate records need an explicit reviewed export;
            # silently deduplicating might hide conflicting or partial captures.
            raise EvidenceError("duplicate_gateway_request")
        seen.add(request_id)
        if any(record.get(key) != scope[key]
               for key in ("connector_id", "sprite_id", "org_id", "provider", "model")):
            raise EvidenceError("mixed_gateway_scope")
        start, finish = _instant(record.get("started_at")), _instant(record.get("finished_at"))
        if not window[0] <= start <= finish <= window[1]:
            raise EvidenceError("gateway_request_outside_window")
        status = record.get("status")
        if (type(status) is not int or not 200 <= status < 300
                or record.get("outcome") != "completed"):
            raise EvidenceError("partial_or_failed_gateway_request")
        if record.get("usage_known") is not True or record.get("unit") != "tokens":
            raise EvidenceError("unknown_usage")
        for key in totals:
            totals[key] += _count(record.get(key))
    if seen != set(expected):
        raise EvidenceError("gateway_request_set_mismatch")
    if (billing.get("source") != "nebius-billing-usage" or billing.get("view") != "full-numbers"
            or billing.get("precision") != "exact" or not _digest(billing.get("artifact_sha256"))):
        raise EvidenceError("non_authoritative_or_rounded_billing")
    if billing.get("settled") is not True or billing.get("isolated") is not True:
        raise EvidenceError("unsettled_or_unrelated_billing")
    if (billing.get("project_id") != scope["project_id"] or billing.get("model") != scope["model"]
            or _window(billing) != window):
        raise EvidenceError("billing_scope_mismatch")
    if not _instant(billing.get("collected_at")) >= _instant(billing.get("data_through")) >= window[1]:
        raise EvidenceError("stale_billing_evidence")
    comparisons = {}
    for key, gateway_count in totals.items():
        provider_count = _billing_count(billing.get(key), billing.get("unit"))
        difference = abs(gateway_count - provider_count)
        within = difference * 100 <= provider_count * 5
        comparisons[key] = {"gateway": gateway_count, "nebius": provider_count,
                            "absolute_difference": difference, "within_five_percent": within}
    if not sum(item["nebius"] for item in comparisons.values()):
        raise EvidenceError("no_billable_usage_to_reconcile")
    passed = all(item["within_five_percent"] for item in comparisons.values())
    return {"status": "pass" if passed else "fail", "reason": "within_tolerance" if passed
            else "usage_mismatch", "request_count": len(seen), "counts": comparisons,
            "evidence": [{"source": "gateway-log", "artifact_sha256": gateway["artifact_sha256"]},
                         {"source": "nebius-billing", "artifact_sha256": billing["artifact_sha256"]},
                         {"source": "manual-review",
                          "artifact_sha256": scope["project_binding_sha256"]}]}


def reconcile(document):
    """Compare complete, exact, isolated accounting evidence; never infer zero."""
    if not isinstance(document, dict):
        raise EvidenceError("invalid_reconciliation")
    revision = _revision(document.get("tested_revision"))
    result = {"requirement": "V10", "timestamp": utc_now(), "tested_revision": revision,
              "status": "inconclusive", "full_spec_verified": False, "evidence": []}
    try:
        result.update(_reconcile(document))
    except EvidenceError as error:
        result["reason"] = str(error)
    return result


def _private_file(path):
    """Open host-only regular files without following a final symlink."""
    descriptor = None
    try:
        if not isinstance(path, str):
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                or metadata.st_uid != os.getuid()):
            raise ValueError
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        return handle
    except (OSError, ValueError, TypeError):
        raise EvidenceError("unreadable_or_nonprivate_capture") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _scan_artifact(path, needle, chunk_size=1024 * 1024):
    digest, found, count, tail = hashlib.sha256(), False, 0, b""
    with _private_file(path) as source:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            count += len(chunk)
            data = tail + chunk
            found = found or needle in data
            tail = data[-(len(needle) - 1):]
    return found, count, digest.hexdigest()


def scan(document, key_file):
    """Match a host-only key against explicit private, raw host captures.

    Capturing a Sprite is intentionally separate: this operation never executes
    there, sends the key anywhere, enumerates local files, or emits match text.
    """
    if not isinstance(document, dict):
        raise EvidenceError("invalid_scan_manifest")
    revision = _revision(document.get("tested_revision"))
    result = {"requirement": "V1", "timestamp": utc_now(), "tested_revision": revision,
              "full_spec_verified": False, "status": "inconclusive", "evidence_only": True,
              "artifacts_scanned": 0, "bytes_scanned": 0, "matching_artifacts": 0,
              "unreadable_artifacts": 0, "coverage_gaps": 0}
    try:
        with _private_file(key_file) as source:
            raw_key = source.read(4099)
        if len(raw_key) > 4098:
            raise EvidenceError("invalid_private_key_file")
        needle = raw_key.rstrip(b"\r\n")
        if not 16 <= len(needle) <= 4096 or any(byte in needle for byte in (b"\r", b"\n", b"\x00")):
            raise EvidenceError("invalid_private_key_file")
        start, finish = _window(document)
        coverage, artifacts = document.get("coverage"), document.get("artifacts")
        if (not isinstance(coverage, list) or not isinstance(artifacts, list)
                or not artifacts or len(artifacts) > 100000):
            raise EvidenceError("missing_scan_coverage")
        expected = {(phase, scope) for phase in ("before", "after")
                    for scope in ("filesystem", "process-environment")}
        declared, captured = set(), set()
        for item in coverage:
            if not isinstance(item, dict):
                raise EvidenceError("invalid_scan_coverage")
            pair = (item.get("phase"), item.get("scope"))
            if not all(isinstance(part, str) for part in pair) or pair not in expected:
                raise EvidenceError("invalid_scan_coverage")
            if pair in declared:
                result["coverage_gaps"] += 1
            declared.add(pair)
            captured_at = _instant(item.get("captured_at"))
            time_ok = captured_at <= start if pair[0] == "before" else captured_at >= finish
            zero_fields = ("unreadable_count", "excluded_count", "race_count")
            if (item.get("complete") is not True or not time_ok
                    or any(type(item.get(key)) is not int or item[key] != 0 for key in zero_fields)):
                result["coverage_gaps"] += 1
        seen_paths = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise EvidenceError("invalid_capture_artifact")
            pair = (artifact.get("phase"), artifact.get("scope"))
            path = artifact.get("path")
            if (not all(isinstance(part, str) for part in pair) or pair not in expected
                    or artifact.get("encoding") != "raw" or not _digest(artifact.get("sha256"))
                    or not isinstance(path, str)):
                raise EvidenceError("invalid_capture_artifact")
            # A path cannot be reused for both pre- and post-run evidence.
            canonical = os.path.abspath(path)
            if canonical in seen_paths:
                result["coverage_gaps"] += 1
                continue
            seen_paths.add(canonical)
            try:
                found, size, digest = _scan_artifact(path, needle)
                result["artifacts_scanned"] += 1
                result["bytes_scanned"] += size
                result["matching_artifacts"] += int(found)
                if digest != artifact["sha256"]:
                    result["coverage_gaps"] += 1
                elif size:
                    captured.add(pair)
            except (EvidenceError, OSError):
                result["unreadable_artifacts"] += 1
        result["coverage_gaps"] += len(expected - declared) + len(expected - captured)
        complete = not result["coverage_gaps"] and not result["unreadable_artifacts"]
        result.update(status="fail" if result["matching_artifacts"] else "pass" if complete else "inconclusive",
                      reason="key_match" if result["matching_artifacts"] else
                      "no_matches_in_complete_capture" if complete else "incomplete_scan_coverage")
    except EvidenceError as error:
        result.update(reason=str(error), status="fail" if result["matching_artifacts"] else "inconclusive")
    except OSError:
        result.update(reason="unreadable_or_nonprivate_capture",
                      status="fail" if result["matching_artifacts"] else "inconclusive")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate_json_key")
        result[key] = value
    return result


def read_document(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise EvidenceError("evidence_file_too_large")
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("invalid_json_number")))
    except (OSError, ValueError, UnicodeError):
        raise EvidenceError("unreadable_or_invalid_evidence") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("ledger", "reconcile", "scan"))
    parser.add_argument("evidence", help="Local, reviewed JSON evidence; never a credential file")
    parser.add_argument("--key-file", help="Host-only private key file; required only for scan")
    args = parser.parse_args(argv)
    if (args.command == "scan") != bool(args.key_file):
        parser.error("--key-file is required only for scan")
    try:
        document = read_document(args.evidence)
        if args.command == "scan":
            result = scan(document, args.key_file)
        else:
            result = ledger(document) if args.command == "ledger" else reconcile(document)
    except EvidenceError as error:
        result = {"status": "inconclusive", "full_spec_verified": False, "reason": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
