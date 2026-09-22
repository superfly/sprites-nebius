"""Offline onboarding tests: fake discovery/installers/agents, real config edits."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import nebius_configure as config
import nebius_setup as setup
from support import BASE, MODEL, DiscoveryClient as FakeClient, HomeTestCase


def options(**values):
    return argparse.Namespace(**dict(agent="pi", connector=None, model=None, install=False,
                                     apply=False, dry_run=False, launch=False, off=False) | values)


class SetupTests(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.bin = self.home / "bin"
        self.bin.mkdir()
        for agent in config.AGENTS:
            executable = self.bin / agent
            executable.write_text("#!/bin/sh\nexit 99\n")  # Never run by setup-only.
            executable.chmod(0o700)
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.home), "PATH": str(self.bin)}, clear=True))
        self.enterContext(patch("sys.stdin.isatty", return_value=False))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.runtime = self.enterContext(patch.object(setup, "prepare_runtime", return_value=True))
        self.client = FakeClient()

    def run_setup(self, **kwargs):
        return setup.setup(options(**kwargs), client=self.client, inside_sprite=True)

    def state(self):
        return json.loads((self.home / config.STATE / "active.json").read_text())

    def test_all_entry_points_configure_only_selected_agent_without_launch(self):
        with patch.object(config, "activate_service", return_value={"ready": True}) as service, \
                patch.object(setup.os, "execve") as launch:
            for agent in config.AGENTS:
                with self.subTest(agent=agent):
                    self.run_setup(agent=agent, model=MODEL, apply=True)
                    self.assertEqual(self.state()["agents"], [agent])
                    self.run_setup(agent=agent, off=True, apply=True)
            service.assert_called_once()
            launch.assert_not_called()
        self.assertTrue(all(kwargs.get("method", "GET") == "GET" for _, kwargs in self.client.calls))

    def test_setup_rerun_uses_saved_selection_and_restores_original(self):
        settings = self.home / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        original = '{"defaultModel":"old", "unrelated":true}\n'
        settings.write_text(original)
        self.run_setup(model=MODEL, apply=True)
        state = self.state()
        self.assertEqual(self.run_setup()["status"], "unchanged")
        self.assertEqual(self.state(), state)
        self.client.calls.clear()
        self.run_setup(off=True, apply=True)
        self.assertEqual(settings.read_text(), original)
        self.assertEqual(self.client.calls, [])
        self.assertFalse((self.home / config.STATE / "active.json").exists())

    def test_model_never_auto_selected_even_when_only_one(self):
        with self.assertRaisesRegex(config.ConfigureError, "Choose --model"):
            self.run_setup(apply=True)
        self.assertFalse((self.home / config.STATE).exists())

    def test_interactive_selection_and_confirmation(self):
        self.client.gateways = (BASE, BASE + "-other")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["2", "1", "yes"]):
            self.run_setup()
        self.assertEqual(self.state()["gateway"], BASE + "-other")

    def test_ambiguous_connector_fails_without_interactive_selection(self):
        self.client.gateways = (BASE, BASE + "-other")
        with self.assertRaisesRegex(config.ConfigureError, "Choose --connector"):
            self.run_setup(model=MODEL, apply=True)

    def test_dry_run_and_declined_apply_leave_no_configuration(self):
        self.run_setup(model=MODEL, dry_run=True, install=True, apply=True)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
            with self.assertRaisesRegex(config.ConfigureError, "Cancelled"):
                self.run_setup(model=MODEL)
        self.assertFalse((self.home / config.STATE).exists())
        self.assertFalse((self.home / ".pi").exists())

    def test_noninteractive_requires_consent_before_config_or_service_changes(self):
        with patch.object(config, "activate_service") as service:
            for agent in ("pi", "claude"):
                with self.subTest(agent=agent), self.assertRaisesRegex(config.ConfigureError, "approval flag"):
                    self.run_setup(agent=agent, model=MODEL)
            service.assert_not_called()
        self.assertFalse((self.home / config.STATE).exists())
        self.assertFalse((self.home / ".pi").exists())
        self.assertFalse((self.home / ".claude").exists())

    def test_conflicting_environment_checked_before_bootstrap(self):
        for variable in ("NEBIUS_API_KEY", config.ENV_KEY, "PI_CODING_AGENT_DIR"):
            with self.subTest(variable=variable), patch.dict(os.environ, {variable: "private-value"}):
                with self.assertRaises(config.ConfigureError):
                    self.run_setup(model=MODEL, apply=True)
        self.runtime.assert_not_called()
        self.assertEqual(self.client.calls, [])

    def test_another_selection_not_silently_replaced(self):
        self.run_setup(model=MODEL, apply=True)
        self.runtime.reset_mock()
        with self.assertRaisesRegex(config.ConfigureError, "Another agent selection"):
            self.run_setup(agent="codex", model=MODEL, apply=True)
        self.runtime.assert_not_called()
        self.assertEqual(self.state()["agents"], ["pi"])

    def test_changed_configuration_blocks_launch_and_restore(self):
        self.run_setup(model=MODEL, apply=True)
        settings = self.home / ".pi/agent/settings.json"
        settings.write_text(settings.read_text().replace(MODEL, "user-change"))
        with patch.object(setup.os, "execve") as launch:
            for mode in ({"launch": True}, {"off": True}):
                with self.assertRaises(config.ConfigureError):
                    self.run_setup(apply=True, **mode)
            launch.assert_not_called()
        self.assertIn("user-change", settings.read_text())

    def test_launch_uses_child_environment_and_keeps_working_directory(self):
        self.run_setup(model=MODEL, apply=True)
        before = Path.cwd()
        with patch.object(setup.os, "execve") as launch:
            self.run_setup(launch=True)
        executable, arguments, env = launch.call_args.args
        self.assertEqual(executable, str(self.bin / "pi"))
        self.assertEqual(arguments, [executable])
        self.assertEqual(env[config.ENV_KEY], setup.PLACEHOLDER)
        self.assertNotIn(config.ENV_KEY, os.environ)
        self.assertEqual(Path.cwd(), before)

    def test_unsafe_provider_models_never_printed_or_selected(self):
        self.client.models = (MODEL, "\x1b[31mbad", "$(touch bad)", "x" * 201)
        with self.assertRaisesRegex(config.ConfigureError, "Choose --model"):
            self.run_setup(apply=True)
        output = self.output.getvalue()
        self.assertIn(MODEL, output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("$(touch", output)

    def test_invalid_cli_combinations_fail_before_setup(self):
        for flags in (("--off", "--launch"), ("--dry-run", "--launch"), ("--off", "--model", MODEL), ("--dry-r",)):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                setup.main(["pi", *flags])
        self.runtime.assert_not_called()

    def test_host_refused_before_any_installs(self):
        with self.assertRaisesRegex(config.ConfigureError, "inside the intended Sprite"):
            setup.setup(options(), inside_sprite=False)
        self.runtime.assert_not_called()

    def test_bootstrap_failure_never_applies_configuration_or_launches(self):
        self.runtime.side_effect = config.ConfigureError("Dependency installation failed")
        with patch.object(setup.os, "execve") as launch:
            with self.assertRaisesRegex(config.ConfigureError, "installation failed"):
                self.run_setup(model=MODEL, apply=True, launch=True)
            launch.assert_not_called()
        self.assertFalse((self.home / config.STATE).exists())
        self.assertEqual(self.client.calls, [])

    def test_unknown_or_removed_saved_model_is_not_replaced(self):
        self.run_setup(model=MODEL, apply=True)
        before = self.state()
        self.client.models = ("different-model",)
        with self.assertRaisesRegex(config.ConfigureError, "not available"):
            self.run_setup(apply=True)
        self.assertEqual(self.state(), before)

    def test_owned_state_symlink_rejected(self):
        directory = self.home / config.STATE
        directory.mkdir(parents=True)
        (directory / "active.json").symlink_to(self.home / "elsewhere")
        with self.assertRaisesRegex(config.ConfigureError, "symlink"):
            self.run_setup(model=MODEL, apply=True)
        self.runtime.assert_not_called()


class BootstrapTests(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.directory / "checkout with spaces"
        self.root.mkdir()
        (self.root / "proxy").mkdir()
        for name in ("requirements-configure.txt", "proxy/requirements.txt"):
            (self.root / name).write_bytes((setup.ROOT / name).read_bytes())
        self.enterContext(patch.object(setup, "ROOT", self.root))
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.home), "PATH": "/bin"}, clear=True))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch("sys.stdin.isatty", return_value=False))
        self.run = self.enterContext(patch.object(setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)))
        self.install = self.enterContext(patch.object(setup, "run_install"))
        self.handoff = self.enterContext(patch.object(setup.os, "execv"))

    def test_missing_dependencies_dry_run_is_read_only(self):
        with patch.object(setup.shutil, "which", return_value=None):
            self.assertFalse(setup.prepare_runtime(options(dry_run=True, install=True), self.home))
        self.install.assert_not_called()
        self.run.assert_not_called()
        self.assertFalse((self.root / ".venv").exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_existing_harness_not_installed_or_upgraded(self):
        (self.root / ".venv").mkdir()
        with patch.object(setup.shutil, "which", return_value="/usr/bin/pi"):
            self.assertTrue(setup.prepare_runtime(options(), self.home))
        self.install.assert_not_called()
        self.assertTrue(os.environ["PATH"].startswith("/bin:"))
        self.handoff.assert_called_once()

    def test_missing_python_dependencies_require_consent(self):
        with patch.object(setup.shutil, "which", return_value="/usr/bin/pi"):
            with self.assertRaisesRegex(config.ConfigureError, "approval flag"):
                setup.prepare_runtime(options(), self.home)
        self.install.assert_not_called()

    def test_declined_dependency_install_leaves_checkout_untouched(self):
        with patch.object(setup.shutil, "which", return_value="/bin/pi"), \
                patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
            with self.assertRaisesRegex(config.ConfigureError, "Cancelled"):
                setup.prepare_runtime(options(), self.home)
        self.install.assert_not_called()
        self.assertFalse((self.root / ".venv").exists())

    def test_broken_existing_agent_not_replaced(self):
        self.run.return_value = subprocess.CompletedProcess([], 1)
        with patch.object(setup.shutil, "which", return_value="/bin/pi"):
            with self.assertRaisesRegex(config.ConfigureError, "repair it manually"):
                setup.prepare_runtime(options(install=True), self.home)
        self.install.assert_not_called()

    def test_missing_node_fails_before_any_install(self):
        with patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaisesRegex(config.ConfigureError, "Node.js"):
                setup.prepare_runtime(options(install=True), self.home)
        self.install.assert_not_called()

    def test_old_node_not_upgraded(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, stdout="v20.0.0\n")
        with patch.object(setup.shutil, "which", side_effect=[None, "/bin/node", "/bin/npm"]):
            with self.assertRaisesRegex(config.ConfigureError, "runtime left unchanged"):
                setup.prepare_runtime(options(install=True), self.home)
        self.install.assert_not_called()

    def test_selected_pinned_package_and_only_reviewed_installer(self):
        for agent in config.AGENTS:
            with self.subTest(agent=agent):
                self.install.reset_mock()
                expected = setup.PACKAGES[agent].rsplit("@", 1)[1]
                self.run.side_effect = [subprocess.CompletedProcess([], 0, stdout="v22.19.0\n"),
                                        subprocess.CompletedProcess([], 0, stdout=agent + " " + expected)]
                with patch.object(setup.shutil, "which", side_effect=[None, "/bin/node", "/bin/npm", "/bin/agent"]):
                    setup.prepare_runtime(options(agent=agent, install=True), self.home)
                commands = [call.args[0] for call in self.install.call_args_list]
                npm = next(command for command in commands if command[0] == "/bin/npm")
                self.assertIn("--ignore-scripts", npm)
                self.assertEqual(npm[-1], setup.PACKAGES[agent])
                scripts = [command for command in commands if command[0] == "/bin/node"]
                self.assertEqual(len(scripts), int(agent in setup.BINARY_INSTALLERS))
                if scripts:
                    self.assertTrue(scripts[0][1].endswith(setup.BINARY_INSTALLERS[agent]))

    def test_off_never_reinstalls_missing_agent(self):
        (self.root / ".venv").mkdir()
        with patch.object(setup.shutil, "which", return_value=None):
            setup.prepare_runtime(options(off=True), self.home)
        self.install.assert_not_called()

    def test_failed_installer_does_not_handoff_to_configurator(self):
        self.install.side_effect = config.ConfigureError("Dependency installation failed")
        with patch.object(setup.shutil, "which", return_value="/bin/pi"):
            with self.assertRaisesRegex(config.ConfigureError, "installation failed"):
                setup.prepare_runtime(options(install=True), self.home)
        self.handoff.assert_not_called()

    def test_symlinked_venv_rejected(self):
        (self.root / ".venv").symlink_to(self.home)
        with self.assertRaisesRegex(config.ConfigureError, "symlink"):
            setup.prepare_runtime(options(install=True), self.home)
        self.install.assert_not_called()

    def test_real_shell_entry_points_dispatch_correct_agent_from_other_directory(self):
        source = Path(__file__).resolve().parents[1]
        # Test the thin entry points without running the bootstrap or changing a Sprite.
        (self.root / "scripts").mkdir()
        dispatcher = self.root / "scripts/setup-nebius"
        dispatcher.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        dispatcher.chmod(0o700)
        for agent in config.AGENTS:
            wrapper = self.root / ("setup-nebius-" + agent)
            wrapper.write_bytes((source / wrapper.name).read_bytes())
            wrapper.chmod(0o700)
            # Patching subprocess.run above is deliberately bypassed for this shell-only test.
            process = subprocess.Popen([str(wrapper), "--model", "Qwen/test model"], cwd=self.home,
                                       env={**os.environ, "PATH": "/usr/bin:/bin"},
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.splitlines(), [agent, "--model", "Qwen/test model"])


class HelperTests(unittest.TestCase):
    def test_package_pins_match_installation_guide(self):
        guide = (setup.ROOT / "docs/installation.md").read_text()
        for package in setup.PACKAGES.values():
            self.assertIn("`" + package + "`", guide)

    def test_installer_output_never_echoed_and_failure_not_retried(self):
        with patch.object(setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as run:
            with self.assertRaisesRegex(config.ConfigureError, "Dependency installation failed"):
                setup.run_install(["npm", "install"])
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_oversized_menu_input_fails_safely(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1" * 5000), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.ConfigureError, "Invalid selection"):
                setup.choose("model", [MODEL])


if __name__ == "__main__":
    unittest.main()
