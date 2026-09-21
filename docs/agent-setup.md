# Configure and restore agents

Complete [connector setup](connector-setup.md) and [installation](installation.md)
first. Run from the repository root inside the intended Sprite, in Bash or Zsh.
The real Nebius key stays in the connector; the configurator uses
`sprites-nebius-placeholder-not-a-secret`.

## Enable

```sh
.venv/bin/python scripts/verify discover
.venv/bin/python scripts/configure --dry-run
source scripts/use-nebius on --model 'MODEL_ID_FROM_DISCOVERY' --dry-run
source scripts/use-nebius on --model 'MODEL_ID_FROM_DISCOVERY' --approve-service-change
```

Choose an exact model ID from discovery. By default all four agents must be on
PATH; missing executables fail before configuration changes. For a subset, add
`--agents codex,opencode,pi` (or another selection) to the configure/on commands.
With multiple matching connectors, also pass `--connector CONNECTION_ID`.
Discovery proves a model exists, not that it supports an agent's protocol,
reasoning or tools; see [tested compatibility](status.md).

Source the helper in each shell that will launch agents. It writes configuration,
starts/checks the owned Claude service when selected, then exports the placeholder.
It never edits startup files, PATH, shell options or the working directory.
Conflicting/readonly shell variables fail; pre-existing placeholders are not
claimed. Options must be spelled in full.

The service approval flag is needed only when changing the Claude service.
Dry runs do not change files, services or the shell. Setup makes discovery/model
GETs, not inference requests. Run agents only after authorizing their spending;
a short prompt can cause several billable requests.

For configuration-only automation, use `.venv/bin/python scripts/configure`.
It does not manage services unless given `--activate`, and cannot export variables
to its parent shell. The sourced helper is the usual interactive entry point.

## Managed configuration

| Agent | User-level files | Routing |
| --- | --- | --- |
| Codex | `~/.codex/config.toml` | `nebius` provider, Responses API, placeholder environment variable, zero request/stream retries |
| OpenCode | `~/.config/opencode/opencode.json` or existing `.jsonc` | Built-in `nebius` provider's base URL, placeholder key, selected model |
| Pi | `~/.pi/agent/models.json`, `settings.json` | `nebius`, Chat Completions, `$SPRITES_NEBIUS_PLACEHOLDER`, automatic retry disabled |
| Claude | `~/.claude/settings.json` | Loopback adapter, placeholder, explicit model aliases, retries and thinking disabled |

Reference templates are in `templates/`; do not overwrite existing configurations
with them. The configurator preserves unrelated fields/comments and other Pi
models. Codex providers are user-level; Pi's leading `$` denotes an environment
variable rather than a literal key.

Existing provider credentials, custom authentication, symlinks, ambiguous
OpenCode JSON/JSONC files and redirected config paths fail closed. Resolve the
conflict yourself; the tool will not erase a credential or guess the intended file.
Use a shell without `CODEX_HOME`, `OPENCODE_CONFIG*`, `PI_CODING_AGENT_DIR`,
`CLAUDE_CONFIG_DIR` or `XDG_CONFIG_HOME` overrides. Project settings, hooks and
extensions can also override routing; use a clean project for validation.

Configuration and recovery records each have a 2 MiB ceiling; base64 backup
overhead reduces the supported original size. Oversized changes fail before
editing. Select fewer agents or reduce configuration size rather than bypassing
the limit.

## Restore and recover

```sh
source scripts/use-nebius off --dry-run
source scripts/use-nebius off --approve-service-change
```

The helper validates owned settings before changing anything, stops/removes only
the recorded owned service definition, and retains runtime logs. It does not own
arbitrary foreground processes or other services. A service conflict or uncertain
cleanup leaves configuration and shell exports in place for inspection.
See [service lifecycle](../proxy/README.md#service-lifecycle).

Untouched files restore byte-for-byte. Later unrelated edits are preserved;
changes to owned fields/helpers stop restoration with a conflict. Pi's custom
model array is conservatively owned as a whole. Repeat identical setup is
idempotent; switch off before changing model, connector or agent selection.

Private backups and interruption journals live in
`~/.local/state/sprites-nebius/` with owner-only permissions. They may contain
other credentials: never publish them. Recovery proceeds only when files match
the journal's expected before/after states; inspect conflicts and retain backups.
On success, the shell helper removes only exports it introduced and still owns.
The retained `off.sh` can clear that placeholder from another already-open shell
without unsetting a changed or pre-existing value.

## Optional live agent checks

Preview the selected pinned-agent checks, then opt in only for an approved run:

```sh
.venv/bin/python scripts/verify-agents --agents codex,opencode,pi
.venv/bin/python scripts/verify-agents --agents codex,opencode,pi --approve-agent-runs
.venv/bin/python scripts/verify-agents --agents claude --timeout 180 \
  --approve-agent-runs --approve-claude-fixture
```

The runner uses isolated temporary homes and real configurator-written files,
accepts only exact `OK` for the first three agents, never retries, and stops on
the first non-pass. Claude requires a healthy owned adapter and a dedicated test
Sprite. Its restricted fixture allows one arithmetic edit and a fixed test,
rejects other paths/commands/changed tests, and independently checks the result.
It is not a general sandbox for arbitrary code. Six turns and timeouts do not
bound provider request counts or cost. For cross-context checks and key scanning,
use the [host-side suite](verification.md).
