#!/usr/bin/env python3
"""Explicit, ownership-checked Sprite service lifecycle; never runs inference."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import struct
import sys
import time
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nebius_configure import ConfigureError, STATE, atomic_write, read_file, safe_path

MARKER = STATE + "/service-owned.json"
CODE_ENV = "SPRITES_NEBIUS_SOURCE_SHA256="
SOURCE_FILES = ("proxy/server.py", "proxy/__init__.py", "proxy/vendor/__init__.py",
                "proxy/vendor/conversion.py", "proxy/requirements.txt")
MAX_SOURCE_BYTES = 4 * 1024 * 1024


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


def command(args, *, timeout=30):
    try:
        result = subprocess.run(["sprite-env", "services", *args], capture_output=True,
                                timeout=timeout, check=False)
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
        fingerprint = row.get("source_sha256")
        if fingerprint is not None and (not isinstance(fingerprint, str)
                or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint)):
            raise ValueError
        return row
    except (ValueError, TypeError, KeyError):
        raise ServiceError("Invalid service ownership record; manual review required") from None


def source_fingerprint(root=None):
    """Hash bounded proxy sources/requirements, not credentials or Git metadata.

    This detects stale reuse after checkout changes; it is not attestation of
    a process against a malicious local actor or of installed dependencies.
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    try:
        digest = hashlib.sha256(b"sprites-nebius-proxy-source-v1\0")
        total = 0
        # Keep this explicit: proxy/.venv and unrelated helper code are not the
        # running adapter's source, and must not be recursively traversed.
        for source in SOURCE_FILES:
            path = root / source
            # read_file rejects symlinks, nonregular files and oversized files.
            body = read_file(path)
            if body is None:
                raise ValueError
            total += len(body)
            if total > MAX_SOURCE_BYTES:
                raise ValueError
            name = source.encode()
            digest.update(struct.pack("!I", len(name)) + name)
            digest.update(struct.pack("!I", len(body)) + body)
        return digest.hexdigest()
    except (ConfigureError, OSError, ValueError):
        raise ServiceError("Cannot verify bounded proxy source identity; inspect owned service state") from None


def require_current_source(marker):
    """Legacy ownership remains usable for off, never silently upgraded/reused."""
    fingerprint = marker.get("source_sha256")
    definition = marker["definition"]
    arguments = definition.get("args")
    root = Path(__file__).resolve().parents[1]
    if (not fingerprint or definition.get("dir") != str(root)
            or not isinstance(arguments, list) or arguments.count(CODE_ENV + fingerprint) != 1
            or fingerprint != source_fingerprint(root)):
        raise ServiceError("Owned adapter source is changed or unrecorded; use approved --off then --start")


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


def port_available():
    """Refuse an existing listener before creating a new service; never evict it."""
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 8083))
    except OSError:
        raise ServiceError("Loopback port 8083 is unavailable; no service created") from None


async def _health(timeout):
    # One overall deadline includes headers/body, even for a slow local peer.
    import httpx
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", "http://127.0.0.1:8083/health") as response:
                if response.status_code != 200:
                    return False
                body = bytearray()
                async for chunk in response.aiter_raw():
                    body.extend(chunk)
                    if len(body) > 1024:
                        return False
                return json.loads(body) == {"status": "ok", "scope": "local adapter only"}


def healthy(timeout):
    import httpx
    try:
        return asyncio.run(_health(timeout))
    except (OSError, TimeoutError, ValueError, httpx.HTTPError):
        return False


def wait_ready(home, *, run=command, timeout=10, probe=healthy):
    """Check the exact owned service and local-only health within one deadline."""
    deadline = time.monotonic() + timeout

    def status_run(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceError("Owned adapter did not become healthy before the deadline")
        # Bound every production status read, including the post-health check.
        return command(args, timeout=remaining) if run is command else run(args)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceError("Owned adapter did not become healthy before the deadline")
        marker = load_marker(home)
        if marker is None or marker["phase"] != "confirmed":
            raise ServiceError("Owned service is not confirmed; retain state for inspection")
        require_current_source(marker)
        row = matching_service(marker, services(status_run))
        if row is None or runtime_status(row) in ("stopped", "failed"):
            raise ServiceError("Owned adapter exited before becoming healthy")
        remaining = deadline - time.monotonic()
        if remaining > 0 and runtime_status(row) == "running" and probe(min(0.5, remaining)):
            if load_marker(home) != marker:
                raise ServiceError("Service ownership changed during readiness")
            row = matching_service(marker, services(status_run))
            if row is None or runtime_status(row) != "running":
                raise ServiceError("Owned adapter stopped during readiness")
            require_current_source(marker)
            if time.monotonic() < deadline:
                return
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def start_owned(home, *, run=command, python=None, locked=False):
    home = Path(home)
    with ownership_lock(home, locked=locked):
        return _start_owned(home, run=run, python=python)


def _start_owned(home, *, run, python):
    if read_file(safe_path(home, STATE + "/pending.json")) is not None:
        raise ServiceError("Recover the interrupted configuration before starting a service")
    marker_path = safe_path(home, MARKER)
    if marker_path.exists():
        marker = load_marker(home)
        require_current_source(marker)
        row = matching_service(marker, services(run))
        if row and marker["phase"] == "confirmed" and runtime_status(row) == "running":
            require_current_source(marker)
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
    fingerprint = source_fingerprint(root)
    executable = "/usr/bin/env"
    # Services normally inherit the Sprite environment. Drop it explicitly;
    # isolated Python also ignores PYTHONPATH/user-site configuration.
    arguments = ["-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=" + str(home),
                 CODE_ENV + fingerprint,
                 str(Path(python or sys.executable).absolute()), "-I",
                 str(root / "proxy/server.py"), "--config", str(config)]
    if any("," in value or "\n" in value for value in [executable, str(root), *arguments]):
        raise ServiceError("Service paths must not contain CLI separators")
    definition = {"name": "sprites-nebius-" + uuid.uuid4().hex, "cmd": executable,
                  "args": arguments, "dir": str(root), "env": {}, "needs": [], "http_port": None}
    if any(row.get("name") == definition["name"] for row in services(run)):
        raise ServiceError("Service name collision; nothing changed")
    port_available()
    # Persist intent before the external operation. An uncertain create must not
    # be retried automatically or forgotten by configure --off.
    marker = {"version": 1, "phase": "pending", "definition": definition,
              "source_sha256": fingerprint}
    atomic_write(marker_path, json.dumps(marker).encode())
    run(["create", definition["name"], "--cmd", executable, "--args", ",".join(arguments),
         "--dir", str(root), "--no-stream"])
    row = matching_service(load_marker(home), services(run))
    if not row:
        raise ServiceError("Service creation is unconfirmed; ownership record retained for review")
    status = runtime_status(row)
    atomic_write(marker_path, json.dumps({**marker, "phase": "confirmed"}).encode())
    require_current_source(marker)
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
        if args.start:
            with ownership_lock(Path.home()):
                wait_ready(Path.home())
            result["ready"] = True
        print(json.dumps(result))
        return 0
    except (ServiceError, ConfigureError, OSError, ImportError, ValueError):
        print(json.dumps({"status": "error", "detail": "Service operation could not be verified; no automatic retry. Review the private ownership record."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
