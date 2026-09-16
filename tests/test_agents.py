"""No native agents are executed: subprocesses and Sprite identity are mocked."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nebius_agents as agents
from nebius_configure import document, fields, STATE

BASE = "https://api.sprites.dev/v1/gateway/custom_api/offline-agent-test"
MODEL = "provider/model"


def args(names="pi", approve=False):
    return argparse.Namespace(agents=names, approve_agent_runs=approve, timeout=30)


def lines(rows):
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


def codex_answer(text="OK"):
    return lines([{"type": "thread.started"}, {"type": "turn.started"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
                  {"type": "turn.completed"}])


def opencode_answer(text="OK"):
    return lines([{"type": "step_start", "part": {}}, {"type": "text", "part": {"text": text}},
                  {"type": "step_finish", "part": {"reason": "stop"}}])


class OutputTests(unittest.TestCase):
    def test_exact_ok_not_substring(self):
        for name, good, bad in [("codex", codex_answer(), codex_answer("OK done")),
                                ("opencode", opencode_answer(), opencode_answer("NOT OK")),
                                ("pi", b"OK\n", b"NOT OK\n")]:
            self.assertTrue(agents.exact_ok(name, good))
            self.assertFalse(agents.exact_ok(name, bad))

    def test_output_schema_fail_closed(self):
        for name, raw in [("codex", b"OK\n"), ("opencode", b"OK\n"),
                          ("codex", lines([{"type": "item.completed", "item": {"type": "command_execution"}}])),
                          ("opencode", lines([{"type": "tool_use", "part": {"text": "OK"}}])),
                          ("codex", b"\xff"), ("opencode", lines([{"type": "error", "error": "secret"}]))]:
            with self.subTest(name=name), self.assertRaises(agents.AgentError):
                agents.exact_ok(name, raw)

    def test_no_missing_terminal_success(self):
        self.assertFalse(agents.exact_ok("codex", lines([{"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}])))
        self.assertFalse(agents.exact_ok("opencode", lines([{"type": "text", "part": {"text": "OK"}}])))

    def test_native_commands_never_bypass_permissions(self):
        for name in ("codex", "opencode", "pi"):
            argv = agents.command(name, "/bin/" + name)
            self.assertFalse(any("dangerously" in part for part in argv))
            self.assertIn(agents.PROMPT, argv)
        self.assertIn("--sandbox", agents.command("codex", "/bin/codex"))
        self.assertIn("--no-tools", agents.command("pi", "/bin/pi"))
        with self.assertRaises(agents.AgentError):
            agents.command("claude", "/bin/claude")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name).resolve()
        self.calls = []

    def configure(self, selected):
        folder = self.home / STATE
        folder.mkdir(parents=True)
        (folder / "active.json").write_text(json.dumps({"version": 1, "agents": selected,
                                                       "gateway": BASE, "model": MODEL}))
        for relative, (kind, changes) in fields(selected, BASE, MODEL).items():
            doc = document(None, kind)
            for path, value in changes:
                doc.set(path, value)
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(doc.render())

    def fake_run(self, argv, *, cwd, env, timeout):
        self.calls.append((argv, Path(cwd), env))
        name = Path(argv[0]).name
        if argv[1:] == ["--version"]:
            return 0, (agents.PINS[name] + "\n").encode()
        if name == "codex":
            return 0, codex_answer()
        if name == "opencode":
            return 0, opencode_answer()
        return 0, b"OK\n"

    def execute(self, options, **kwargs):
        return agents.execute(options, home=self.home, environ={"PATH": "/usr/bin:/bin:relative:",
            "NEBIUS_API_KEY": "secret", "OPENAI_API_KEY": "secret", "NODE_OPTIONS": "malicious"},
            run=kwargs.pop("run", self.fake_run), which=lambda name: "/installed/bin/" + name,
            inside_sprite=kwargs.pop("inside_sprite", True), revision=lambda: {"git_revision": "a" * 40, "working_tree_dirty": False}, **kwargs)

    def test_dry_plan_no_subprocess_config_or_sprite_required(self):
        report = self.execute(args("codex,opencode,pi,claude"), inside_sprite=False)
        self.assertEqual(report["status"], "dry_plan")
        self.assertEqual(self.calls, [])
        self.assertFalse(report["full_spec_verified"])
        self.assertEqual(report["results"][-1]["status"], "blocked")

    def test_approved_outside_sprite_refused(self):
        with self.assertRaises(agents.AgentError):
            self.execute(args(approve=True), inside_sprite=False)
        self.assertEqual(self.calls, [])

    def test_missing_configuration_refused_without_launch(self):
        with self.assertRaises(agents.AgentError):
            self.execute(args(approve=True))
        self.assertEqual(self.calls, [])

    def test_reject_changed_route_before_launch(self):
        self.configure(["pi"])
        config = self.home / ".pi/agent/models.json"
        config.write_text(config.read_text().replace(BASE, "https://api.openai.com/v1"))
        with self.assertRaises(agents.AgentError):
            self.execute(args(approve=True))
        self.assertEqual(self.calls, [])

    def test_pi_run_is_sanitized_temporary_and_metadata_only(self):
        self.configure(["pi"])
        before = (self.home / ".pi/agent/models.json").read_bytes()
        report = self.execute(args(approve=True))
        self.assertEqual(report["results"][0]["status"], "pass")
        self.assertEqual(len(self.calls), 2)
        env = self.calls[-1][2]
        self.assertNotIn("NEBIUS_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertEqual(env["PATH"], "/installed/bin:/usr/local/bin:/usr/bin:/bin")
        self.assertNotEqual(env["HOME"], str(self.home))
        self.assertFalse(self.calls[-1][1].exists())
        self.assertEqual((self.home / ".pi/agent/models.json").read_bytes(), before)
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("output", report["results"][0])
        self.assertIn("started_at", report["results"][0])
        self.assertEqual(report["git_revision"], "a" * 40)
        self.assertFalse(report["full_spec_verified"])

    def test_version_mismatch_no_paid_command(self):
        self.configure(["pi"])
        def run(argv, **kwargs):
            self.calls.append(argv)
            return 0, b"0.0.1\n"
        report = self.execute(args(approve=True), run=run)
        self.assertEqual(report["results"][0]["status"], "inconclusive")
        self.assertEqual(len(self.calls), 1)

    def test_agent_error_not_retried_or_output_leaked(self):
        self.configure(["pi", "opencode"])
        def run(argv, **kwargs):
            if argv[1:] == ["--version"]:
                return self.fake_run(argv, **kwargs)
            self.calls.append(argv)
            return 1, b"SECRET_OUTPUT"
        report = self.execute(args("pi,opencode", True), run=run)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(report["results"][1]["status"], "not_run")
        self.assertNotIn("SECRET_OUTPUT", json.dumps(report))

    def test_v8_approval_still_does_not_launch_claude(self):
        report = self.execute(args("claude", True))
        self.assertEqual(report["results"][0]["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_fresh_config_omits_unowned_plugins_and_credentials(self):
        self.configure(["opencode"])
        path = self.home / ".config/opencode/opencode.json"
        content = json.loads(path.read_text())
        content["plugin"] = ["untrusted-plugin"]
        content["provider"]["other"] = {"options": {"apiKey": "private-key"}}
        path.write_text(json.dumps(content))
        def run(argv, **kwargs):
            fresh = Path(kwargs["env"]["HOME"]) / ".config/opencode/opencode.json"
            raw = fresh.read_text()
            config = json.loads(raw)
            self.assertNotIn("private-key", raw)
            self.assertNotIn("untrusted-plugin", raw)
            self.assertEqual(config["permission"], {"*": "deny"})
            return self.fake_run(argv, **kwargs)
        report = self.execute(args("opencode", True), run=run)
        self.assertEqual(report["results"][0]["status"], "pass")

    def test_bad_selection_refused(self):
        for value in ("pi,pi", "all", "", "pi,unknown"):
            with self.assertRaises(agents.AgentError):
                self.execute(args(value))

    def test_symlink_config_refused(self):
        self.configure(["pi"])
        path = self.home / ".pi/agent/models.json"
        target = self.home / "other.json"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(agents.AgentError):
            self.execute(args(approve=True))


if __name__ == "__main__":
    unittest.main()
