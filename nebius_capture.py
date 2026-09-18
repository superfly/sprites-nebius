"""Bounded, keyless Sprite capture streamed directly to a trusted-host matcher.

Only regular files in explicit roots and requested live process environments are
sampled. This is not a snapshot: changed/unreadable objects make coverage
inconclusive. Symlinks, devices and virtual filesystems are excluded; /dev/shm
is data-bearing and allowed. Deleted files, memory, xattrs and transformed keys
are not covered. Callers must supply an outer transport/process watchdog: local
deadline checks cannot interrupt an uninterruptible filesystem read.

Never redirect the collector stream to a terminal or file. It may contain other
credentials. The collector never receives the comparison key. Only scan() reads
the host-only key, and returns aggregate metadata, never content or paths.
"""
import json
import os
from pathlib import Path
import stat
import struct
import time

from nebius_acceptance import _private_file


MAGIC = b"SPRITES-NEBIUS-SCAN-1\n"
CHUNK = 64 * 1024
MAX_BYTES = 4 * 1024**3
MAX_FILES = 100_000
COUNTERS = ("files", "environments", "bytes", "unreadable", "races", "excluded", "capped")


class CaptureError(Exception):
    """Fixed diagnostics only; never include input or captured contents."""


def _limits(max_bytes, max_files, timeout):
    if (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES
            or type(max_files) is not int or not 1 <= max_files <= MAX_FILES
            or type(timeout) not in (int, float) or not 0 < timeout <= 600):
        raise CaptureError("invalid_capture_limits")


def _path(value):
    if not isinstance(value, (str, Path)):
        raise CaptureError("invalid_capture_scope")
    value = str(value)
    if (not value.startswith("/") or len(value) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or value != os.path.normpath(value) or value.startswith("//")):
        raise CaptureError("invalid_capture_scope")
    return value


def _virtual(path):
    return (path == "/proc" or path.startswith("/proc/")
            or path == "/sys" or path.startswith("/sys/")
            or (path == "/dev" or path.startswith("/dev/"))
            and not (path == "/dev/shm" or path.startswith("/dev/shm/")))


def _directory(path):
    """Open every component without following links, including ancestors."""
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.split("/")[1:]:
            if not part:
                continue
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _frame(stream, kind, payload):
    if kind != b"D":
        payload = json.dumps(payload, separators=(",", ":")).encode()
    _write_all(stream, kind + struct.pack("!I", len(payload)) + payload)


def _write_all(stream, data):
    """Support short pipe writes without silently losing capture bytes."""
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if type(written) is not int or not 0 < written <= len(view):
            raise CaptureError("capture_transport_failed")
        view = view[written:]


def _unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CaptureError("duplicate_capture_field")
        value[key] = item
    return value


def _checked_key(key):
    if (not isinstance(key, bytes) or not 16 <= len(key) <= 4096
            or any(byte in key for byte in (b"\x00", b"\r", b"\n"))):
        raise CaptureError("invalid_host_key")
    return key


def read_host_key(key_file):
    """Validate locally BEFORE dispatch; never pass returned bytes to the Sprite."""
    try:
        with _private_file(key_file) as source:
            raw_key = source.read(4099)
        if len(raw_key) > 4098:
            raise CaptureError("invalid_host_key")
        return _checked_key(raw_key.rstrip(b"\r\n"))
    except Exception:
        raise CaptureError("invalid_host_key") from None


class CaptureWriter:
    """Compose lifecycle samples under one aggregate budget; no key is accepted."""

    def __init__(self, stream, *, max_bytes=64 * 1024**2, max_files=10_000, timeout=120):
        _limits(max_bytes, max_files, timeout)
        self.stream = stream
        self.options = {"max_bytes": max_bytes, "max_files": max_files, "timeout": timeout}
        self.state = {"coverage": dict.fromkeys(COUNTERS, 0),
                      "deadline": time.monotonic() + timeout}
        self.finished = False
        self.collections = 0
        _write_all(stream, MAGIC)

    def collect(self, *, roots=(), process_ids=(), _proc_root="/proc"):
        if self.finished:
            raise CaptureError("capture_already_finished")
        result = write(self.stream, roots=roots, process_ids=process_ids,
                       _proc_root=_proc_root, _state=self.state, **self.options)
        self.collections += 1
        return result

    def finish(self):
        if self.finished:
            raise CaptureError("capture_already_finished")
        if not self.collections:
            self.state["coverage"]["unreadable"] += 1
        if time.monotonic() >= self.state["deadline"]:
            self.state["coverage"]["capped"] = 1
        _frame(self.stream, b"R", self.state["coverage"])
        self.stream.flush()
        self.finished = True
        return dict(self.state["coverage"])


def write(stream, *, roots, process_ids=(), max_bytes=64 * 1024**2,
          max_files=10_000, timeout=120, _proc_root="/proc", _state=None):
    """Write a sensitive framed stream, never a key; return sanitized coverage.

    roots are explicit absolute directories. process_ids is an explicit sequence
    of positive PIDs (not a claim to include all processes). _proc_root is solely
    a fixture seam; no CLI/control document should expose it.
    """
    _limits(max_bytes, max_files, timeout)
    if not isinstance(roots, (list, tuple)) or not isinstance(process_ids, (list, tuple)):
        raise CaptureError("invalid_capture_scope")
    roots = tuple(_path(root) for root in roots)
    if (len(roots) > 64 or len(process_ids) > MAX_FILES or not roots and not process_ids
            or len(set(roots)) != len(roots) or any(_virtual(root) for root in roots)
            or any(type(pid) is not int or not 0 < pid < 2**31 for pid in process_ids)
            or len(set(process_ids)) != len(process_ids)):
        raise CaptureError("invalid_capture_scope")
    # Overlapping roots would silently count the same data twice.
    if any(a != b and (a == "/" or b.startswith(a + "/")) for a in roots for b in roots):
        raise CaptureError("overlapping_capture_roots")
    _proc_root = _path(_proc_root)
    coverage = dict.fromkeys(COUNTERS, 0) if _state is None else _state["coverage"]
    deadline = time.monotonic() + timeout if _state is None else _state["deadline"]
    if _state is None:
        _write_all(stream, MAGIC)

    def available():
        if time.monotonic() >= deadline:
            coverage["capped"] = 1
        return not coverage["capped"]

    def object_bytes(descriptor, kind):
        if coverage["files"] + coverage["environments"] >= max_files or not available():
            coverage["capped"] = 1
            return
        coverage[kind] += 1
        _frame(stream, b"B", {"kind": kind})
        length = 0
        try:
            while available():
                remaining = max_bytes - coverage["bytes"]
                data = os.read(descriptor, min(CHUNK, remaining + 1))
                if not data:
                    break
                if len(data) > remaining:
                    coverage["capped"] = 1
                    break
                _frame(stream, b"D", data)
                coverage["bytes"] += len(data)
                length += len(data)
        except OSError:
            coverage["unreadable"] += 1
        _frame(stream, b"E", {"bytes": length})

    def walk(directory, path, depth=0):
        if depth > 128:
            coverage["capped"] = 1
            return
        before = os.fstat(directory)
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not available():
                        return
                    child_path = path.rstrip("/") + "/" + entry.name
                    # /dev itself must be traversed to reach data-bearing shm;
                    # its other children remain explicitly excluded.
                    if _virtual(child_path) and child_path != "/dev":
                        coverage["excluded"] += 1
                        continue
                    descriptor = None
                    try:
                        expected = entry.stat(follow_symlinks=False)
                        if not (stat.S_ISDIR(expected.st_mode) or stat.S_ISREG(expected.st_mode)):
                            coverage["excluded"] += 1
                            continue
                        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                        if stat.S_ISDIR(expected.st_mode):
                            flags |= os.O_DIRECTORY
                        descriptor = os.open(entry.name, flags, dir_fd=directory)
                        actual = os.fstat(descriptor)
                        if (actual.st_dev, actual.st_ino, actual.st_mode) != (expected.st_dev, expected.st_ino, expected.st_mode):
                            coverage["races"] += 1
                            continue
                        if stat.S_ISDIR(actual.st_mode):
                            walk(descriptor, child_path, depth + 1)
                        else:
                            object_bytes(descriptor, "files")
                            after = os.fstat(descriptor)
                            if (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                coverage["races"] += 1
                    except OSError:
                        coverage["unreadable"] += 1
                    finally:
                        if descriptor is not None:
                            os.close(descriptor)
        except OSError:
            coverage["unreadable"] += 1
        after = os.fstat(directory)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            coverage["races"] += 1

    for root in roots:
        if not available():
            break
        descriptor = None
        try:
            descriptor = _directory(root)
            walk(descriptor, root)
        except OSError:
            coverage["unreadable"] += 1
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def process_identity(directory):
        descriptor = os.open("stat", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            body = os.read(descriptor, 8193)
            if len(body) > 8192:
                raise ValueError
            return int(body.rsplit(b") ", 1)[1].split()[19])
        finally:
            os.close(descriptor)

    for pid in process_ids:
        if not available():
            break
        directory = descriptor = None
        try:
            directory = _directory(_proc_root + "/" + str(pid))
            before = process_identity(directory)
            descriptor = os.open("environ", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError
            object_bytes(descriptor, "environments")
            if process_identity(directory) != before:
                coverage["races"] += 1
        except (OSError, ValueError, IndexError):
            coverage["unreadable"] += 1
        finally:
            for handle in (descriptor, directory):
                if handle is not None:
                    os.close(handle)
    if _state is None:
        _frame(stream, b"R", coverage)
        stream.flush()
    return dict(coverage)


def scan(stream, *, key_file=None, key=None, max_bytes=64 * 1024**2,
         max_files=10_000, timeout=120):
    """Match on the trusted host; key=bytes is a test/in-memory integration seam.

    Transport must be a finite stream for this scan, with an outer watchdog.
    Neither key nor any captured bytes are retained in the result.
    """
    result = {"requirement": "V1", "status": "inconclusive", "full_spec_verified": False,
              "files": 0, "environments": 0, "bytes": 0, "matching_objects": 0,
              "reason": "incomplete_capture"}
    try:
        _limits(max_bytes, max_files, timeout)
        if (key_file is None) == (key is None):
            raise CaptureError("invalid_host_key")
        if key_file is not None:
            key = read_host_key(key_file)
        _checked_key(key)
        deadline = time.monotonic() + timeout

        def read(length):
            data = bytearray()
            while len(data) < length:
                if time.monotonic() >= deadline:
                    raise CaptureError("capture_deadline")
                part = stream.read(length - len(data))
                if not isinstance(part, bytes) or not part:
                    raise CaptureError("truncated_capture")
                data.extend(part)
            return bytes(data)

        if read(len(MAGIC)) != MAGIC:
            raise CaptureError("invalid_capture_protocol")
        active, length, tail, found = False, 0, b"", False
        while True:
            header = read(5)
            kind, size = header[:1], struct.unpack("!I", header[1:])[0]
            if kind not in (b"B", b"D", b"E", b"R") or size > (CHUNK if kind == b"D" else 1024):
                raise CaptureError("invalid_capture_frame")
            payload = read(size)
            if kind == b"D":
                if not active or not payload or result["bytes"] + size > max_bytes:
                    raise CaptureError("invalid_capture_data")
                data = tail + payload
                if not found and key in data:
                    result["matching_objects"] += 1
                    found = True
                tail = data[-(len(key) - 1):]
                result["bytes"] += size
                length += size
                continue
            value = json.loads(payload, object_pairs_hook=_unique_fields)
            if not isinstance(value, dict):
                raise CaptureError("invalid_capture_metadata")
            if kind == b"B":
                category = value.get("kind")
                if active or value != {"kind": category} or category not in ("files", "environments"):
                    raise CaptureError("invalid_capture_object")
                if result["files"] + result["environments"] >= max_files:
                    raise CaptureError("capture_object_limit")
                result[category] += 1
                active, length, tail, found = True, 0, b"", False
            elif kind == b"E":
                if not active or value != {"bytes": length} or type(value["bytes"]) is not int:
                    raise CaptureError("invalid_capture_end")
                active = False
            else:
                if (active or set(value) != set(COUNTERS)
                        or any(type(v) is not int or not 0 <= v <= MAX_BYTES for v in value.values())
                        or any(value[k] != result[k] for k in ("files", "environments", "bytes"))
                        or value["capped"] not in (0, 1)):
                    raise CaptureError("invalid_capture_coverage")
                if stream.read(1):
                    raise CaptureError("trailing_capture_data")
                result["coverage"] = value
                complete = not any(value[k] for k in ("unreadable", "races", "capped"))
                result.update(status="fail" if result["matching_objects"] else "pass" if complete else "inconclusive",
                              reason="key_match" if result["matching_objects"] else "no_match_in_declared_scope" if complete else "coverage_gap")
                break
    except Exception:
        # Also suppress decoder/IO/private-file diagnostics that might contain
        # sensitive input. A known match remains a failure after later damage.
        result.update(status="fail" if result["matching_objects"] else "inconclusive",
                      reason="key_match" if result["matching_objects"] else "invalid_or_incomplete_capture")
    return result
