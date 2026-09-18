"""Synthetic fixture captures only; never inspect real processes or credentials."""
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import nebius_capture as capture


KEY = b"FAKE-NEBIUS-TEST-KEY-0123456789"


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.files = self.root / "files"
        self.files.mkdir()

    def collect(self, **options):
        stream = io.BytesIO()
        coverage = capture.write(stream, roots=[self.files], **options)
        return stream.getvalue(), coverage

    def scan(self, raw, **options):
        return capture.scan(io.BytesIO(raw), key=KEY, **options)

    def test_safe_regular_files_pass_and_paths_not_retained(self):
        (self.files / "private-path").write_bytes(b"ordinary fixture")
        raw, coverage = self.collect()
        result = self.scan(raw)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["files"], 1)
        self.assertEqual(coverage["bytes"], 16)
        self.assertNotIn(b"private-path", raw)
        self.assertNotIn("ordinary fixture", json.dumps(result))

    def test_cross_chunk_key_is_found_without_leaking_it(self):
        (self.files / "fixture").write_bytes(b"x" * (capture.CHUNK - 10) + KEY + b"suffix")
        raw, _ = self.collect()
        result = self.scan(raw)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["matching_objects"], 1)
        self.assertNotIn(KEY.decode(), json.dumps(result))

    def test_matcher_does_not_join_distinct_files(self):
        (self.files / "first").write_bytes(KEY[:15])
        (self.files / "second").write_bytes(KEY[15:])
        self.assertEqual(self.scan(self.collect()[0])["status"], "pass")

    def test_collector_has_no_key_parameter(self):
        with self.assertRaises(TypeError):
            capture.write(io.BytesIO(), roots=[self.files], key=KEY)

    def test_fake_private_host_key_file(self):
        key_file = self.root / "fake-key"
        key_file.write_bytes(KEY + b"\n")
        key_file.chmod(0o600)
        self.assertEqual(capture.read_host_key(str(key_file)), KEY)
        raw, _ = self.collect()
        self.assertEqual(capture.scan(io.BytesIO(raw), key_file=str(key_file))["status"], "pass")
        key_file.chmod(0o644)
        with self.assertRaisesRegex(capture.CaptureError, "^invalid_host_key$"):
            capture.read_host_key(str(key_file))
        self.assertEqual(capture.scan(io.BytesIO(raw), key_file=str(key_file))["status"], "inconclusive")
        key_file.chmod(0o600)
        key_file.write_bytes(b"x" * 4096 + b"\n\n\ntrailing")
        self.assertEqual(capture.scan(io.BytesIO(raw), key_file=str(key_file))["status"], "inconclusive")

    def test_symlinks_and_fifo_are_excluded_without_reading_targets(self):
        secret = self.root / "outside"
        secret.write_bytes(KEY)
        (self.files / "link").symlink_to(secret)
        os.mkfifo(self.files / "fifo")
        raw, coverage = self.collect()
        self.assertEqual(self.scan(raw)["status"], "pass")
        self.assertEqual(coverage["excluded"], 2)
        self.assertNotIn(KEY, raw)

    def test_symlink_in_root_ancestor_is_not_followed(self):
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "nested").mkdir()
        (actual / "nested/key").write_bytes(KEY)
        (self.root / "redirect").symlink_to(actual, target_is_directory=True)
        stream = io.BytesIO()
        capture.write(stream, roots=[self.root / "redirect/nested"])
        result = self.scan(stream.getvalue())
        self.assertEqual(result["status"], "inconclusive")
        self.assertNotIn(KEY, stream.getvalue())

    def test_missing_root_is_inconclusive(self):
        stream = io.BytesIO()
        capture.write(stream, roots=[self.root / "missing"])
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def test_invalid_scope_rejected_before_any_stream_output(self):
        for roots, pids in ((["relative"], ()), (["/tmp/../etc"], ()),
                            (["/tmp/new\nline"], ()),
                            (["/proc"], ()), (["/sys/test"], ()), (["/dev/random"], ()),
                            ([self.files, self.files], ()), ([self.root, self.files], ()),
                            ([self.files], (True,)), ([self.files], (1, 1)), ([], ())):
            with self.subTest(roots=roots, pids=pids):
                stream = io.BytesIO()
                with self.assertRaises(capture.CaptureError):
                    capture.write(stream, roots=roots, process_ids=pids)
                self.assertEqual(stream.getvalue(), b"")

    def test_caps_are_inconclusive_not_truncated_success(self):
        (self.files / "first").write_bytes(b"x" * 10)
        (self.files / "second").write_bytes(b"x")
        for options in ({"max_bytes": 5}, {"max_files": 1}):
            raw, coverage = self.collect(**options)
            self.assertEqual(coverage["capped"], 1)
            self.assertEqual(self.scan(raw)["status"], "inconclusive")

    def test_shared_writer_accumulates_lifecycle_samples(self):
        (self.files / "file").write_bytes(b"fixture")
        other = self.root / "other"
        other.mkdir()
        (other / "file").write_bytes(KEY)
        stream = io.BytesIO()
        writer = capture.CaptureWriter(stream)
        writer.collect(roots=[self.files])
        writer.collect(roots=[other])
        coverage = writer.finish()
        self.assertEqual(coverage["files"], 2)
        self.assertEqual(self.scan(stream.getvalue())["status"], "fail")
        with self.assertRaises(capture.CaptureError):
            writer.collect(roots=[other])
        with self.assertRaises(capture.CaptureError):
            writer.finish()

    def test_shared_writer_budget_is_not_reset(self):
        (self.files / "file").write_bytes(b"1234")
        stream = io.BytesIO()
        writer = capture.CaptureWriter(stream, max_bytes=6)
        writer.collect(roots=[self.files])
        writer.collect(roots=[self.files])
        writer.finish()
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def test_empty_writer_is_not_success(self):
        stream = io.BytesIO()
        capture.CaptureWriter(stream).finish()
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def test_deadline_is_inconclusive(self):
        stream = io.BytesIO()
        with patch.object(capture.time, "monotonic", side_effect=[0, 2]):
            capture.write(stream, roots=[self.files], timeout=1)
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def process_fixture(self):
        proc = self.root / "proc"
        folder = proc / "123"
        folder.mkdir(parents=True)
        (folder / "stat").write_bytes(b"123 (fake worker) S " + b"0 " * 18 + b"456 0\n")
        (folder / "environ").write_bytes(b"PLACEHOLDER=safe\x00OTHER=" + KEY + b"\x00")
        return proc

    def test_explicit_process_environment_fixture(self):
        proc = self.process_fixture()
        stream = io.BytesIO()
        capture.write(stream, roots=[], process_ids=[123], _proc_root=str(proc))
        result = self.scan(stream.getvalue())
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["environments"], 1)
        self.assertNotIn("OTHER", json.dumps(result))

    def test_exited_process_is_inconclusive(self):
        proc = self.root / "proc"
        proc.mkdir()
        stream = io.BytesIO()
        capture.write(stream, roots=[], process_ids=[123], _proc_root=str(proc))
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def test_reused_process_identity_is_inconclusive(self):
        proc = self.process_fixture()
        (proc / "123/environ").write_bytes(b"safe environment")
        original_read = os.read
        def read(descriptor, size):
            data = original_read(descriptor, size)
            if data == b"safe environment":
                (proc / "123/stat").write_bytes(b"123 (fake worker) S " + b"0 " * 18 + b"789 0\n")
            return data
        stream = io.BytesIO()
        with patch.object(capture.os, "read", side_effect=read):
            coverage = capture.write(stream, roots=[], process_ids=[123], _proc_root=str(proc))
        self.assertEqual(coverage["races"], 1)
        self.assertEqual(self.scan(stream.getvalue())["status"], "inconclusive")

    def test_regular_file_swapped_to_fifo_is_not_read(self):
        path = self.files / "file"
        path.write_bytes(b"safe")
        original_open = os.open
        def open_file(name, flags, **kwargs):
            if name == "file":
                path.unlink()
                os.mkfifo(path)
            return original_open(name, flags, **kwargs)
        with patch.object(capture.os, "open", side_effect=open_file):
            raw, coverage = self.collect()
        self.assertGreater(coverage["races"], 0)
        self.assertEqual(coverage["bytes"], 0)
        self.assertEqual(self.scan(raw)["status"], "inconclusive")

    def test_file_changed_during_read_is_inconclusive(self):
        path = self.files / "file"
        path.write_bytes(b"123")
        original_read = os.read
        changed = False
        def read(descriptor, size):
            nonlocal changed
            result = original_read(descriptor, size)
            if result and not changed:
                changed = True
                path.write_bytes(b"changed fixture")
            return result
        with patch.object(capture.os, "read", side_effect=read):
            raw, coverage = self.collect()
        self.assertGreater(coverage["races"], 0)
        self.assertEqual(self.scan(raw)["status"], "inconclusive")

    def test_truncation_and_host_budget_rejection(self):
        (self.files / "file").write_bytes(b"ordinary bytes")
        raw, _ = self.collect()
        for damaged in (raw[:5], raw[:-1], raw + b"extra"):
            self.assertEqual(self.scan(damaged)["status"], "inconclusive")
        self.assertEqual(self.scan(raw, max_bytes=1)["status"], "inconclusive")

    def test_observed_match_stays_failed_after_truncation(self):
        (self.files / "file").write_bytes(KEY)
        raw, _ = self.collect()
        self.assertEqual(self.scan(raw[:-10])["status"], "fail")

    def test_malicious_frame_length_and_metadata_never_echo(self):
        duplicate = b'{"kind":"files","kind":"files"}'
        for raw in (capture.MAGIC + b"D" + struct.pack("!I", 2**32 - 1),
                    capture.MAGIC + b"B" + struct.pack("!I", 6) + b"SECRET",
                    capture.MAGIC + b"B" + struct.pack("!I", len(duplicate)) + duplicate,
                    capture.MAGIC + b"X" + struct.pack("!I", 0)):
            result = self.scan(raw)
            self.assertEqual(result["status"], "inconclusive")
            self.assertNotIn("SECRET", json.dumps(result))

    def test_mount_scope_classification(self):
        for path in ("/proc", "/proc/123/environ", "/sys/kernel", "/dev/zero"):
            self.assertTrue(capture._virtual(path))
        for path in ("/dev/shm", "/dev/shm/file", "/run", "/tmp/proc"):
            self.assertFalse(capture._virtual(path))

    def test_fragmented_transport_reads_supported(self):
        (self.files / "file").write_bytes(KEY)
        raw, _ = self.collect()
        class Fragmented(io.BytesIO):
            def read(self, length=-1):
                return super().read(min(length, 3))
        self.assertEqual(capture.scan(Fragmented(raw), key=KEY)["status"], "fail")

    def test_fragmented_transport_writes_supported(self):
        (self.files / "file").write_bytes(KEY)
        class Fragmented(io.BytesIO):
            def write(self, data):
                return super().write(data[:3])
        stream = Fragmented()
        capture.write(stream, roots=[self.files])
        self.assertEqual(self.scan(stream.getvalue())["status"], "fail")


if __name__ == "__main__":
    unittest.main()
