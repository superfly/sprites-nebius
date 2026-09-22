# Configure and restore agents

For one agent, start with the [setup scripts](../README.md#get-started):

```sh
./setup-nebius-pi
./setup-nebius-pi --launch
./setup-nebius-pi --off
```

Substitute `codex`, `opencode` or `claude` for `pi`. They share the configurator
below, including its ownership checks and rollback. Repeat setup reuses your
saved selection; `--launch` exports the placeholder only to the agent process
and preserves your current working directory. No shell startup files change.
Project settings, hooks and extensions can still override user-level routing.

Use `--dry-run` for a read-only preview. On a fresh checkout without dependencies,
it lists the installs needed before a full configuration preview is possible.
For noninteractive setup, select `--model MODEL_ID` and, if ambiguous,
`--connector CONNECTION_ID`. `--install` approves missing-dependency downloads;
`--apply` separately approves configuration and owned service changes. Neither
flag launches an agent: only `--launch` does that, with billable inference.
Changing an active agent/model/connector selection requires `--off` first.

## Advanced: sourced activation and multiple agents

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
reasoning or tools; see [tested compatibility](compatibility.md).

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
to its parent shell. Use the sourced helper when you want to launch plain agent
commands from your current shell, or configure multiple agents together. A
multi-agent configuration must be restored with this helper, not a single-agent
setup script.

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
