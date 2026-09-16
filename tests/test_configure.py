import argparse
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import nebius_configure as config
import nebius_verify as verify

BASE = "https://api.sprites.dev/v1/gateway/custom_api/test-connector"
MODEL = "Qwen/test-model"


class Response(io.BytesIO):
    status = 200


class FakeClient:
    def __init__(self, gateways=(BASE,), models=(MODEL,)):
        self.calls = []
        self.gateways = gateways
        self.models = models

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == verify.DISCOVERY_URL:
            value = {"connections": [{"provider": "custom_api", "base_api_url": verify.NEBIUS_URL,
                                       "gateway_base_url": item} for item in self.gateways]}
        else:
            value = {"data": [{"id": item} for item in self.models]}
        return Response(json.dumps(value).encode())


def options(**values):
    defaults = dict(model=MODEL, agents=None, connector=None, dry_run=False, off=False)
    return argparse.Namespace(**{**defaults, **values})


class DocumentTests(unittest.TestCase):
    def test_reference_templates_match_configurator(self):
        root = Path(__file__).resolve().parents[1]
        mappings = {'.codex/config.toml': 'codex/config.toml',
                    '.config/opencode/opencode.json': 'opencode/opencode.json',
                    '.pi/agent/models.json': 'pi/models.json',
                    '.pi/agent/settings.json': 'pi/settings.json',
                    '.claude/settings.json': 'claude-code/settings.json'}
        for relative, template in mappings.items():
            kind, changes = config.fields(config.AGENTS, BASE, MODEL)[relative]
            text = (root / 'templates' / template).read_text().replace('GATEWAY_BASE_URL', BASE).replace('MODEL_ID', MODEL)
            doc = config.document(text.encode(), kind)
            for path, value in changes:
                with self.subTest(template=template, path=path):
                    self.assertEqual(config.get_value(doc.data, path), value)

    def test_json_preserves_unrelated_comments_and_strings(self):
        text = '{\n// intro\n"keep": "https://x/*text*/", // keep\n"nested": {/* note */ "value": 1,},\n}\n'
        doc = config.JsonDocument(text)
        doc.set(("nested", "value"), 2)
        self.assertIn('// keep', doc.render())
        self.assertIn('/* note */', doc.render())
        self.assertIn('"https://x/*text*/"', doc.render())
        doc.set(("new", "child"), "new")
        self.assertEqual(doc.data["new"]["child"], "new")

    def test_json_remove_first_middle_last_with_comments(self):
        for key in ("a", "b", "c"):
            doc = config.JsonDocument('{"a":1,/*one*/"b":2,/*two*/"c":3}')
            doc.set((key,))
            self.assertNotIn(key, doc.data)
            self.assertIn('/*one*/', doc.render())
            self.assertIn('/*two*/', doc.render())

    def test_malformed_json_is_rejected(self):
        for text in ('{"a":1,"a":2}', '{"a":1} trailing', '{"a":NaN}',
                     '{"a":1 /* no end }', '[1,2]', '{a: 1}', '{"a": 1e}', '{'):
            with self.subTest(text=text), self.assertRaises(config.ConfigureError):
                config.JsonDocument(text)

    def test_json_parent_type_conflict(self):
        doc = config.JsonDocument('{"a": 2}')
        with self.assertRaises(config.ConfigureError):
            doc.set(("a", "b"), 3)

    def test_toml_preserves_comments(self):
        doc = config.TomlDocument('# intro\nmodel="old" # choice\n[unrelated]\nx=1 # keep\n')
        doc.set(("model",), MODEL)
        doc.set(("model_providers", "nebius", "wire_api"), "responses")
        self.assertIn('# choice', doc.render())
        self.assertIn('x=1 # keep', doc.render())


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()

    def run_config(self, **kwargs):
        client = kwargs.pop("client", FakeClient())
        overrides = kwargs.pop("overrides", {})
        return config.configure(options(**kwargs), home=self.home, environ={}, client=client,
                                which=lambda _: "/bin/installed-agent", inside_sprite=True, **overrides)

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_default_all_schema_and_no_spend(self):
        client = FakeClient()
        result = self.run_config(client=client)
        self.assertEqual(result["agents"], config.AGENTS)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(kwargs.get("method", "GET") == "GET" for _, kwargs in client.calls))
        codex = config.TomlDocument((self.home / '.codex/config.toml').read_text()).data
        self.assertEqual(codex['model_providers']['nebius']['wire_api'], 'responses')
        self.assertEqual(codex['model_providers']['nebius']['request_max_retries'], 0)
        pi = json.loads((self.home / '.pi/agent/models.json').read_text())
        self.assertEqual(pi['providers']['nebius']['apiKey'], '$' + config.ENV_KEY)
        claude = json.loads((self.home / '.claude/settings.json').read_text())
        self.assertEqual(claude['env']['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8083')
        self.assertFalse(result['full_spec_verified'])
        self.assertIn('not_started', result['proxy_service'])

    def test_dry_run_creates_nothing(self):
        result = self.run_config(dry_run=True)
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_agents_before_any_config_write(self):
        with self.assertRaisesRegex(config.ConfigureError, 'Install'):
            config.configure(options(), home=self.home, environ={}, client=FakeClient(),
                             which=lambda _: None, inside_sprite=True)
        self.assertFalse((self.home / '.codex').exists())

    def test_requires_sprite(self):
        with self.assertRaisesRegex(config.ConfigureError, 'inside'):
            config.configure(options(), home=self.home, environ={}, inside_sprite=False)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_multiple_connectors_require_explicit_id(self):
        with self.assertRaisesRegex(config.ConfigureError, 'exactly one'):
            self.run_config(client=FakeClient((BASE, BASE + '-other')))
        result = self.run_config(connector='test-connector', client=FakeClient((BASE, BASE + '-other')))
        self.assertEqual(result['status'], 'configured')

    def test_missing_model_lists_without_configuration(self):
        result = self.run_config(model=None)
        self.assertEqual(result['models'], [MODEL])
        self.assertEqual(result['certified_combinations'], [])
        self.assertFalse((self.home / '.codex').exists())

    def test_unlisted_and_unsafe_model_rejected(self):
        for model in ('missing', '$(touch surprise)'):
            with self.assertRaises(config.ConfigureError):
                self.run_config(model=model)
        self.assertFalse((self.home / '.codex').exists())

    def test_malformed_last_file_prevents_earlier_writes(self):
        self.write('.claude/settings.json', '{bad')
        with self.assertRaises(config.ConfigureError):
            self.run_config()
        self.assertFalse((self.home / '.codex').exists())

    def test_real_credentials_not_overwritten(self):
        path = self.write('.claude/settings.json', '{"env":{"ANTHROPIC_AUTH_TOKEN":"user-owned-credential"}}')
        before = path.read_bytes()
        with self.assertRaisesRegex(config.ConfigureError, 'credentials'):
            self.run_config()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / '.codex').exists())

    def test_environment_credentials_and_overrides_are_rejected(self):
        for env in ({'NEBIUS_API_KEY':'user-owned-credential'}, {'ANTHROPIC_AUTH_TOKEN':'user-owned-credential'},
                    {config.ENV_KEY: 'user-owned-value'}, {'CODEX_HOME': '/elsewhere'},
                    {'ANTHROPIC_BASE_URL': 'https://other.example'}):
            with self.subTest(env=list(env)), self.assertRaises(config.ConfigureError):
                config.configure(options(), home=self.home, environ=env, inside_sprite=True,
                                 which=lambda _: '/bin/agent', client=FakeClient())

    def test_symlink_config_or_parent_rejected(self):
        self.write('outside', '{}')
        (self.home / '.claude').symlink_to(self.home)
        with self.assertRaisesRegex(config.ConfigureError, 'symlink'):
            self.run_config()
        self.assertFalse((self.home / '.codex').exists())

    def test_codex_existing_auth_configuration_is_rejected(self):
        for field, value in [('env_key','"REAL_PROVIDER_KEY"'), ('auth','{command="key-helper"}'),
                             ('query_params','{key="real-value"}')]:
            self.write('.codex/config.toml', '[model_providers.nebius]\n' + field + '=' + value + '\n')
            with self.subTest(field=field), self.assertRaisesRegex(config.ConfigureError, 'credentials'):
                self.run_config(agents='codex')

    def test_state_file_symlinks_are_rejected(self):
        for name in ('active.json', 'pending.json', 'lock'):
            directory = self.home / config.STATE
            directory.mkdir(parents=True, exist_ok=True)
            target = self.write('outside-' + name, '{}')
            link = directory / name
            if link.exists():
                link.unlink()
            link.symlink_to(target)
            with self.subTest(name=name), self.assertRaisesRegex(config.ConfigureError, 'symlink'):
                self.run_config(agents='codex')
            link.unlink()

    def test_private_backups_and_exact_round_trip(self):
        original = '# keep\nmodel = "old" # mine\n[other]\na = 12\n'
        path = self.write('.codex/config.toml', original)
        self.run_config(agents='codex')
        backup = self.home / config.STATE / 'backups/.codex_config.toml.original'
        self.assertEqual(backup.read_text(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        result = self.run_config(off=True)
        self.assertEqual(result['status'], 'off')
        self.assertEqual(path.read_text(), original)
        self.assertTrue((self.home / config.STATE / 'off.sh').exists())

    def test_idempotent_preserves_original_backup(self):
        self.write('.codex/config.toml', 'model="old"\n')
        self.run_config(agents='codex')
        state = (self.home / config.STATE / 'active.json').read_bytes()
        self.assertEqual(self.run_config(agents='codex')['status'], 'unchanged')
        self.assertEqual((self.home / config.STATE / 'active.json').read_bytes(), state)

    def test_enable_disable_enable_and_dry_run(self):
        self.run_config(agents='codex')
        self.run_config(off=True)
        self.assertEqual(self.run_config(agents='codex', dry_run=True)['status'], 'dry_run')
        self.assertEqual(self.run_config(agents='codex')['status'], 'configured')

    def test_restore_preserves_new_unrelated_jsonc_changes(self):
        path = self.write('.config/opencode/opencode.jsonc', '{// intro\n"theme":"old"\n}\n')
        self.run_config(agents='opencode')
        path.write_text(path.read_text().replace('"old"', '"new"') + '// added later\n')
        self.run_config(off=True)
        self.assertEqual(config.JsonDocument(path.read_text()).data, {'theme':'new'})
        self.assertIn('// intro', path.read_text())
        self.assertIn('// added later', path.read_text())

    def test_restore_preserves_new_unrelated_toml_changes(self):
        path = self.write('.codex/config.toml', 'model="old" # mine\n[other]\nvalue=1 # keep\n')
        self.run_config(agents='codex')
        path.write_text(path.read_text().replace('value=1', 'value=2'))
        self.run_config(off=True)
        self.assertIn('value=2 # keep', path.read_text())
        self.assertEqual(config.TomlDocument(path.read_text()).data['model'], 'old')

    def test_restore_owned_conflict_writes_nothing(self):
        self.run_config()
        codex = self.home / '.codex/config.toml'
        before = codex.read_bytes()
        claude = self.home / '.claude/settings.json'
        claude.write_text(claude.read_text().replace('8083', '9000'))
        with self.assertRaisesRegex(config.ConfigureError, 'conflict'):
            self.run_config(off=True)
        self.assertEqual(codex.read_bytes(), before)
        self.assertTrue((self.home / config.STATE / 'active.json').exists())

    def test_off_stops_only_owned_service_after_conflict_preflight(self):
        self.run_config(agents='codex')
        with patch('proxy.service.stop_owned') as stop:
            self.run_config(off=True, dry_run=True)
            stop.assert_not_called()
            self.run_config(off=True)
        stop.assert_called_once_with(self.home, locked=True)

    def test_off_conflict_does_not_stop_service(self):
        self.run_config(agents='codex')
        path = self.home / '.codex/config.toml'
        path.write_text(path.read_text().replace(MODEL, 'user-model'))
        with patch('proxy.service.stop_owned') as stop, self.assertRaises(config.ConfigureError):
            self.run_config(off=True)
        stop.assert_not_called()

    def test_failed_service_stop_keeps_configuration(self):
        from proxy.service import ServiceError
        self.run_config(agents='codex')
        path = self.home / '.codex/config.toml'
        before = path.read_bytes()
        with patch('proxy.service.stop_owned', side_effect=ServiceError('untrusted details')), \
                self.assertRaisesRegex(config.ConfigureError, 'configuration unchanged'):
            self.run_config(off=True)
        self.assertEqual(path.read_bytes(), before)

    def test_partial_write_failure_rolls_back(self):
        path = self.write('.codex/config.toml', 'model="old"\n')
        original_write = config.atomic_write
        failed = False

        def fail_once(target, content):
            nonlocal failed
            if target.name == 'settings.json' and not failed:
                failed = True
                raise OSError('simulated write failure')
            original_write(target, content)

        with patch.object(config, 'atomic_write', side_effect=fail_once), self.assertRaises(OSError):
            self.run_config()
        self.assertEqual(path.read_text(), 'model="old"\n')
        self.assertFalse((self.home / '.pi/agent/models.json').exists())
        self.assertFalse((self.home / config.STATE / 'active.json').exists())
        self.assertFalse((self.home / config.STATE / 'pending.json').exists())

    def test_crash_recovery_rolls_back_incomplete_transaction(self):
        path = self.write('.codex/config.toml', 'model="old"\n')
        files = config.plan_files(self.home, ('codex',), BASE, MODEL)
        directory = self.home / config.STATE
        directory.mkdir(parents=True)
        config.atomic_write(directory / 'pending.json', json.dumps({'files':files, 'old_active':None}).encode())
        config.replace_file(path, config.unpacked(files[0]['after']))
        config.recover(self.home, directory)
        self.assertEqual(path.read_text(), 'model="old"\n')
        self.assertFalse((directory / 'pending.json').exists())

    def test_crash_recovery_does_not_clobber_new_edits(self):
        path = self.write('.codex/config.toml', 'model="old"\n')
        files = config.plan_files(self.home, ('codex',), BASE, MODEL)
        directory = self.home / config.STATE
        directory.mkdir(parents=True)
        config.atomic_write(directory / 'pending.json', json.dumps({'files':files, 'old_active':None}).encode())
        path.write_text('model="new-user-choice"\n')
        with self.assertRaisesRegex(config.ConfigureError, 'conflicts'):
            config.recover(self.home, directory)
        self.assertEqual(path.read_text(), 'model="new-user-choice"\n')

    def test_pi_keeps_unrelated_models(self):
        path = self.write('.pi/agent/models.json', '{"providers":{"nebius":{"models":[{"id":"other","name":"Mine"}]}}}')
        self.run_config(agents='pi')
        self.assertEqual(json.loads(path.read_text())['providers']['nebius']['models'][0], {'id':'other','name':'Mine'})
        self.run_config(off=True)
        self.assertEqual(json.loads(path.read_text())['providers']['nebius']['models'], [{'id':'other','name':'Mine'}])

    def test_shell_activation_and_restore(self):
        self.run_config(agents='codex')
        activation = self.home / config.STATE / 'env.sh'
        deactivation = self.home / config.STATE / 'off.sh'
        command = '. "$1"; test "$SPRITES_NEBIUS_PLACEHOLDER" = "$3"; . "$2"; test "${SPRITES_NEBIUS_PLACEHOLDER+x}" != x'
        result = subprocess.run(['sh', '-c', command, 'sh', str(activation), str(deactivation), verify.PLACEHOLDER], env={}, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['sh', '-c', '. "$1"', 'sh', str(activation)],
                                env={config.ENV_KEY:'user-owned-value'}, capture_output=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
