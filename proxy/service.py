#!/usr/bin/env python3
"""Explicit, ownership-checked Sprite service lifecycle; never runs inference."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nebius_configure import ConfigureError, STATE, atomic_write, read_file, safe_path

MARKER = STATE + "/service-owned.json"


class ServiceError(Exception):
    """Static diagnostic; command output may contain private service metadata."""


@contextmanager
def ownership_lock(home, *, locked=False):
    # Configure --off already holds this exact lock through its file transaction.
    if locked:
        yield
        return
    state_dir = safe_path(home, STATE)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    path = safe_path(home, STATE + "/lock")
    with path.open("a") as handle:
        os.chmod(path, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def command(args):
    try:
        result = subprocess.run(["sprite-env", "services", *args], capture_output=True,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ServiceError("Service operation failed or timed out; inspect the owned service before retrying") from None
    if result.returncode:
        raise ServiceError("Service operation failed; output omitted")
    return result.stdout


def services(run):
    try:
        raw = run(["list"])
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError
        rows = json.loads(raw)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        return rows
    except (ValueError, TypeError):
        raise ServiceError("Unrecognized Sprite service listing; no service changed") from None


def load_marker(home):
    raw = read_file(safe_path(home, MARKER))
    if raw is None:
        return None
    try:
        row = json.loads(raw)
        if (not isinstance(row, dict) or row.get("version") != 1
                or row.get("phase") not in ("pending", "confirmed")
                or not isinstance(row.get("definition"), dict)):
            raise ValueError
        expected = row["definition"]
        name = expected["name"]
        if not isinstance(name, str) or not name.startswith("sprites-nebius-") or len(name) != 47:
            raise ValueError
        int(name[15:], 16)
        if set(expected) != {"name", "cmd", "args", "dir", "env", "needs", "http_port"}:
            raise ValueError
        return row
    except (ValueError, TypeError, KeyError):
        raise ServiceError("Invalid service ownership record; manual review required") from None


def matching_service(marker, rows):
    expected = marker["definition"]
    matches = [row for row in rows if row.get("name") == expected["name"]]
    if len(matches) > 1:
        raise ServiceError("Ambiguous service identity; no service changed")
    if not matches:
        return None
    row = matches[0]
    for key in ("name", "cmd", "args", "dir"):
        if row.get(key) != expected[key]:
            raise ServiceError("Owned service definition changed; no service changed")
    for key, empty in (("env", {}), ("needs", []), ("http_port", None)):
        if (row.get(key) or empty) != expected[key]:
            raise ServiceError("Owned service routing, dependencies, or environment changed")
    return row


def runtime_status(row):
    state = row.get("state")
    if not isinstance(state, dict) or not isinstance(state.get("status"), str):
        raise ServiceError("Unrecognized service runtime state")
    return state["status"]


def start_owned(home, *, run=command, python=None):
    home = Path(home)
    with ownership_lock(home):
        return _start_owned(home, run=run, python=python)


def _start_owned(home, *, run, python):
    if read_file(safe_path(home, STATE + "/pending.json")) is not None:
        raise ServiceError("Recover the interrupted configuration before starting a service")
    marker_path = safe_path(home, MARKER)
    if marker_path.exists():
        marker = load_marker(home)
        row = matching_service(marker, services(run))
        if row and marker["phase"] == "confirmed" and runtime_status(row) == "running":
            return {"status": "already_running", "service": row["name"]}
        raise ServiceError("An owned service operation is incomplete; use --off before starting again")
    # Validate settings and installed runtime before creating any service.
    from proxy.server import Settings
    config = safe_path(home, STATE + "/proxy.json")
    try:
        Settings.load(json.loads(read_file(config)))
    except (ValueError, TypeError):
        raise ServiceError("Configure the reviewed proxy settings first") from None
    if not safe_path(home, STATE + "/active.json").is_file():
        raise ServiceError("Active configuration ownership is required")
    root = Path(__file__).resolve().parents[1]
    executable = "/usr/bin/env"
    # Services normally inherit the Sprite environment. Drop it explicitly;
    # isolated Python also ignores PYTHONPATH/user-site configuration.
    arguments = ["-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=" + str(home),
                 str(Path(python or sys.executable).absolute()), "-I",
                 str(root / "proxy/server.py"), "--config", str(config)]
    if any("," in value or "\n" in value for value in [executable, str(root), *arguments]):
        raise ServiceError("Service paths must not contain CLI separators")
    definition = {"name": "sprites-nebius-" + uuid.uuid4().hex, "cmd": executable,
                  "args": arguments, "dir": str(root), "env": {}, "needs": [], "http_port": None}
    if any(row.get("name") == definition["name"] for row in services(run)):
        raise ServiceError("Service name collision; nothing changed")
    # Persist intent before the external operation. An uncertain create must not
    # be retried automatically or forgotten by configure --off.
    marker = {"version": 1, "phase": "pending", "definition": definition}
    atomic_write(marker_path, json.dumps(marker).encode())
    run(["create", definition["name"], "--cmd", executable, "--args", ",".join(arguments),
         "--dir", str(root), "--no-stream"])
    row = matching_service(load_marker(home), services(run))
    if not row:
        raise ServiceError("Service creation is unconfirmed; ownership record retained for review")
    status = runtime_status(row)
    atomic_write(marker_path, json.dumps({**marker, "phase": "confirmed"}).encode())
    return {"status": "created", "service": definition["name"],
            "runtime_status": status,
            "live_agent_verified": False}


def stop_owned(home, *, run=command, locked=False):
    """Remove only the exact definition this setup created; retain runtime logs."""
    home = Path(home)
    with ownership_lock(home, locked=locked):
        return _stop_owned(home, run=run)


def _stop_owned(home, *, run):
    marker = load_marker(home)
    if marker is None:
        return False
    row = matching_service(marker, services(run))
    if row is None and marker["phase"] == "pending":
        raise ServiceError("Uncertain service creation cannot be cleared by an empty listing; manual review required")
    if row:
        name = row["name"]
        # The public stop endpoint returns 409 for an already exited service.
        # Resume cleanup from its terminal state instead of issuing stop twice.
        if runtime_status(row) == "running":
            run(["stop", name])
            row = matching_service(marker, services(run))
        if row:
            # The runtime's WaitForStop accepts stopped OR failed: SIGTERM
            # can leave exit code 143 and status failed after a successful
            # explicit stop. Deletion also removes restart state. Still reject
            # running/transitional states or a remaining process identifier.
            state = row.get("state", {})
            if (runtime_status(row) not in ("stopped", "failed")
                    or state.get("pid") not in (None, 0)
                    or state.get("host_pid") not in (None, 0)):
                raise ServiceError("Service stop is unconfirmed; configuration has not been restored")
        if row:
            run(["delete", name])
        if matching_service(marker, services(run)) is not None:
            raise ServiceError("Service deletion is unconfirmed; ownership record retained")
    safe_path(home, MARKER).unlink()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", action="store_true")
    mode.add_argument("--off", action="store_true")
    parser.add_argument("--approve-service-change", action="store_true")
    args = parser.parse_args(argv)
    if not args.approve_service_change:
        parser.error("Service changes require --approve-service-change and prior authorization")
    if not Path("/.sprite").is_dir():
        parser.error("Run this inside the intended Sprite")
    try:
        result = start_owned(Path.home()) if args.start else {"status": "off", "removed_owned_definition": stop_owned(Path.home())}
        print(json.dumps(result))
        return 0
    except (ServiceError, ConfigureError, OSError, ImportError, ValueError):
        print(json.dumps({"status": "error", "detail": "Service operation could not be verified; no automatic retry. Review the private ownership record."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
