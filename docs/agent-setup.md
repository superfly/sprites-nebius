# Configure agents inside a Sprite

This is an offline-tested setup workflow, **not live four-agent certification**.
The five-minute path below assumes an existing authorized connector, a labeled
Sprite, a reviewed checkout at its final path, its Python environment, and all
selected agents already installed. It excludes administrative setup,
installation, paid validation, and the independent unaided-admin acceptance
test. See [connector setup](connector-setup.md) and [installation](installation.md)
first if those prerequisites are missing.

The real Nebius key belongs only in the connector. Configuration uses the
deliberately harmless `sprites-nebius-placeholder-not-a-secret` value; this is
not a credential or an isolation boundary between processes in the same Sprite.

## Conditional five-minute setup

Run these commands **inside the intended Sprite**, from the repository root.
They read gateway discovery and the model list but do not send inference.

1. Inspect the visible connector and models:

   ```sh
   .venv/bin/python scripts/verify discover
   .venv/bin/python scripts/configure --dry-run
   ```

   By default configure requires `codex`, `opencode`, `pi`, and `claude` on
   `PATH`. If one is missing, it fails before writing agent configurations; it
   does not silently omit the agent or install it. For a deliberate subset,
   add `--agents codex,opencode,pi` (or another comma-separated selection) to
   both discovery/configuration commands that invoke `scripts/configure`.
   With multiple matching Nebius connectors, add
   `--connector CONNECTION_ID`; there is no implicit first-match selection.

2. Copy an exact model ID from the discovery result, review the dry run, then
   apply the same selection:

   ```sh
   .venv/bin/python scripts/configure --model 'MODEL_ID_FROM_DISCOVERY' --dry-run
   .venv/bin/python scripts/configure --model 'MODEL_ID_FROM_DISCOVERY'
   . "$HOME/.local/state/sprites-nebius/env.sh"
   ```

   Replace the example model ID; retain any `--agents` or `--connector` flags
   you selected above. The source step is necessary in each shell that launches
   the native agents: a child configuration process cannot update its parent's
   environment. It exports only `SPRITES_NEBIUS_PLACEHOLDER`, refuses to replace
   another value, and never changes shell startup files. Do not substitute a
   real key. Discovery proves a model exists, not that it supports an agent's
   reasoning, context limits, tools, or wire protocol. Currently the certified
   agent/model matrix is empty.

3. If Claude was selected, start its owned loopback service **only after service
   creation is authorized**:

   ```sh
   .venv/bin/python proxy/service.py --start --approve-service-change
   ```

   Configuration does not start this service automatically. The service uses
   this Python interpreter and the private generated `proxy.json`. It binds
   only `127.0.0.1:8083`; do not add an HTTP service port or expose the listener
   through a public URL. A created or running service is not evidence that
   Claude's multi-turn task passes. See [proxy behavior and limits](../proxy/README.md).

Stop here unless agent execution and its spending are separately authorized.
Agent prompts and tool loops can make several billable requests, even when
their final answer is short. Setup flags do not grant an inference allowance.
Use the [acceptance procedure](acceptance.md) to record genuine V5–V8 evidence,
including independent verification of Claude's file edit and test result.

After fresh approval for native agent inference, dry-plan an explicit selection:

```sh
.venv/bin/python scripts/verify-agents --agents codex,opencode,pi
```

Then add `--approve-agent-runs` only for the approved batch. The runner checks
the pinned executable versions, uses fresh temporary agent homes, disables
tools/plugins where the native CLI supports it, accepts only an exact `OK`,
does not retry, and stops the batch after the first non-pass. A timeout is not a
request or spend cap: a native agent may make more than one provider request.
It deliberately reports Claude V8 as blocked even with the flag; editing and
running agent-written code requires a separate disposable execution scope and
verified confinement. Do not use permission-bypass flags as a substitute.

## What configure owns

| Agent | User-level file | Managed routing |
| --- | --- | --- |
| Codex | `~/.codex/config.toml` | `nebius` provider, Responses wire API, exact discovered gateway, placeholder environment key; request/stream retries set to zero |
| OpenCode | `~/.config/opencode/opencode.json`, or an existing `.jsonc` | Built-in `nebius` provider's `options.baseURL` and placeholder `apiKey`, selected model |
| Pi | `~/.pi/agent/models.json` and `settings.json` | `nebius`, `openai-completions`, `$SPRITES_NEBIUS_PLACEHOLDER`, selected model/default provider; automatic retry disabled |
| Claude Code | `~/.claude/settings.json` | Loopback proxy, placeholder auth, explicit model aliases, request retries and Anthropic thinking disabled |

Readable reference templates are in `templates/`; do not copy them wholesale
over an existing configuration. The configurator merges only owned settings,
preserves unrelated fields and comments, and keeps other configured Pi models.
Codex configuration is user-level, not a project provider block. Pi's leading
`$` is intentional: an unprefixed variable name would be a literal API key.
These mappings follow the current [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-sample),
[OpenCode provider configuration](https://opencode.ai/docs/providers/),
[Pi models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md),
[Pi defaults](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/settings.md),
and [Claude environment reference](https://code.claude.com/docs/en/env-vars).

Existing provider credentials, custom authentication headers/commands, symlinked
configuration paths, ambiguous OpenCode JSON/JSONC files, and redirected config
locations fail closed. Resolve them yourself before retrying; the tool must not
erase a real credential or guess which configuration you intended. Run from a
clean shell without `CODEX_HOME`, `OPENCODE_CONFIG*`, `PI_CODING_AGENT_DIR`,
`CLAUDE_CONFIG_DIR`, or `XDG_CONFIG_HOME` overrides. Custom provider environment
variables and project-local settings may also override user settings. For live
acceptance, inspect those layers and use a clean fixture directory without
project provider overrides, hooks, or unrelated extensions.

## Restore safely

Use the same checkout and user account:

```sh
.venv/bin/python scripts/configure --off --dry-run
.venv/bin/python scripts/configure --off
. "$HOME/.local/state/sprites-nebius/off.sh"
```

`--off` verifies all owned fields before changing anything. It stops and deletes
only the exact service definition recorded by this setup, retaining runtime
logs; arbitrary foreground processes and services created by another method
are not owned. Stop those separately before considering the proxy disabled.
If the owned service cannot be safely verified or stopped, configuration is
left in place and the command fails. Dry run never stops a service.

Untouched files restore exactly. If unrelated fields changed later, restoration
reverses only owned fields and retains those changes. If an owned field or
helper changed, restoration stops with a conflict instead of clobbering it.
The Pi custom-model list is conservatively owned as an array, so later edits to
that list require manual review. Repeating the same setup is idempotent; use
`--off` before changing the connector, agent subset, or model.

Private originals, ownership state, and the interruption journal live beneath
`~/.local/state/sprites-nebius/`; backup files have owner-only permissions. They
may contain unrelated existing credentials from the original configuration, so
never publish or upload this state directory. Interrupted updates recover from
the journal only when files still match the expected before/after versions;
later edits require manual review. Keep backups until restoration is reviewed.

The harmless `off.sh` remains available so already-open shells can remove only
the placeholder value this setup introduced. It does not unset a value changed
by the user or a pre-existing placeholder. No startup files or real credential
variables are rewritten. Neither successful configuration nor successful
restoration sets `full_spec_verified` to true.
