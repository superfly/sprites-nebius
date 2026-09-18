"""Exercise the sourced shell interface with a fake local configuration child."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import nebius_configure as config


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'reviewed checkout'
        self.home = Path(self.temp.name) / 'agent home'
        self.home.mkdir()
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / '.venv/bin').mkdir(parents=True)
        self.helper = self.root / 'scripts/use-nebius'
        self.helper.write_bytes((Path(__file__).resolve().parents[1] / 'scripts/use-nebius').read_bytes())
        executable = self.root / '.venv/bin/python'
        executable.write_text(f'''#!{sys.executable}
import argparse, json, os, pathlib, sys
parser = argparse.ArgumentParser(allow_abbrev=False)
for option in ('--activate', '--off', '--dry-run', '--approve-service-change'):
    parser.add_argument(option, action='store_true')
for option in ('--model', '--agents', '--connector'):
    parser.add_argument(option)
parser.parse_args(sys.argv[2:])
home = pathlib.Path(os.environ['HOME'])
(home / 'child.json').write_text(json.dumps(sys.argv[1:]))
if (home / 'fail').exists():
    sys.exit(1)
if '--dry-run' not in sys.argv:
    state = home / {config.STATE!r}
    state.mkdir(parents=True, exist_ok=True)
    (state / 'env.sh').write_text({config.activation_shell()!r})
    (state / 'off.sh').write_text({config.deactivation_shell()!r})
    if (home / 'replace-helper').exists():
        for name in ('env.sh', 'off.sh'):
            (state / name).write_text('printf executed > "$HOME/helper-executed"\\n')
print('{{"status":"configured"}}')
''')
        executable.chmod(0o700)
        self.shells = [shutil.which(shell) for shell in ('bash', 'zsh') if shutil.which(shell)]

    def run_shell(self, body, *, shell=None, extra=None):
        return subprocess.run([shell or self.shells[0], '-c', body, 'activation-test', str(self.helper)],
                              env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin', **(extra or {})},
                              cwd=self.root, capture_output=True, text=True, timeout=10)

    def test_one_command_on_off_in_bash_and_zsh(self):
        body = '''
source "$1" on --agents codex --model 'Qwen/example' || exit 11
test "$SPRITES_NEBIUS_PLACEHOLDER" = sprites-nebius-placeholder-not-a-secret || exit 12
sh -c 'test "$SPRITES_NEBIUS_PLACEHOLDER" = sprites-nebius-placeholder-not-a-secret' || exit 13
source "$1" off || exit 14
test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x || exit 15
test "${SPRITES_NEBIUS_OWNS_PLACEHOLDER+x}" != x || exit 16
'''
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = self.run_shell(body, shell=shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--off', json.loads((self.home / 'child.json').read_text()))

    def test_preserves_caller_directory_arguments_options_and_traps(self):
        body = '''
before_pwd=$PWD
before_argument=$1
before_path=$PATH
before_options=$(set +o)
trap ':' USR1
before_traps=$(trap)
source "$1" on --agents codex --model 'Qwen/example' || exit 11
test "$PWD" = "$before_pwd" || exit 12
test "$PATH" = "$before_path" || exit 13
test "$(set +o)" = "$before_options" || exit 14
test "$(trap)" = "$before_traps" || exit 15
test "$#" = 1 || exit 16
test "$1" = "$before_argument" || exit 17
! command -v __sprites_nebius_use >/dev/null || exit 18
'''
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = self.run_shell(body, shell=shell)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_preexisting_placeholder_is_not_unset(self):
        for shell in self.shells:
            result = self.run_shell('source "$1" on --model model && source "$1" off && '
                                    'test "$SPRITES_NEBIUS_PLACEHOLDER" = sprites-nebius-placeholder-not-a-secret',
                                    shell=shell, extra={config.ENV_KEY: 'sprites-nebius-placeholder-not-a-secret'})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_placeholder_is_preserved_on_off(self):
        for shell in self.shells:
            result = self.run_shell('source "$1" on --model model || exit 11; '
                                    'SPRITES_NEBIUS_PLACEHOLDER=user-value; source "$1" off || exit 12; '
                                    'test "$SPRITES_NEBIUS_PLACEHOLDER" = user-value', shell=shell)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_and_child_failure_never_activate(self):
        for shell in self.shells:
            for failed in (False, True):
                marker = self.home / 'fail'
                if failed:
                    marker.touch()
                elif marker.exists():
                    marker.unlink()
                body = ('if source "$1" on --model model; then exit 11; fi; ' if failed else
                        'source "$1" on --dry-run || exit 11; ')
                result = self.run_shell(body + 'test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x', shell=shell)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_conflicting_and_readonly_variables_fail_before_child(self):
        for shell in self.shells:
            for preparation in ('SPRITES_NEBIUS_PLACEHOLDER=user-value',
                                'readonly SPRITES_NEBIUS_PLACEHOLDER=sprites-nebius-placeholder-not-a-secret',
                                'readonly SPRITES_NEBIUS_OWNS_PLACEHOLDER=1',
                                'SPRITES_NEBIUS_OWNS_PLACEHOLDER=user-value'):
                child = self.home / 'child.json'
                if child.exists():
                    child.unlink()
                result = self.run_shell(preparation + '; if source "$1" on --model model; then exit 11; fi', shell=shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(child.exists(), (shell, preparation))

    def test_direct_execution_is_rejected(self):
        for shell in self.shells:
            result = subprocess.run([shell, str(self.helper), 'on', '--model', 'model'],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Source this helper', result.stderr)

    def test_wrapper_reserved_arguments_do_not_activate(self):
        for argument in ('--off', '--help', '--activate'):
            result = self.run_shell('if source "$1" on ' + argument + '; then exit 11; fi; '
                                    'test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_function_is_not_overwritten(self):
        for shell in self.shells:
            result = self.run_shell('__sprites_nebius_use() { printf preserved; }; '
                                    'if source "$1" on --model model; then exit 11; fi; '
                                    'test "$(__sprites_nebius_use)" = preserved', shell=shell)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_off_keeps_shell_activation(self):
        for shell in self.shells:
            (self.home / 'fail').touch()
            result = self.run_shell('if source "$1" off; then exit 11; fi; '
                                    'test "$SPRITES_NEBIUS_PLACEHOLDER" = sprites-nebius-placeholder-not-a-secret && '
                                    'test "$SPRITES_NEBIUS_OWNS_PLACEHOLDER" = 1', shell=shell,
                                    extra={config.ENV_KEY: 'sprites-nebius-placeholder-not-a-secret',
                                           'SPRITES_NEBIUS_OWNS_PLACEHOLDER': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_abbreviated_dry_run_is_rejected_without_shell_mutation(self):
        for shell in self.shells:
            for mode in ('on', 'off'):
                result = self.run_shell('if source "$1" ' + mode + ' --dry-r; then exit 11; fi; '
                                        'test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x', shell=shell)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_replaced_helpers_are_never_executed(self):
        (self.home / 'replace-helper').touch()
        for shell in self.shells:
            result = self.run_shell('source "$1" on --model model && source "$1" off && '
                                    'test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x', shell=shell)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.home / 'helper-executed').exists())


if __name__ == '__main__':
    unittest.main()
