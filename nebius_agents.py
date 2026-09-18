"""Approval-gated native agent acceptance. Dry plan by default, never retries.

Native agents may issue multiple billable requests. A timeout, version pin, or
one CLI invocation is NOT a spend/request cap. Obtain fresh batch approval.
Claude V8 additionally requires --approve-claude-fixture. Its restricted native
tools and fail-closed hook permit only a fixed arithmetic edit/test fixture.

Primary CLI references reviewed 2026-09-16:
https://learn.chatgpt.com/docs/developer-commands?surface=cli
https://learn.chatgpt.com/docs/config-file/config-sample
https://learn.chatgpt.com/docs/non-interactive-mode
https://opencode.ai/docs/cli/
https://opencode.ai/docs/permissions/
https://github.com/earendil-works/pi/tree/main/packages/coding-agent
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from nebius_configure import (
    ConfigureError, ENV_KEY, STATE, configure, document, fields, get_value, read_file, safe_path,
)
from nebius_verify import PLACEHOLDER, gateway_url

PINS = {"codex": "0.154.0", "opencode": "1.18.31", "pi": "0.85.1", "claude": "2.1.273"}
CHECKS = {"codex": "V5", "opencode": "V6", "pi": "V7", "claude": "V8"}
PROMPT = "Reply with exactly: OK"
MAX_OUTPUT = 2 * 1024 * 1024
SPEND_WARNING = "Native agents may make multiple paid requests; request count and spend are not bounded by this runner. Fresh approval is required for each invocation; no automatic retries."
V8_BLOCKER = "V8 requires --approve-claude-fixture and approval for its fixed arithmetic edit/test task on the dedicated test Sprite."


class AgentError(Exception):
    """Static, sanitized diagnostic. Never contains agent output or config."""


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_process(argv, *, cwd, env, timeout, on_start=None):
    """Bound output/time; kill only the new child process group on termination."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise AgentError("Executable failed to start; output omitted") from None
    captured = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        if on_start is not None:
            on_start(proc.pid)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, True)
            selector.register(proc.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentError("Agent timed out; no automatic retry")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_OUTPUT:
                        raise AgentError("Agent output exceeded limit; content omitted")
                    if key.data:
                        captured.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentError("Agent timed out; no automatic retry")
            code = proc.wait(timeout=remaining)
        return code, bytes(captured)
    except subprocess.TimeoutExpired:
        raise AgentError("Agent timed out; no automatic retry") from None
    finally:
        # Also terminate descendants left behind after the parent exits. The
        # session/group was created specifically by this invocation.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def load_selection(home, agents):
    try:
        if read_file(safe_path(home, STATE + "/pending.json")) is not None:
            raise AgentError("Recover interrupted configuration before agent acceptance")
        raw = read_file(safe_path(home, STATE + "/active.json"))
        state = json.loads(raw) if raw else None
        if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("agents"), list):
            raise AgentError("Run scripts/configure before agent acceptance")
        if any(agent not in state["agents"] for agent in agents):
            raise AgentError("A selected agent is not configured")
        gateway = gateway_url(state.get("gateway"))
        model = state.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", model):
            raise AgentError("Invalid selected model")
        specs = fields(agents, gateway, model)
        normal = ".config/opencode/opencode.json"
        commented = normal + "c"
        if normal in specs and safe_path(home, commented).exists():
            if safe_path(home, normal).exists():
                raise AgentError("Both OpenCode JSON and JSONC config exist; resolve precedence first")
            specs[commented] = specs.pop(normal)
        for relative, (kind, changes) in specs.items():
            original = read_file(safe_path(home, relative))
            if original is None:
                raise AgentError("A required agent config is missing")
            current = document(original, kind)
            for path, expected in changes:
                actual = get_value(current.data, path)
                if path == ("providers", "nebius", "models"):
                    if not isinstance(actual, list) or not any(isinstance(row, dict) and row.get("id") == model for row in actual):
                        raise AgentError("Configured model changed; run configure again")
                elif actual != expected:
                    raise AgentError("Configured route or owned setting changed; run configure again")
        return gateway, model
    except (ConfigureError, ValueError, TypeError, argparse.ArgumentTypeError):
        raise AgentError("Invalid or missing agent configuration; contents omitted") from None


def isolated_environment(root, executable, *, node=None):
    # Never inherit provider keys, login credentials, command hooks, proxy
    # settings or agent-specific config overrides from the invoking shell.
    # Keep the approved installed prefix's bin directory for env-based Node
    # shebangs; do not inherit every absolute PATH entry from the caller.
    executable_dir = str(Path(executable).absolute().parent)
    runtime_dirs = []
    if node is not None:
        if not Path(node).is_absolute() or Path(node).name != "node":
            raise AgentError("Node executable must be an absolute path")
        runtime_dirs.append(str(Path(node).parent))
    safe_dirs = list(dict.fromkeys([executable_dir, *runtime_dirs, "/usr/local/bin", "/usr/bin", "/bin"]))
    return {"PATH": os.pathsep.join(safe_dirs), "HOME": str(root / "home"),
            "TMPDIR": str(root / "tmp"), "XDG_CONFIG_HOME": str(root / "home/.config"),
            "XDG_DATA_HOME": str(root / "home/.local/share"),
            "XDG_CACHE_HOME": str(root / "home/.cache"), "LANG": "C.UTF-8",
            "TERM": "dumb", "NO_COLOR": "1", ENV_KEY: PLACEHOLDER,
            "OPENCODE_DISABLE_AUTOUPDATE": "true", "OPENCODE_DISABLE_MODELS_FETCH": "true",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true", "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE": "true", "OPENCODE_AUTO_SHARE": "false",
            "PI_OFFLINE": "1", "PI_TELEMETRY": "0", "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def prepare(root, agent, gateway, model, *, client=None, which=shutil.which):
    home = root / "home"
    for relative in ("home", "work", "tmp"):
        (root / relative).mkdir(mode=0o700)
    # Seed only acceptance restrictions. The real configurator supplies all
    # provider/model fields, so native execution exercises its emitted files.
    for relative, (kind, _) in fields((agent,), gateway, model).items():
        doc = document(None, kind)
        if agent == "codex":
            for path, value in [(("web_search",), "disabled"), (("project_doc_max_bytes",), 0),
                                (("check_for_update_on_startup",), False), (("agents", "enabled"), False),
                                (("analytics", "enabled"), False), (("feedback", "enabled"), False),
                                (("tools", "view_image"), False), (("otel", "metrics_exporter"), "none")]:
                doc.set(path, value)
            for feature in ("shell_tool", "unified_exec", "apps", "hooks", "multi_agent", "remote_plugin"):
                doc.set(("features", feature), False)
        elif agent == "opencode":
            for path, value in [(("permission",), {"*": "deny"}), (("share",), "disabled"),
                                (("autoupdate",), False), (("plugin",), []), (("mcp",), {})]:
                doc.set(path, value)
        elif agent == "pi" and relative.endswith("settings.json"):
            doc.set(("enableInstallTelemetry",), False)
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(doc.render())
        target.chmod(0o600)
    options = argparse.Namespace(agents=agent, connector=gateway.rsplit("/", 1)[1],
                                 model=model, dry_run=False, off=False,
                                 activate=False, approve_service_change=False)
    configure(options, home=home, environ={}, client=client, which=which, inside_sprite=True)
    if load_selection(home, (agent,)) != (gateway, model):
        raise AgentError("Configurator selected an unexpected route")
    return root / "work"


def command(agent, executable):
    if agent == "codex":
        return [executable, "exec", "--json", "--ephemeral", "--sandbox", "read-only",
                "--skip-git-repo-check", "--color", "never", "-c", 'approval_policy="never"', PROMPT]
    if agent == "opencode":
        return [executable, "--pure", "run", "--format", "json", PROMPT]
    if agent == "pi":
        return [executable, "-p", "--no-session", "--no-tools", "--no-extensions", "--no-skills",
                "--no-prompt-templates", "--no-themes", "--no-approve", PROMPT]
    raise AgentError(V8_BLOCKER)


def exact_ok(agent, raw):
    try:
        text = raw.decode("utf-8")
        if agent == "pi":
            return text.strip() == "OK"
        rows = [json.loads(line) for line in text.split("\n") if line.strip()]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        if agent == "codex":
            if any(row.get("type") not in {"thread.started", "turn.started", "item.started", "item.updated", "item.completed", "turn.completed"} for row in rows):
                raise ValueError
            # Codex 0.154 emits its custom-model catalog warning as an error
            # item before the turn. Permit only this exact observed notice;
            # real errors, warnings during execution and attempted tools fail.
            started = False
            filtered = []
            for row in rows:
                if row.get("type") == "turn.started":
                    started = True
                if not started and row.get("type") == "item.completed" and codex_metadata_notice(row.get("item")):
                    continue
                filtered.append(row)
            items = [row["item"] for row in filtered if row.get("type", "").startswith("item.")]
            if any(not isinstance(item, dict) or item.get("type") not in {"reasoning", "agent_message"} for item in items):
                raise ValueError
            answers = [row["item"].get("text") for row in rows if row.get("type") == "item.completed" and row["item"].get("type") == "agent_message"]
            return len(answers) == 1 and answers[0] == "OK" and rows[-1].get("type") == "turn.completed"
        if agent == "opencode":
            if any(row.get("type") not in {"step_start", "text", "step_finish"} for row in rows):
                raise ValueError
            answers = [row["part"]["text"] for row in rows if row["type"] == "text"]
            ends = [row["part"] for row in rows if row["type"] == "step_finish"]
            return len(answers) == 1 and answers[0] == "OK" and len(ends) == 1 and ends[0].get("reason") == "stop"
        raise ValueError
    except (UnicodeError, ValueError, TypeError, KeyError):
        raise AgentError("Unrecognized agent output or attempted tool use; output omitted") from None


def codex_metadata_notice(item):
    return (isinstance(item, dict) and item.get("type") == "error"
            and isinstance(item.get("message"), str)
            and re.fullmatch(r"Model metadata for `[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}` not found\. "
                             r"Defaulting to fallback metadata; this can degrade performance and cause issues\.",
                             item["message"]) is not None)


def output_metadata(agent, raw):
    """Keep schema diagnostics, never prompts, completions, IDs or error text."""
    if agent == "pi":
        return {"bytes": len(raw), "exact_ok": raw.strip() == b"OK"}
    result = {"events": [], "non_json_lines": 0}
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            result["non_json_lines"] += 1
            continue
        def kind(value):
            return value if isinstance(value, str) and re.fullmatch(r"[a-z_.]{1,48}", value) else "unknown"
        event = {"type": kind(row.get("type"))}
        item = row.get("item")
        if isinstance(item, dict):
            event["item_type"] = kind(item.get("type"))
            if codex_metadata_notice(item):
                event["diagnostic"] = "custom_model_fallback_metadata"
            if item.get("type") == "agent_message":
                event["exact_ok"] = item.get("text") == "OK"
        # These diagnostics are fixed labels, not excerpts of CLI output.
        message = row.get("message", "")
        if isinstance(message, str):
            if "metadata" in message.lower() and "model" in message.lower():
                event["diagnostic"] = "model_metadata"
            elif "deprecated" in message.lower():
                event["diagnostic"] = "deprecation"
        result["events"].append(event)
        if len(result["events"]) == 100:
            result["truncated"] = True
            break
    return result


def git_revision():
    try:
        root = Path(__file__).resolve().parent
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, timeout=5, check=True)
        revision = result.stdout.decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, timeout=5, check=True)
        return {"git_revision": revision, "working_tree_dirty": bool(dirty.stdout)}
    except (OSError, ValueError, subprocess.SubprocessError):
        raise AgentError("Cannot determine local source revision; no agent launched") from None


def execute(args, *, home=None, environ=None, inside_sprite=None, run=run_process,
            which=shutil.which, revision=git_revision, client=None,
            on_process=None, on_fixture=None):
    agents = tuple(args.agents.split(","))
    if not agents or len(set(agents)) != len(agents) or any(name not in PINS for name in agents):
        raise AgentError("Select distinct codex,opencode,pi,claude agents explicitly")
    report = {"schema_version": 1, "observed_at": utcnow(), "full_spec_verified": False,
              "spend_warning": SPEND_WARNING, "results": []}
    if not args.approve_agent_runs:
        report["status"] = "dry_plan"
        report["results"] = [{"check": CHECKS[a], "agent": a, "status": "blocked" if a == "claude" else "not_run",
                              "reason": V8_BLOCKER if a == "claude" else "Explicit paid-agent approval required",
                              "candidate_version": PINS[a]} for a in agents]
        return report
    if inside_sprite is None:
        inside_sprite = Path("/.sprite").is_dir()
    if not inside_sprite:
        raise AgentError("Run approved agent acceptance inside the intended Sprite")
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    report.update(revision())
    approved_claude = getattr(args, "approve_claude_fixture", False)
    selected = tuple(a for a in agents if a != "claude" or approved_claude)
    if selected:
        gateway, model = load_selection(home, selected)
        report["model"] = model
        report["gateway"] = gateway
    report["status"] = "completed"
    stopped = False
    for agent in agents:
        row = {"check": CHECKS[agent], "agent": agent, "candidate_version": PINS[agent], "started_at": utcnow()}
        report["results"].append(row)
        if agent == "claude" and not approved_claude:
            row.update(status="blocked", reason=V8_BLOCKER)
        elif stopped:
            row.update(status="not_run", reason="Earlier agent did not pass; fresh approval required before retry")
        else:
            try:
                executable = which(agent)
                if not executable or not Path(executable).is_absolute():
                    raise AgentError("Pinned agent executable is missing")
                with tempfile.TemporaryDirectory(prefix="sprites-nebius-agent-") as directory:
                    root = Path(directory).resolve()
                    work = prepare(root, agent, gateway, model, client=client, which=which)
                    row["cleanup"] = "needs-attention"
                    try:
                        env = isolated_environment(root, executable, node=which("node"))
                        code, raw = run([executable, "--version"], cwd=work, env=env, timeout=10)
                        versions = re.findall(rb"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", raw)
                        if code or versions != [PINS[agent].encode()]:
                            raise AgentError("Installed agent version does not match the reviewed candidate pin")
                        row["verified_version"] = PINS[agent]
                        if agent == "claude":
                            import nebius_claude
                            settings = nebius_claude.setup(root)
                            argv = nebius_claude.command(executable, settings)
                        else:
                            argv = command(agent, executable)
                        callbacks = {"on_start": on_process} if on_process is not None else {}
                        code, raw = run(argv, cwd=work, env=env, timeout=args.timeout, **callbacks)
                        row["output_metadata"] = output_metadata(agent, raw)
                        if code:
                            raise AgentError("Agent returned nonzero; output omitted and no retry")
                        if agent == "claude":
                            row.update(nebius_claude.verify(work, raw, run, env))
                        else:
                            passed = exact_ok(agent, raw)
                            row.update(status="pass" if passed else "fail", exact_ok=passed)
                            if not passed:
                                row["reason"] = "Final answer was not exactly OK; content omitted"
                    finally:
                        try:
                            if on_fixture is not None:
                                on_fixture(root)
                        finally:
                            configure(argparse.Namespace(off=True, dry_run=False, agents=agent,
                                                        connector=None, model=None, activate=False,
                                                        approve_service_change=False),
                                      home=root / "home", environ={}, inside_sprite=True)
                            row["cleanup"] = "restored"
                    row["configuration_path"] = "configurator_written_isolated_home"
            except AgentError as error:
                row.update(status="inconclusive", reason=str(error))
            except (ConfigureError, OSError):
                row.update(status="inconclusive", cleanup="needs-attention",
                           reason="Agent/config/version/output check failed; inspect locally under fresh approval, no output logged")
            stopped = row["status"] != "pass"
        row["finished_at"] = utcnow()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", required=True, help="Explicit comma-separated selection")
    parser.add_argument("--approve-agent-runs", action="store_true", help=SPEND_WARNING)
    parser.add_argument("--approve-claude-fixture", action="store_true", help="Also authorize the confined Claude arithmetic edit/test fixture")
    parser.add_argument("--timeout", type=int, default=120, help="Per native-agent invocation, 10..600 seconds; not a spend cap")
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 600:
        parser.error("timeout must be 10..600 seconds")
    try:
        report = execute(args)
    except AgentError as error:
        report = {"observed_at": utcnow(), "status": "blocked", "reason": str(error), "full_spec_verified": False}
    print(json.dumps(report, indent=2))
    return 0 if report.get("results") and all(row["status"] == "pass" for row in report["results"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
