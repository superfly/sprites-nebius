"""Reversible, local-only agent configuration; never sends inference requests.

Configuration is not compatibility certification. Project-local settings and
CLI overrides still take precedence; run live acceptance in a clean directory.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

from nebius_verify import Client, PLACEHOLDER, ProbeError, discover, model_ids

AGENTS = ("codex", "opencode", "pi", "claude")
ENV_KEY = "SPRITES_NEBIUS_PLACEHOLDER"
STATE = ".local/state/sprites-nebius"
# Shared by configuration readers and aggregate ownership/recovery records.
MAX_CONFIG = 2 * 1024 * 1024
MISSING = object()


class ConfigureError(Exception):
    """A diagnostic without configuration contents or credentials."""


def bounded_content(content):
    if content is not None and len(content) > MAX_CONFIG:
        raise ConfigureError("Configuration or recovery state exceeds the 2 MiB limit; "
                             "select fewer agents or reduce configuration size")
    return content


def safe_path(home, relative):
    path = home / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ConfigureError("Invalid path in configuration state")
    for part in (path, *path.parents):
        if part == home.parent:
            break
        if part.is_symlink():
            raise ConfigureError("Refusing a symlink in configuration paths")
    return path


def read_file(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ConfigureError("Refusing a symlink in configuration paths")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_CONFIG:
        raise ConfigureError("Configuration is not a bounded regular file")
    return path.read_bytes()


def atomic_write(path, content):
    bounded_content(content)
    read_file(path)  # Check the destination and every parent before replacement.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".sprites-nebius-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def replace_file(path, content):
    if content is None:
        if path.exists():
            path.unlink()
    else:
        atomic_write(path, content)


def packed(value):
    return None if value is None else base64.b64encode(value).decode("ascii")


def unpacked(value):
    return None if value is None else base64.b64decode(value, validate=True)


class JsonDocument:
    """Strict JSON plus comments/trailing commas, retaining source spans.

    Only object members are edited. Unknown fields, whitespace, and comments
    outside an owned value remain byte-for-byte unchanged.
    """
    token = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:[^"\\\x00-\x1f]|\\.)*"|'
                       r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null|[{}\[\]:,]')

    def __init__(self, text):
        self.text = text
        self.tokens = []
        pos = 0
        while pos < len(text):
            match = self.token.match(text, pos)
            if match is None:
                raise ConfigureError("Malformed JSON configuration")
            value = match.group()
            if not value.isspace() and not value.startswith(("//", "/*")):
                self.tokens.append((value, pos, match.end()))
            pos = match.end()
        self.index = 0
        self.nodes = {}
        self.data = self.parse(())
        if self.index != len(self.tokens) or not isinstance(self.data, dict):
            raise ConfigureError("Configuration must be a JSON object")

    def take(self, expected=None):
        if self.index >= len(self.tokens):
            raise ConfigureError("Truncated JSON configuration")
        item = self.tokens[self.index]
        if expected is not None and item[0] != expected:
            raise ConfigureError("Malformed JSON configuration")
        self.index += 1
        return item

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def parse(self, path):
        token, start, end = self.take()
        node = {"start": start, "end": end, "members": {}}
        self.nodes[path] = node
        if token in ("{", "["):
            result = {} if token == "{" else []
            close = "}" if token == "{" else "]"
            while self.peek() != close:
                if token == "{":
                    name, key_start, _ = self.take()
                    try:
                        key = json.loads(name)
                    except ValueError:
                        raise ConfigureError("Invalid JSON object key") from None
                    if not isinstance(key, str) or key in result:
                        raise ConfigureError("Duplicate or invalid JSON object key")
                    self.take(":")
                    result[key] = self.parse(path + (key,))
                    member = {"start": key_start, "end": self.nodes[path + (key,)]["end"]}
                    node["members"][key] = member
                else:
                    result.append(self.parse(path + (len(result),)))
                    member = {}
                if self.peek() != ",":
                    break
                comma = self.take(",")
                member["comma"] = (comma[1], comma[2])
            _, node["close"], node["end"] = self.take(close)
            return result
        try:
            return json.loads(token)
        except ValueError:
            raise ConfigureError("Invalid JSON value") from None

    def set(self, path, value=MISSING):
        parent_path, key = path[:-1], path[-1]
        for i in range(1, len(path)):
            if path[:i] not in self.nodes:
                self.set(path[:i], {})
            if not isinstance(get_value(self.data, path[:i]), dict):
                raise ConfigureError("Configuration parent is not an object")
        parent = self.nodes[parent_path]
        member = parent["members"].get(key)
        edits = []
        if value is MISSING:
            if not member:
                return
            # Remove punctuation separately so comments are not swallowed.
            edits.append((member["start"], member["end"], ""))
            if "comma" in member:
                edits.append((*member["comma"], ""))
            else:
                keys = list(parent["members"])
                index = keys.index(key)
                if index:
                    previous = parent["members"][keys[index - 1]]
                    if "comma" in previous:
                        edits.append((*previous["comma"], ""))
        elif member:
            node = self.nodes[path]
            edits.append((node["start"], node["end"], json.dumps(value, ensure_ascii=False)))
        else:
            members = list(parent["members"].values())
            comma_prefix = ""
            if members and "comma" not in members[-1]:
                if members[-1]["end"] == parent["close"]:
                    comma_prefix = ","
                else:
                    edits.append((members[-1]["end"], members[-1]["end"], ","))
            prefix = "\n" + "  " * len(path)
            edits.append((parent["close"], parent["close"],
                          comma_prefix + prefix + json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False) + "\n"))
        for start, end, replacement in sorted(edits, reverse=True):
            self.text = self.text[:start] + replacement + self.text[end:]
        self.__init__(self.text)

    def render(self):
        return self.text


class TomlDocument:
    def __init__(self, text):
        try:
            import tomlkit
        except ImportError:
            raise ConfigureError("Install requirements-configure.txt into a virtual environment first") from None
        self.tomlkit = tomlkit
        try:
            self.data = tomlkit.parse(text)
        except Exception:
            raise ConfigureError("Malformed TOML configuration") from None

    def set(self, path, value=MISSING):
        target = self.data
        for key in path[:-1]:
            if key not in target:
                target[key] = self.tomlkit.table()
            if not hasattr(target[key], "keys"):
                raise ConfigureError("Configuration parent is not a TOML table")
            target = target[key]
        if value is MISSING:
            target.pop(path[-1], None)
        else:
            target[path[-1]] = value

    def render(self):
        return self.tomlkit.dumps(self.data)


def get_value(data, path):
    for key in path:
        if not hasattr(data, "keys") or key not in data:
            return MISSING
        data = data[key]
    return data


def document(raw, kind):
    try:
        text = raw.decode("utf-8") if raw is not None else ("" if kind == "toml" else "{}\n")
    except UnicodeError:
        raise ConfigureError("Configuration is not UTF-8") from None
    return TomlDocument(text) if kind == "toml" else JsonDocument(text)


def fields(agents, gateway, model):
    """Canonical templates. Values are placeholders, never provider keys."""
    result = {}
    if "codex" in agents:
        provider = {"name": "Nebius via Fly.io Sprites", "base_url": gateway,
                    "env_key": ENV_KEY, "wire_api": "responses", "requires_openai_auth": False,
                    "request_max_retries": 0, "stream_max_retries": 0, "supports_websockets": False}
        result[".codex/config.toml"] = ("toml", [(('model',), model), (('model_provider',), 'nebius')] +
            [(('model_providers', 'nebius', key), value) for key, value in provider.items()])
    if "opencode" in agents:
        result[".config/opencode/opencode.json"] = ("json", [
            (("model",), "nebius/" + model),
            (("provider", "nebius", "options", "baseURL"), gateway),
            (("provider", "nebius", "options", "apiKey"), "{env:" + ENV_KEY + "}"),
            (("provider", "nebius", "models", model, "name"), model)])
    if "pi" in agents:
        result[".pi/agent/models.json"] = ("json", [
            (("providers", "nebius", "baseUrl"), gateway),
            (("providers", "nebius", "api"), "openai-completions"),
            (("providers", "nebius", "apiKey"), "$" + ENV_KEY),
            (("providers", "nebius", "models"), [{"id": model}])])
        result[".pi/agent/settings.json"] = ("json", [
            (("defaultProvider",), "nebius"), (("defaultModel",), model),
            (("retry", "enabled"), False)])
    if "claude" in agents:
        env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8083", "ANTHROPIC_AUTH_TOKEN": PLACEHOLDER,
               "ANTHROPIC_MODEL": model, "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
               "ANTHROPIC_DEFAULT_SONNET_MODEL": model, "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
               "CLAUDE_CODE_SUBAGENT_MODEL": model, "CLAUDE_CODE_MAX_RETRIES": "0",
               "CLAUDE_CODE_RETRY_WATCHDOG": "0", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
               "MAX_THINKING_TOKENS": "0", "CLAUDE_CODE_DISABLE_THINKING": "1"}
        result[".claude/settings.json"] = ("json", [(('env', key), value) for key, value in env.items()])
        proxy = {"OPENAI_BASE_URL": gateway, "OPENAI_API_KEY": PLACEHOLDER,
                 "ANTHROPIC_API_KEY": PLACEHOLDER, "BIG_MODEL": model, "MIDDLE_MODEL": model,
                 "SMALL_MODEL": model, "MAX_TOKENS_LIMIT": "16384"}
        result[STATE + "/proxy.json"] = ("json", [((key,), value) for key, value in proxy.items()])
    return result


def credential_preflight(data, relative):
    # Never replace an existing credential, credential command, or custom auth header.
    checks = {
        ".codex/config.toml": [("model_providers", "nebius", "experimental_bearer_token"),
                               ("model_providers", "nebius", "auth"),
                               ("model_providers", "nebius", "env_key"),
                               ("model_providers", "nebius", "query_params"),
                               ("model_providers", "nebius", "http_headers"),
                               ("model_providers", "nebius", "env_http_headers")],
        ".config/opencode/opencode.json": [("provider", "nebius", "options", "apiKey"),
                                            ("provider", "nebius", "options", "headers")],
        ".pi/agent/models.json": [("providers", "nebius", "apiKey"), ("providers", "nebius", "headers")],
        ".claude/settings.json": [("env", "ANTHROPIC_API_KEY"), ("env", "ANTHROPIC_AUTH_TOKEN")],
    }
    allowed = (PLACEHOLDER, ENV_KEY, "$" + ENV_KEY, "{env:" + ENV_KEY + "}", "", {})
    for path in checks.get(relative.replace(".jsonc", ".json"), []):
        value = get_value(data, path)
        if value is not MISSING and value not in allowed:
            raise ConfigureError("Existing provider credentials or headers must be removed by their owner first")


def plan_files(home, agents, gateway, model):
    specs = fields(agents, gateway, model)
    normal = ".config/opencode/opencode.json"
    commented = normal + "c"
    if normal in specs and safe_path(home, commented).exists():
        if safe_path(home, normal).exists():
            raise ConfigureError("Both OpenCode JSON and JSONC config exist; resolve precedence first")
        specs[commented] = specs.pop(normal)
    files = []
    for relative, (kind, changes) in specs.items():
        raw = read_file(safe_path(home, relative))
        doc = document(raw, kind)
        credential_preflight(doc.data, relative)
        owned = []
        created = []
        for path, desired in changes:
            previous = get_value(doc.data, path)
            if path == ("providers", "nebius", "models") and previous is not MISSING:
                if not isinstance(previous, list) or any(not isinstance(row, dict) for row in previous):
                    raise ConfigureError("Pi models must be an array of objects")
                desired = previous if any(row.get("id") == model for row in previous) else previous + desired
            for i in range(1, len(path)):
                if get_value(doc.data, path[:i]) is MISSING and list(path[:i]) not in created:
                    created.append(list(path[:i]))
            owned.append({"path": list(path), "before_present": previous is not MISSING,
                          "before": None if previous is MISSING else previous, "after": desired})
            doc.set(path, desired)
        files.append({"path": relative, "kind": kind, "before": packed(raw),
                      "after": packed(doc.render().encode()), "owned": owned, "created": created})
    helper = activation_shell().encode()
    for name, content in (("env.sh", helper), ("off.sh", deactivation_shell().encode())):
        relative = STATE + "/" + name
        raw = read_file(safe_path(home, relative))
        if raw is not None and not (name == "off.sh" and raw == content):
            raise ConfigureError("Unowned activation helper already exists")
        files.append({"path": relative, "kind": "raw", "before": packed(raw), "after": packed(content),
                      "owned": [], "created": []})
    return files


def activation_shell():
    return ("# Source this file in the current shell; no startup files are changed.\n"
            f'if [ "${{{ENV_KEY}+set}}" = set ] && [ "${{{ENV_KEY}}}" != {shlex.quote(PLACEHOLDER)} ]; then\n'
            "  printf '%s\\n' 'Refusing to overwrite existing placeholder variable' >&2\n"
            "  return 1\nfi\n"
            f'if [ "${{{ENV_KEY}+set}}" != set ]; then\n'
            "  export SPRITES_NEBIUS_OWNS_PLACEHOLDER=1\nfi\n"
            f"export {ENV_KEY}={shlex.quote(PLACEHOLDER)}\n")


def deactivation_shell():
    return ("# Source after configure --off; keep this harmless helper for active shells.\n"
            f'if [ "${{SPRITES_NEBIUS_OWNS_PLACEHOLDER-}}" = 1 ] && [ "${{{ENV_KEY}-}}" = {shlex.quote(PLACEHOLDER)} ]; then\n'
            f"  unset {ENV_KEY} SPRITES_NEBIUS_OWNS_PLACEHOLDER\nfi\n")


def assert_owned(home, state):
    for row in state["files"]:
        raw = read_file(safe_path(home, row["path"]))
        if raw is None:
            raise ConfigureError("An owned configuration file was removed; restore conflicts")
        if row["kind"] == "raw":
            if raw != unpacked(row["after"]):
                raise ConfigureError("An owned helper changed; restore conflicts")
            continue
        doc = document(raw, row["kind"])
        for field in row["owned"]:
            if get_value(doc.data, field["path"]) != field["after"]:
                raise ConfigureError("An owned configuration field changed; restore conflicts")


def restoration(home, state):
    assert_owned(home, state)
    result = []
    for row in state["files"]:
        raw = read_file(safe_path(home, row["path"]))
        if row["path"].endswith("/off.sh"):
            continue  # Active shells still need this non-secret helper after --off.
        if raw == unpacked(row["after"]):
            restored = unpacked(row["before"])
        elif row["kind"] != "raw":
            doc = document(raw, row["kind"])
            for field in reversed(row["owned"]):
                doc.set(tuple(field["path"]), field["before"] if field["before_present"] else MISSING)
            for path in sorted(row["created"], key=len, reverse=True):
                value = get_value(doc.data, path)
                if value is not MISSING and not value:
                    doc.set(tuple(path))
            restored = doc.render().encode()
        else:
            raise ConfigureError("Changed helper cannot be restored")
        result.append({**row, "before": packed(raw), "after": packed(restored)})
    return result


def recover(home, state_dir):
    path = state_dir / "pending.json"
    raw = read_file(path)
    if raw is None:
        return
    try:
        pending = json.loads(raw)
        old_active = bounded_content(unpacked(pending["old_active"]))
        for row in pending["files"]:
            before = bounded_content(unpacked(row["before"]))
            after = bounded_content(unpacked(row["after"]))
            current = read_file(safe_path(home, row["path"]))
            if current not in (before, after):
                raise ConfigureError("Interrupted update conflicts with a later edit; manual recovery required")
        for row in reversed(pending["files"]):
            replace_file(safe_path(home, row["path"]), unpacked(row["before"]))
        replace_file(state_dir / "active.json", old_active)
        path.unlink()
    except (ValueError, KeyError, TypeError):
        raise ConfigureError("Invalid recovery journal; manual recovery required") from None


def prepare_transaction(files, active, previous):
    """Keep every write and its rollback readable by all ownership consumers."""
    for row in files:
        bounded_content(unpacked(row["before"]))
        bounded_content(unpacked(row["after"]))
    bounded_content(previous)
    active_raw = bounded_content(json.dumps(active).encode() if active else None)
    pending = {"files": files, "old_active": packed(previous)}
    pending_raw = bounded_content(json.dumps(pending).encode())
    return active_raw, pending_raw


def transact(home, state_dir, files, active):
    active_raw, pending_raw = prepare_transaction(files, active, read_file(state_dir / "active.json"))
    atomic_write(state_dir / "pending.json", pending_raw)
    try:
        for row in files:
            if read_file(safe_path(home, row["path"])) != unpacked(row["before"]):
                raise ConfigureError("Configuration changed during planning; nothing overwritten")
            replace_file(safe_path(home, row["path"]), unpacked(row["after"]))
        replace_file(state_dir / "active.json", active_raw)
        (state_dir / "pending.json").unlink()
    except BaseException:
        recover(home, state_dir)
        raise


def preflight(agents, environ, which):
    missing = [name for name in agents if which(name) is None]
    if missing:
        raise ConfigureError("Install the selected agents first: " + ", ".join(missing) + "; see docs/agent-setup.md")
    for key in ("CODEX_HOME", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT",
                "PI_CODING_AGENT_DIR", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        if environ.get(key):
            raise ConfigureError("Custom configuration location detected; use a clean shell without " + key)
    if environ.get(ENV_KEY) not in (None, "", PLACEHOLDER):
        raise ConfigureError("Refusing to overwrite existing placeholder variable")
    for key in ("NEBIUS_API_KEY", "NEBIUS_TOKEN"):
        if environ.get(key) not in (None, "", PLACEHOLDER):
            raise ConfigureError("A real provider credential is present in the environment; remove it first")
    if "claude" in agents:
        if environ.get("CLAUDE_CODE_RETRY_WATCHDOG") not in (None, "", "0"):
            raise ConfigureError("Disable the Claude retry watchdog before configuring")
        if environ.get("ANTHROPIC_BASE_URL") not in (None, "", "http://127.0.0.1:8083"):
            raise ConfigureError("Custom Claude endpoint in environment; remove it before configuring")
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            if environ.get(key) not in (None, "", PLACEHOLDER):
                raise ConfigureError("Existing Claude credentials must be removed by their owner first")


def configure(args, *, home=None, environ=None, client=None, which=shutil.which, inside_sprite=None):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    if inside_sprite is None:
        inside_sprite = Path("/.sprite").is_dir()
    if not inside_sprite:
        raise ConfigureError("Run configure inside the intended Sprite, not on your laptop")
    state_dir = safe_path(home, STATE)
    if args.dry_run and (state_dir / "pending.json").exists():
        raise ConfigureError("Interrupted update needs recovery; run configure --off without --dry-run")
    if not args.dry_run:
        read_file(state_dir / "lock")
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(state_dir, 0o700)
    lock = contextlib.nullcontext() if args.dry_run else (state_dir / "lock").open("a")
    with lock as handle:
        if handle is not None:
            os.chmod(state_dir / "lock", 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            recover(home, state_dir)
        raw_state = read_file(state_dir / "active.json")
        try:
            state = json.loads(raw_state) if raw_state else None
        except ValueError:
            raise ConfigureError("Invalid ownership state; manual recovery required") from None
        if state is not None and (not isinstance(state, dict) or state.get("version") != 1
                                  or not isinstance(state.get("files"), list)):
            raise ConfigureError("Invalid ownership state; manual recovery required")
        if args.off:
            if not state:
                return {"status": "already_off", "full_spec_verified": False}
            files = restoration(home, state)
            prepare_transaction(files, None, raw_state)
            if not args.dry_run:
                # Only the definition owned by proxy/service.py may be stopped.
                # Validate all restoration conflicts before any service mutation.
                from proxy.service import ServiceError, stop_owned
                try:
                    stop_owned(home, locked=True)
                except ServiceError:
                    raise ConfigureError("Owned proxy service could not be safely stopped; configuration unchanged") from None
                transact(home, state_dir, files, None)
            return {"status": "dry_run" if args.dry_run else "off", "paths": [f["path"] for f in files],
                    "source": str(state_dir / "off.sh"), "full_spec_verified": False}
        agents = tuple(args.agents.split(",")) if args.agents else AGENTS
        if not agents or len(set(agents)) != len(agents) or any(agent not in AGENTS for agent in agents):
            raise ConfigureError("--agents must be a comma-separated selection of codex,opencode,pi,claude")
        preflight(agents, environ, which)
        client = Client() if client is None else client
        matches = [row["gateway_url"] for row in discover(client)[0]["connections"]]
        if args.connector:
            matches = [url for url in matches if url.rsplit("/", 1)[1] == args.connector]
        if len(matches) != 1:
            raise ConfigureError("Select exactly one discovered Nebius connector with --connector CONNECTION_ID")
        gateway = matches[0]
        with client.request(gateway + "/models", bearer=PLACEHOLDER) as response:
            models = model_ids(response)
        if args.model is None:
            return {"status": "select_model", "models": models, "certified_combinations": [],
                    "note": "Choose --model explicitly; discovery is not agent compatibility certification",
                    "full_spec_verified": False}
        if args.model not in models or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", args.model):
            raise ConfigureError("Choose an exact, safe model ID from discovery")
        if state:
            assert_owned(home, state)
            if (state.get("agents"), state.get("gateway"), state.get("model")) != (list(agents), gateway, args.model):
                raise ConfigureError("Use --off before changing the connector, agents, or model")
            return {"status": "unchanged", "source": str(state_dir / "env.sh"), "full_spec_verified": False}
        files = plan_files(home, agents, gateway, args.model)
        new_state = {"version": 1, "agents": list(agents), "gateway": gateway, "model": args.model, "files": files}
        active_raw, _ = prepare_transaction(files, new_state, raw_state)
        # A successful setup must also fit its untouched --off journal, which
        # includes the old active state as well as both versions of each file.
        undo_files = [{**row, "before": row["after"], "after": row["before"]}
                      for row in files if not row["path"].endswith("/off.sh")]
        prepare_transaction(undo_files, None, active_raw)
        if not args.dry_run:
            # Private complete originals remain available even after a scoped restore.
            backup_dir = state_dir / "backups"
            if backup_dir.is_symlink():
                raise ConfigureError("Refusing a symlink backup directory")
            backup_dir.mkdir(exist_ok=True, mode=0o700)
            for row in files:
                if row["before"] is not None:
                    name = row["path"].replace("/", "_") + ".original"
                    path = backup_dir / name
                    if not path.exists():
                        atomic_write(path, unpacked(row["before"]))
            transact(home, state_dir, files, new_state)
        return {"status": "dry_run" if args.dry_run else "configured", "agents": agents,
                "paths": [row["path"] for row in files], "source": str(state_dir / "env.sh"),
                "proxy_service": "not_started; see proxy/README.md" if "claude" in agents else "not_selected",
                "full_spec_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--agents", help="Comma-separated installed agents; default: all four")
    parser.add_argument("--connector", help="Connection ID from gateway discovery")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--off", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(configure(args), indent=2))
        return 0
    except (ConfigureError, ProbeError, OSError) as exc:
        # OSError paths can contain sensitive filenames; omit its details.
        detail = "Local filesystem operation failed" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"status": "error", "message": detail, "full_spec_verified": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
