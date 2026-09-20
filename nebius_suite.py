"""Explicit-target acceptance coordinator. Preview by default; never retries.

Run on a trusted host with existing Sprite CLI authentication. No uploads,
installs, connector edits, service creation or provider keys in worker controls.
Operator-supplied V4/V10 evidence remains an explicit acceptance boundary.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

import nebius_acceptance as acceptance
import nebius_agents as agents
from nebius_capture import MAX_BYTES, MAX_FILES
from nebius_configure import atomic_write, safe_path
from nebius_verify import Client, ProbeError, access, gateway_url, inference, utc_now, write_denial

OPERATIONS = ("outside", "unlabeled", "access", "streaming", "codex", "opencode", "pi", "claude", "denial", "scan")
REQUIREMENTS = tuple("V" + str(i) for i in range(1, 11))
LIMIT = 2 * 1024 * 1024
MAX_SCAN_TIMEOUT = 20 * 60


class SuiteError(Exception):
    """Fixed reason codes only; no process output or credential-bearing errors."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value) is not None


def absolute_path(value):
    return (isinstance(value, str) and len(value) < 1024 and value.startswith("/")
            and re.fullmatch(r"/[A-Za-z0-9_./-]*", value) is not None
            and os.path.normpath(value) == value and not value.startswith("//")
            and not {".", ".."}.intersection(value.split("/")))


def validate_plan(plan):
    required = {"schema_version", "tested_revision", "gateway", "model", "org", "org_id",
                "labeled", "unlabeled", "agent_bin", "agent_timeout", "scan"}
    if not isinstance(plan, dict) or set(plan) != required or plan["schema_version"] != 1:
        raise SuiteError("invalid_plan_schema")
    acceptance._revision(plan["tested_revision"])
    if type(plan["org_id"]) is not int or not 0 < plan["org_id"] < 2**63:
        raise SuiteError("invalid_org_identity")
    gateway_url(plan["gateway"])
    if not identifier(plan["org"]) or not isinstance(plan["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", plan["model"]):
        raise SuiteError("invalid_plan_identity")
    for name in ("labeled", "unlabeled"):
        target = plan[name]
        if not isinstance(target, dict) or set(target) != {"name", "id", "checkout", "python"}:
            raise SuiteError("invalid_target")
        if not identifier(target["name"]) or not identifier(target["id"]):
            raise SuiteError("invalid_target_identity")
        if not all(absolute_path(target[k]) for k in ("checkout", "python")):
            raise SuiteError("invalid_target_path")
    if plan["labeled"]["id"] == plan["unlabeled"]["id"] or plan["labeled"]["name"] == plan["unlabeled"]["name"]:
        raise SuiteError("targets_must_differ")
    if not absolute_path(plan["agent_bin"]) or type(plan["agent_timeout"]) is not int or not 10 <= plan["agent_timeout"] <= 180:
        raise SuiteError("invalid_agent_limits")
    scan = plan["scan"]
    if not isinstance(scan, dict) or set(scan) != {"roots", "max_bytes", "max_files", "timeout"}:
        raise SuiteError("invalid_scan_scope")
    if (not isinstance(scan["roots"], list) or not 1 <= len(scan["roots"]) <= 32
            or any(not absolute_path(p) for p in scan["roots"])):
        raise SuiteError("invalid_scan_roots")
    if any(a == b or a == "/" or b.startswith(a + "/")
           for i, a in enumerate(scan["roots"]) for j, b in enumerate(scan["roots"]) if i != j):
        raise SuiteError("overlapping_scan_roots")
    if any(p == "/proc" or p.startswith("/proc/") or p == "/sys" or p.startswith("/sys/")
           or p == "/dev" or p.startswith("/dev/") and not (p == "/dev/shm" or p.startswith("/dev/shm/")) for p in scan["roots"]):
        raise SuiteError("virtual_scan_root")
    for key, low, high in (("max_bytes", 1, MAX_BYTES), ("max_files", 1, MAX_FILES), ("timeout", 1, MAX_SCAN_TIMEOUT)):
        if type(scan[key]) is not int or not low <= scan[key] <= high:
            raise SuiteError("invalid_scan_limits")
    return plan


def preview(plan):
    return {"status": "dry_plan", "full_spec_verified": False, "plan_sha256": digest(plan),
            "tested_revision": plan["tested_revision"], "org": plan["org"],
            "targets": {key: plan[key] for key in ("labeled", "unlabeled")},
            "operations": list(OPERATIONS), "candidate_versions": agents.PINS,
            "agent_commands": {name: agents.command(name, name) for name in ("codex", "opencode", "pi")},
            "claude_task": "One confined arithmetic edit/test invocation; up to six turns",
            "streaming": "Two requests, Chat and Responses, at most 256 requested output tokens each",
            "denial": "One empty POST /files; never retried",
            "scan": plan["scan"], "spend_warning": agents.SPEND_WARNING,
            "prerequisites": "Reviewed clean checkout at target revision on both Sprites; labeled home configured and owned Claude service ready. No resources are provisioned.",
            "v4": "Requires separately reviewed Playground evidence or accepted production-test equivalence",
            "v10": "Requires scoped operator gateway export and authoritative matching billing evidence"}


def row(requirement, status, reason, context, **extra):
    return {"requirement": requirement, "status": status, "reason": reason,
            "execution_context": context, **extra}


def normalize(checks, context):
    # Only trusted fixed check names and a status leave the worker. Never
    # forward model lists, raw agent output, provider error text or paths.
    result = []
    for item in checks:
        check = item.get("check")
        if check not in {*REQUIREMENTS, "S1", "S2", "S3 chat", "S3 responses", "S4 GET /files", "S4 GET /batches", "S4 GET /fine_tuning/jobs"}:
            raise SuiteError("unexpected_check")
        status = item.get("status")
        if status not in acceptance.STATUSES:
            status = "inconclusive"
        result.append(row(check, status, "observed_check", context))
    return result


def worker(control):
    """Fixed remote entry point; controls never contain the host key or paths."""
    plan = validate_plan(control["plan"])
    operation = control["operation"]
    if operation not in OPERATIONS or operation == "outside" or not Path("/.sprite").is_dir():
        raise SuiteError("invalid_worker_context")
    if agents.git_revision() != {"git_revision": plan["tested_revision"], "working_tree_dirty": False}:
        raise SuiteError("worker_revision_mismatch")
    context = "unlabeled-sprite" if operation == "unlabeled" else "labeled-sprite"
    capture = None
    samples = {"process": 0, "fixture": 0}
    if control["capture"]:
        from nebius_capture import CaptureWriter
        limits = {key: plan["scan"][key] for key in ("max_bytes", "max_files", "timeout")}
        # Include native run time; file reads still share this bounded budget.
        limits["timeout"] += plan["agent_timeout"]
        capture = CaptureWriter(sys.stdout.buffer, **limits)
    def process_sample(pid):
        capture.collect(process_ids=[pid])
        samples["process"] += 1
    def fixture_sample(root):
        capture.collect(roots=[str(root)])
        samples["fixture"] += 1
    try:
        client = Client(timeout=30)
        if operation in ("access", "unlabeled"):
            checks = access(client, plan["gateway"], "allowed" if operation == "access" else "unlabeled")
        elif operation == "streaming":
            checks = inference(client, plan["gateway"], plan["model"], 256)
        elif operation == "denial":
            checks = write_denial(client, plan["gateway"])
        elif operation in agents.PINS:
            if agents.load_selection(Path.home(), (operation,)) != (plan["gateway"], plan["model"]):
                raise SuiteError("configured_selection_mismatch")
            if operation == "claude":
                from proxy.service import ownership_lock, wait_ready
                with ownership_lock(Path.home()):
                    wait_ready(Path.home())
            options = argparse.Namespace(agents=operation, approve_agent_runs=True,
                                         approve_claude_fixture=operation == "claude", timeout=plan["agent_timeout"])
            find = lambda name: shutil.which(name, path=plan["agent_bin"] + os.pathsep + "/.sprite/bin:/usr/bin:/bin")
            report = agents.execute(options, which=find,
                on_process=process_sample if capture else None,
                on_fixture=fixture_sample if capture else None)
            checks = report["results"]
        else:
            if capture is None:
                raise SuiteError("scan_approval_required")
            pids = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdecimal()]
            capture.collect(roots=plan["scan"]["roots"], process_ids=pids)
            checks = []
        return {"results": normalize(checks, context), "tested_revision": plan["tested_revision"],
                "capture_samples": samples,
                "cleanup": ("restored" if all(r.get("cleanup") == "restored" for r in checks)
                            else "needs-attention") if operation in agents.PINS else "not-required"}
    finally:
        if capture:
            capture.finish()


class PipeReader:
    """A blocking pipe interface with a single deadline, including stalled EOF."""
    def __init__(self, pipe, deadline):
        self.pipe, self.deadline = pipe, deadline

    def read(self, size):
        if not 0 <= size <= LIMIT:
            raise SuiteError("invalid_stream_read")
        if size == 0:
            return b""
        with selectors.DefaultSelector() as selector:
            selector.register(self.pipe, selectors.EVENT_READ)
            wait = self.deadline - time.monotonic()
            if wait <= 0 or not selector.select(wait):
                raise SuiteError("transport_timeout_no_retry")
        return os.read(self.pipe.fileno(), size)


def bounded_json(stream):
    body = bytearray()
    while True:
        chunk = stream.read(min(65536, LIMIT + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > LIMIT:
            raise SuiteError("worker_output_limit")
    try:
        return json.loads(body, object_pairs_hook=acceptance._unique_object)
    except (ValueError, UnicodeError):
        raise SuiteError("invalid_worker_result") from None


def transport(argv, *, timeout, capture=None):
    """Never persist or print stdout/stderr; capture output may contain secrets."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "SPRITE_TOKEN") if k in os.environ}
    # A failed CLI Start may follow an ambiguous dispatch. Do not let its
    # default startup retries repeat an operation the suite records only once.
    env["SPRITE_EXEC_MAX_RETRIES"] = "1"
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, start_new_session=True)
    deadline = time.monotonic() + timeout
    errors = bytearray()
    overflow = threading.Event()
    def drain():
        while True:
            part = proc.stderr.read(65536)
            if not part:
                return
            if len(errors) + len(part) <= LIMIT:
                errors.extend(part)
            else:
                overflow.set()
                proc.kill()
                return
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    scanned = None
    try:
        source = PipeReader(proc.stdout, deadline)
        scanned = capture(source) if capture else None
        result = None if capture else bounded_json(source)
        code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        thread.join(timeout=max(0.01, deadline - time.monotonic()))
        if code or overflow.is_set() or thread.is_alive():
            if capture:
                return {"results": [], "scan": scanned, "cleanup": "needs-attention"}
            raise SuiteError("worker_failed_or_uncertain_no_retry")
        if capture:
            try:
                result = json.loads(errors, object_pairs_hook=acceptance._unique_object)
            except (ValueError, UnicodeError):
                return {"results": [], "scan": scanned, "cleanup": "needs-attention"}
            if not isinstance(result, dict):
                return {"results": [], "scan": scanned, "cleanup": "needs-attention"}
            result["scan"] = scanned
        elif isinstance(result, dict):
            result.pop("scan", None)  # Only the host matcher may produce V1 evidence.
        return result
    except Exception:
        if scanned is not None and scanned.get("status") == "fail":
            return {"results": [], "scan": scanned, "cleanup": "needs-attention"}
        raise
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                proc.kill()
        proc.wait()
        thread.join(timeout=1)
        proc.stdout.close()
        proc.stderr.close()


def invoke(plan, operation, *, key_file=None, scan_approved=False):
    if operation == "outside":
        return {"results": normalize(access(Client(), plan["gateway"], "outside"), "host"), "cleanup": "not-required"}
    cli = shutil.which("sprite")
    if not cli:
        raise SuiteError("sprite_cli_missing")
    target = plan["unlabeled" if operation == "unlabeled" else "labeled"]
    capturing = scan_approved and (operation in agents.PINS or operation == "scan")
    matcher = None
    if capturing:
        from nebius_capture import read_host_key, scan
        key = read_host_key(key_file)  # Validate BEFORE dispatch, never sent remotely.
        matcher = lambda source: scan(source, key=key,
            max_bytes=plan["scan"]["max_bytes"], max_files=plan["scan"]["max_files"],
            timeout=plan["scan"]["timeout"] + plan["agent_timeout"] + 30)
    # Name reuse must not silently retarget an approved run to another Sprite.
    identity = transport([cli, "api", "-o", plan["org"], "/v1/sprites/" + target["name"],
                          "--", "--silent", "--show-error", "--fail"], timeout=30)
    if (not isinstance(identity, dict) or identity.get("id") != target["id"]
            or identity.get("organization") != plan["org"] or identity.get("name") != target["name"]):
        raise SuiteError("sprite_identity_mismatch")
    labels = identity.get("labels", [])
    if not isinstance(labels, list) or ("nebius" in labels) != (operation != "unlabeled"):
        raise SuiteError("sprite_label_mismatch")
    control = {"plan": plan, "operation": operation, "capture": capturing}
    encoded = base64.urlsafe_b64encode(canonical(control)).decode()
    bootstrap = "import sys;sys.path.insert(0,'.');from nebius_suite import worker_main;worker_main(sys.argv[1])"
    argv = [cli, "exec", "-o", plan["org"], "-s", target["name"], "--no-port-forward",
            "--dir", target["checkout"], "--", target["python"], "-I", "-B", "-c", bootstrap, encoded]
    return transport(argv, timeout=plan["agent_timeout"] + plan["scan"]["timeout"] + 180, capture=matcher)


def checked_result(plan, operation, value):
    """Treat remote metadata as untrusted; emit only an exact safe vocabulary."""
    context = "host" if operation == "outside" else "unlabeled-sprite" if operation == "unlabeled" else "labeled-sprite"
    expected = {"outside": ["V2"], "unlabeled": ["V3"],
                "access": ["S1", "S2", "S4 GET /files", "S4 GET /batches", "S4 GET /fine_tuning/jobs"],
                "streaming": ["S3 chat", "S3 responses"], "denial": ["V9"], "scan": []}
    expected.update({name: [check] for name, check in agents.CHECKS.items()})
    if not isinstance(value, dict):
        raise SuiteError("invalid_executor_result")
    clean = {"results": [], "cleanup": "needs-attention"}
    items = value.get("results")
    valid = (isinstance(items, list) and len(items) == len(expected[operation])
             and all(isinstance(item, dict) for item in items)
             and [item.get("requirement") for item in items] == expected[operation]
             and (operation == "outside" or value.get("tested_revision") == plan["tested_revision"]))
    if valid:
        for item in items:
            status = item.get("status")
            if not isinstance(status, str) or status not in acceptance.STATUSES or item.get("execution_context") != context:
                valid = False
                break
            clean["results"].append(row(item["requirement"], status, "observed_check", context))
    if not valid:
        clean["results"] = []
    elif value.get("cleanup") in ("restored", "not-required"):
        clean["cleanup"] = value["cleanup"]
    sample = value.get("capture_samples")
    if isinstance(sample, dict) and all(type(sample.get(k)) is int and sample[k] == 1 for k in ("process", "fixture")):
        clean["capture_samples"] = {"process": 1, "fixture": 1}
    scanned = value.get("scan")
    # These fields are produced by the HOST matcher, not the remote report.
    if isinstance(scanned, dict):
        clean["scan"] = {"status": "inconclusive", "files": 0, "environments": 0, "bytes": 0, "matching_objects": 0}
        for key in ("files", "environments", "bytes", "matching_objects"):
            count = scanned.get(key)
            if type(count) is int and 0 <= count <= MAX_BYTES:
                clean["scan"][key] = count
        coverage = scanned.get("coverage")
        names = ("files", "environments", "bytes", "unreadable", "races", "excluded", "capped")
        if isinstance(coverage, dict) and all(type(coverage.get(k)) is int and 0 <= coverage[k] <= MAX_BYTES for k in names):
            clean["scan"]["coverage"] = {k: coverage[k] for k in names}
        if clean["scan"]["matching_objects"] or scanned.get("status") == "fail":
            clean["scan"]["status"] = "fail"
        elif (valid and scanned.get("status") == "pass" and clean["scan"]["files"] > 0
              and clean["scan"]["environments"] > 0
              and (operation == "scan" or clean.get("capture_samples") == {"process": 1, "fixture": 1})):
            clean["scan"]["status"] = "pass"
    return clean


def worker_main(encoded):
    capture = False
    try:
        if len(encoded) > 32768:
            raise SuiteError("worker_control_limit")
        control = json.loads(base64.b64decode(encoded, altchars=b"-_", validate=True))
        if not isinstance(control, dict) or set(control) != {"plan", "operation", "capture"} or type(control["capture"]) is not bool:
            raise SuiteError("invalid_worker_control")
        capture = control["capture"]
        result = worker(control)
    except Exception:
        result = {"results": [], "status": "inconclusive", "reason": "worker_failed_no_retry", "cleanup": "needs-attention"}
    print(json.dumps(result), file=sys.stderr if capture else sys.stdout, flush=True)


def permitted(operation, approvals):
    if operation == "outside":
        return approvals.get("probes", False)
    if not approvals.get("exec", False):
        return False
    if operation in agents.PINS:
        return approvals.get("agents", False) and (operation != "claude" or approvals.get("claude", False))
    return approvals.get({"unlabeled": "probes", "access": "probes", "streaming": "inference",
                          "denial": "denial", "scan": "scan"}[operation], False)


def assess(plan, state, *, v4=None, billing=None, scan_acceptance=None):
    results = {r: row(r, "blocked", "not_observed", "none") for r in REQUIREMENTS}
    for entry in state["operations"].values():
        for item in entry.get("results", []):
            if item["requirement"] in results:
                results[item["requirement"]] = item
    scans = [state["operations"].get(op, {}).get("scan") for op in (*agents.PINS, "scan")]
    if any(s and s.get("status") == "fail" for s in scans):
        results["V1"] = row("V1", "fail", "key_match", "host")
    elif all(s and s.get("status") == "pass" for s in scans):
        accepted = (isinstance(scan_acceptance, dict) and scan_acceptance.get("plan_sha256") == digest(plan)
                    and scan_acceptance.get("profile") == "lifecycle-v1"
                    and acceptance._digest(scan_acceptance.get("review_sha256")))
        results["V1"] = row("V1", "pass" if accepted else "inconclusive",
                            "no_match_in_accepted_sampled_scope" if accepted else "scan_scope_review_required", "host")
        if accepted:
            results["V1"]["evidence"] = [{"source": "manual-review", "artifact_sha256": scan_acceptance["review_sha256"]}]
    elif any(scans):
        results["V1"] = row("V1", "inconclusive", "incomplete_scan_coverage", "host")
    if v4 is not None:
        if not isinstance(v4, dict) or v4.get("route") not in ("gateway-playground", "production-test"):
            raise SuiteError("invalid_v4_route")
        evidence = acceptance.ledger(v4.get("ledger"))
        entry = next(r for r in evidence["results"] if r["requirement"] == "V4")
        bound = v4.get("context") == {"org_id": plan["org_id"], "sprite_id": plan["labeled"]["id"], "gateway": plan["gateway"]}
        accepted = v4["route"] == "gateway-playground" or acceptance._digest(v4.get("equivalence_sha256"))
        if evidence["tested_revision"] == plan["tested_revision"] and bound and accepted:
            results["V4"] = row("V4", entry["status"], "reviewed_operator_evidence", "operator-evidence", evidence=entry["evidence"])
            if v4["route"] == "production-test":
                results["V4"]["evidence"].append({"source": "manual-review", "artifact_sha256": v4["equivalence_sha256"]})
    if billing is not None:
        item = acceptance.reconcile(billing)
        scope = billing.get("scope", {})
        bound = (billing.get("tested_revision") == plan["tested_revision"]
                 and scope.get("connector_id") == plan["gateway"].rsplit("/", 1)[1]
                 and scope.get("sprite_id") == plan["labeled"]["id"] and scope.get("model") == plan["model"]
                 and scope.get("org_id") == plan["org_id"] and scope.get("provider") == "custom_api")
        results["V10"] = row("V10", item["status"] if bound else "inconclusive",
                             "reconciled_evidence" if bound else "evidence_scope_mismatch", "operator-evidence")
        if bound:
            results["V10"].update(evidence=item["evidence"], counts=item.get("counts", {}))
    state["results"] = list(results.values())
    state["verification_complete"] = all(item["status"] == "pass" for item in results.values())
    state["full_spec_verified"] = False
    state["all_checks_automated"] = False  # V4/V10 still require explicit operator inputs.
    state["cleanup"] = {"status": "needs-attention" if any(
        op.get("phase") == "dispatched" or op.get("cleanup") == "needs-attention"
        for op in state["operations"].values()) else "restored"}
    return state


def resumed_state(plan, previous):
    if (not isinstance(previous, dict) or previous.get("schema_version") != 1
            or previous.get("plan_sha256") != digest(plan)
            or previous.get("tested_revision") != plan["tested_revision"]
            or not acceptance._digest(previous.get("run_id"), 32)
            or not isinstance(previous.get("operations"), dict)
            or not set(previous["operations"]).issubset(OPERATIONS)):
        raise SuiteError("resume_context_mismatch")
    acceptance._instant(previous.get("started_at"))
    state = {k: previous[k] for k in ("schema_version", "run_id", "plan_sha256", "tested_revision", "started_at")}
    state["operations"] = {}
    for operation, old in previous["operations"].items():
        if not isinstance(old, dict) or old.get("phase") not in ("dispatched", "completed") or type(old.get("attempts")) is not int or old["attempts"] != 1:
            raise SuiteError("invalid_resume_operation")
        acceptance._instant(old.get("started_at"))
        entry = {"phase": old["phase"], "attempts": 1, "started_at": old["started_at"]}
        if "finished_at" in old:
            acceptance._instant(old["finished_at"])
            entry["finished_at"] = old["finished_at"]
        if old["phase"] == "completed":
            clean = checked_result(plan, operation, {**old, "tested_revision": plan["tested_revision"]})
            entry.update(clean)
        else:
            entry.update(cleanup="needs-attention", reason="operation_failed_or_uncertain_no_retry")
        state["operations"][operation] = entry
    return state


def run_suite(plan, approvals, *, previous=None, save=lambda _: None, executor=invoke,
              key_file=None, v4=None, billing=None, scan_acceptance=None):
    plan = validate_plan(plan)
    if previous is None:
        state = {"schema_version": 1, "run_id": uuid.uuid4().hex, "plan_sha256": digest(plan),
                 "tested_revision": plan["tested_revision"], "started_at": utc_now(), "operations": {}}
    else:
        state = resumed_state(plan, previous)
    if approvals.get("scan") and not key_file:
        raise SuiteError("host_key_file_required")
    # Validate supplied operator evidence before dispatching any paid operation.
    assess(plan, state, v4=v4, billing=billing, scan_acceptance=scan_acceptance)
    stopped = any(item.get("phase") == "dispatched" or item.get("cleanup") == "needs-attention"
                  or any(r["status"] != "pass" for r in item.get("results", []))
                  or item.get("scan", {}).get("status", "pass") != "pass"
                  for item in state["operations"].values())
    for operation in OPERATIONS:
        # Even failed/inconclusive completed operations are immutable within a
        # run. An uncertain dispatch is never replayed by --resume.
        if stopped or operation in state["operations"] or not permitted(operation, approvals):
            continue
        entry = {"phase": "dispatched", "started_at": utc_now(), "attempts": 1}
        state["operations"][operation] = entry
        state["verification_complete"] = False
        state["cleanup"] = {"status": "needs-attention"}
        save(state)
        try:
            execution_plan = plan
            if approvals.get("scan") and operation in (*agents.PINS, "scan"):
                captures = [item.get("scan", {}) for item in state["operations"].values()]
                byte_budget = plan["scan"]["max_bytes"] - sum(c.get("bytes", 0) for c in captures)
                file_budget = plan["scan"]["max_files"] - sum(c.get("files", 0) + c.get("environments", 0) for c in captures)
                if byte_budget <= 0 or file_budget <= 0:
                    raise SuiteError("aggregate_capture_budget_exhausted")
                execution_plan = {**plan, "scan": {**plan["scan"], "max_bytes": byte_budget, "max_files": file_budget}}
            result = checked_result(plan, operation, executor(execution_plan, operation,
                                    key_file=key_file, scan_approved=approvals.get("scan", False)))
            entry.update(phase="completed", results=result["results"], cleanup=result.get("cleanup", "needs-attention"))
            if "scan" in result:
                entry["scan"] = result["scan"]
            if "capture_samples" in result:
                entry["capture_samples"] = result["capture_samples"]
            stopped = (entry["cleanup"] == "needs-attention" or not result["results"] and operation != "scan"
                       or any(r["status"] != "pass" for r in result["results"])
                       or result.get("scan", {}).get("status", "pass") != "pass")
        except Exception:
            entry.update(reason="operation_failed_or_uncertain_no_retry", cleanup="needs-attention")
            stopped = True
        entry["finished_at"] = utc_now()
        save(state)
    state["finished_at"] = utc_now()
    assess(plan, state, v4=v4, billing=billing, scan_acceptance=scan_acceptance)
    save(state)
    return state


@contextmanager
def result_file(path, resume):
    """Single writer, private result; never overwrite an unrelated existing file."""
    path = Path(path).absolute()
    safe_path(path.parent, path.name)
    lockpath = path.with_name(path.name + ".lock")
    fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SuiteError("unsafe_result_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = None
        if path.exists():
            if not resume:
                raise SuiteError("result_already_exists_use_resume")
            with acceptance._private_file(str(path)) as source:
                previous = bounded_json(source)
        elif resume:
            raise SuiteError("resume_result_missing")
        yield previous, lambda state: atomic_write(path, json.dumps(state, indent=2).encode())
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Explicit-target local JSON plan; no credentials")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--result", help="Private local result, required for run/resume")
    parser.add_argument("--key-file", help="Approved private host key file; never sent to worker")
    parser.add_argument("--v4-evidence", help="Reviewed requirement ledger for Playground/accepted equivalent")
    parser.add_argument("--billing-evidence", help="Reviewed V10 reconciliation JSON")
    parser.add_argument("--scan-acceptance", help="Reviewed lifecycle scan-scope acceptance bound to this plan")
    for name in ("probes", "exec", "agents", "claude", "inference", "denial", "scan"):
        parser.add_argument("--approve-" + name, action="store_true", help="Record separately obtained scoped approval")
    args = parser.parse_args(argv)
    try:
        plan = validate_plan(acceptance.read_document(args.plan))
        if not (args.run or args.resume):
            report = preview(plan)
        else:
            if not args.result:
                raise SuiteError("private_result_path_required")
            approvals = {name: getattr(args, "approve_" + name) for name in ("probes", "exec", "agents", "claude", "inference", "denial", "scan")}
            with result_file(args.result, args.resume) as (previous, save):
                report = run_suite(plan, approvals, previous=previous, save=save, key_file=args.key_file,
                    v4=acceptance.read_document(args.v4_evidence) if args.v4_evidence else None,
                    billing=acceptance.read_document(args.billing_evidence) if args.billing_evidence else None,
                    scan_acceptance=acceptance.read_document(args.scan_acceptance) if args.scan_acceptance else None)
        print(json.dumps(report, indent=2))
        return 0 if report.get("verification_complete") or report.get("status") == "dry_plan" else 1
    except (SuiteError, acceptance.EvidenceError, OSError, ValueError, argparse.ArgumentTypeError, agents.AgentError, ProbeError):
        print(json.dumps({"status": "inconclusive", "reason": "suite_preflight_or_evidence_failed", "full_spec_verified": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
