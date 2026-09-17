import json
from pathlib import Path
import tempfile
import unittest

from nebius_claude import AFTER, BEFORE, TEST, TEST_COMMAND, command, permitted, valid_fixture, verify


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()
        (self.work / 'arithmetic.py').write_text(BEFORE)
        (self.work / 'test_arithmetic.py').write_text(TEST)

    def event(self, name, **payload):
        return {'hook_event_name': 'PreToolUse', 'cwd': str(self.work),
                'tool_name': name, 'tool_input': payload}

    def test_only_exact_arithmetic_edit(self):
        path = str(self.work / 'arithmetic.py')
        self.assertTrue(permitted(self.work, self.event('Edit', file_path=path, old_string='a - b', new_string='a + b')))
        for replacement in ['__import__("os").system("id")', 'a * b', 'a + b\nimport os']:
            self.assertFalse(permitted(self.work, self.event('Edit', file_path=path, old_string='a - b', new_string=replacement)))

    def test_equivalent_source_is_not_the_approved_edit(self):
        path = str(self.work / 'arithmetic.py')
        for replacement in ['# coding: unicode_escape\n' + AFTER,
                            '# comment\n' + AFTER, AFTER + '\n',
                            AFTER.replace('a + b', '(a + b)'), '\ufeff' + AFTER]:
            with self.subTest(replacement=replacement):
                self.assertFalse(permitted(self.work, self.event(
                    'Edit', file_path=path, old_string=BEFORE, new_string=replacement)))

    def test_fixture_execution_requires_exact_bytes(self):
        for name, expected in [('arithmetic.py', AFTER), ('test_arithmetic.py', TEST)]:
            for raw in [("# coding: unicode_escape\n" + expected).encode(),
                        expected.replace('\n', '\r\n').encode(),
                        b'\xef\xbb\xbf' + expected.encode(), b'\xff']:
                with self.subTest(name=name, raw=raw):
                    (self.work / 'arithmetic.py').write_bytes(AFTER.encode())
                    (self.work / 'test_arithmetic.py').write_bytes(TEST.encode())
                    (self.work / name).write_bytes(raw)
                    self.assertFalse(valid_fixture(self.work, fixed=True))
                    self.assertFalse(permitted(self.work, self.event('Bash', command=TEST_COMMAND)))

    def test_test_edit_and_outside_read_denied(self):
        self.assertFalse(permitted(self.work, self.event('Edit', file_path=str(self.work/'test_arithmetic.py'), old_string=TEST, new_string='pass')))
        for path in ['/etc/passwd', str(self.work/'../outside'), 'arithmetic.py']:
            self.assertFalse(permitted(self.work, self.event('Read', file_path=path)))
        self.assertTrue(permitted(self.work, self.event('Read', file_path=str(self.work/'test_arithmetic.py'))))

    def test_shell_command_and_source_checked(self):
        event = self.event('Bash', command=TEST_COMMAND)
        self.assertFalse(permitted(self.work, event))
        (self.work/'arithmetic.py').write_text(AFTER)
        self.assertTrue(permitted(self.work, event))
        for command_text in [TEST_COMMAND+'; id', 'echo OK', 'python3 -c "print(1)"']:
            self.assertFalse(permitted(self.work, self.event('Bash', command=command_text)))
        self.assertFalse(permitted(self.work, self.event('Bash', command=TEST_COMMAND, run_in_background=True)))
        (self.work/'test_arithmetic.py').write_text('import os')
        self.assertFalse(permitted(self.work, event))

    def test_unexpected_files_symlinks_and_tools_denied(self):
        self.assertFalse(permitted(self.work, self.event('Write', file_path=str(self.work/'arithmetic.py'), content=AFTER)))
        (self.work/'sitecustomize.py').write_text('pass')
        self.assertFalse(valid_fixture(self.work))
        (self.work/'sitecustomize.py').unlink()
        (self.work/'arithmetic.py').unlink()
        (self.work/'arithmetic.py').symlink_to(self.work/'test_arithmetic.py')
        self.assertFalse(valid_fixture(self.work))

    def test_wrong_cwd_and_malformed_event_denied(self):
        event = self.event('Read', file_path=str(self.work/'arithmetic.py'))
        event['cwd'] = '/'
        self.assertFalse(permitted(self.work, event))
        for event in [{}, {'tool_input': []}]:
            self.assertFalse(permitted(self.work, event))

    def test_command_uses_restricted_mode_not_permission_bypass(self):
        argv = command('/bin/claude', self.work/'settings.json')
        self.assertIn('--restricted', argv)
        self.assertIn('dontAsk', argv)
        self.assertIn('--max-turns', argv)
        self.assertNotIn('--allowedTools', argv)
        self.assertFalse(any('dangerously' in part for part in argv))

    def test_success_requires_edit_test_stream_and_independent_check(self):
        (self.work/'arithmetic.py').write_text(AFTER)
        rows = [{'type':'assistant','message':{'content':[
            {'type':'tool_use','name':'Edit','id':'a'}, {'type':'tool_use','name':'Bash','id':'b'}]}},
            {'type':'user','message':{'content':[
                {'type':'tool_result','tool_use_id':'a'}, {'type':'tool_result','tool_use_id':'b'}]}},
            {'type':'stream_event','event':{'type':'content_block_delta'}},
            {'type':'result','subtype':'success','is_error':False,'result':'OK'}]
        def run(argv, **kwargs):
            self.assertEqual(kwargs['cwd'], self.work)
            return 0, b''
        raw = lambda: b'\n'.join(json.dumps(row).encode() for row in rows)
        self.assertEqual(verify(self.work, raw(), run, {})['status'], 'pass')
        rows[-1]['permission_denials'] = [{}]
        self.assertEqual(verify(self.work, raw(), run, {})['status'], 'inconclusive')
        rows[-1].pop('permission_denials')
        rows.pop(2)
        self.assertEqual(verify(self.work, raw(), run, {})['status'], 'inconclusive')

    def test_truncated_output_never_passes(self):
        self.assertEqual(verify(self.work, b'bad', None, {})['status'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
