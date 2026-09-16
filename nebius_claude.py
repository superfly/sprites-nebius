"""Confined Claude acceptance fixture, not a general code-execution sandbox.

Claude's restricted mode confines native file tools to the temporary workspace.
A PreToolUse hook permits only its two fixture files and one fixed test command.
The command can execute only the exact harmless arithmetic AST below; edited
tests, imports, calls, symlinks, alternate paths and shell commands are denied.
This relies on the reviewed CLI and an otherwise trusted dedicated test Sprite.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shlex
import sys

BEFORE = "def add(a, b):\n    return a - b\n"
AFTER = "def add(a, b):\n    return a + b\n"
TEST = '''import unittest
from arithmetic import add

class AdditionTest(unittest.TestCase):
    def test_addition(self):
        for a, b in [(2, 3), (-3, 7), (0, 0), (4, -9)]:
            self.assertEqual(add(a, b), a + b)
'''
TEST_COMMAND = "python3 -I -B -m unittest discover -s . -p test_arithmetic.py"
PROMPT = (
    "In this temporary fixture, read arithmetic.py and test_arithmetic.py. "
    "Fix add(a, b) by changing only its subtraction to addition in arithmetic.py. "
    "Do not edit the test or any other file. Then run exactly this Bash command: "
    + TEST_COMMAND + ". After the test passes, reply with exactly: OK. "
    "Use only Read, Edit and that one Bash command; do not delegate."
)


def checked_file(work, name):
    path = work / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("Invalid fixture file")
    return path.read_text()


def valid_fixture(work, *, fixed=False):
    try:
        if work.is_symlink() or not work.is_dir():
            return False
        if set(p.name for p in work.iterdir()) != {"arithmetic.py", "test_arithmetic.py"}:
            return False
        if checked_file(work, "test_arithmetic.py") != TEST:
            return False
        tree = ast.dump(ast.parse(checked_file(work, "arithmetic.py")))
        allowed = [AFTER] if fixed else [BEFORE, AFTER]
        return tree in [ast.dump(ast.parse(source)) for source in allowed]
    except (OSError, ValueError, SyntaxError, UnicodeError):
        return False


def permitted(work, event):
    try:
        if not isinstance(event, dict):
            return False
        if event.get("hook_event_name") != "PreToolUse" or Path(event["cwd"]).resolve() != work:
            return False
        name, payload = event["tool_name"], event["tool_input"]
        if not isinstance(payload, dict) or not valid_fixture(work):
            return False
        if name == "Bash":
            return (payload.get("command") == TEST_COMMAND
                    and not payload.get("run_in_background")
                    and valid_fixture(work, fixed=True))
        if name not in ("Read", "Edit"):
            return False
        path = Path(payload["file_path"])
        allowed = [work / "arithmetic.py"]
        if name == "Read":
            allowed.append(work / "test_arithmetic.py")
        if not path.is_absolute() or path not in allowed or path.is_symlink():
            return False
        if name == "Edit":
            old, new = payload["old_string"], payload["new_string"]
            if not isinstance(old, str) or not old or not isinstance(new, str) or len(new) > 8192:
                return False
            source = checked_file(work, "arithmetic.py")
            if source.count(old) != 1 or payload.get("replace_all"):
                return False
            # Validate the proposed edit before Claude writes it, not only
            # before executing it. Only the exact arithmetic fix is permitted.
            return ast.dump(ast.parse(source.replace(old, new, 1))) == ast.dump(ast.parse(AFTER))
        return True
    except (KeyError, TypeError, ValueError, OSError, SyntaxError):
        return False


def setup(root):
    work = root / "work"
    for name, text in (("arithmetic.py", BEFORE), ("test_arithmetic.py", TEST)):
        path = work / name
        path.write_text(text)
        path.chmod(0o600)
    settings = root / "home/.claude/settings.json"
    data = json.loads(settings.read_text())
    data["hooks"] = {"PreToolUse": [{"hooks": [{"type": "command", "timeout": 10,
        "command": shlex.join([sys.executable, "-I", str(Path(__file__).resolve()), str(work)])}]}]}
    data["permissions"] = {"allow": [], "deny": []}
    settings.write_text(json.dumps(data))
    return settings


def command(executable, settings):
    # No blanket allowedTools or permission bypass: a missing/broken hook
    # cannot silently authorize Edit or Bash under dontAsk.
    return [executable, "-p", "--restricted", "--permission-mode", "dontAsk",
            "--tools", "Read,Edit,Bash", "--settings", str(settings),
            "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--no-chrome", "--no-session-persistence",
            "--max-turns", "6", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--", PROMPT]


def verify(work, raw, run, env):
    """Require real Edit/Bash results, stream events, unchanged tests and rerun."""
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        terminal = rows[-1]
        calls, completed, deltas = {}, set(), 0
        for row in rows:
            if row.get("type") == "stream_event":
                event = row.get("event", {})
                if event.get("type") == "content_block_delta":
                    deltas += 1
            message = row.get("message", {})
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    if block.get("name") not in ("Read", "Edit", "Bash"):
                        raise ValueError
                    calls[block["id"]] = block["name"]
                if block.get("type") == "tool_result" and not block.get("is_error", False):
                    completed.add(block["tool_use_id"])
        tools = {calls[call] for call in completed if call in calls}
        passed = (terminal.get("type") == "result" and terminal.get("subtype") == "success"
                  and not terminal.get("is_error") and not terminal.get("permission_denials")
                  and terminal.get("result", "").strip() == "OK"
                  and {"Edit", "Bash"} <= tools and deltas > 0 and valid_fixture(work, fixed=True))
        code = None
        if passed:
            code, _ = run(shlex.split(TEST_COMMAND), cwd=work, env=env, timeout=10)
        return {"status": "pass" if passed and code == 0 else "inconclusive",
                "stream_delta_count": deltas, "edit_observed": "Edit" in tools,
                "test_tool_observed": "Bash" in tools, "independent_test_passed": code == 0,
                "fixture_valid": valid_fixture(work, fixed=True)}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"status": "inconclusive", "reason": "Unexpected Claude event schema; contents omitted"}


def main():
    allowed = False
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) <= 65536 and len(sys.argv) == 2:
            allowed = permitted(Path(sys.argv[1]).resolve(), json.loads(raw))
    except (ValueError, TypeError, OSError):
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "allow" if allowed else "deny",
        "permissionDecisionReason": "Approved arithmetic fixture operation" if allowed else "Outside the approved arithmetic fixture"}}))


if __name__ == "__main__":
    main()
