# Nebius Token Factory on Fly.io Sprites

Run Codex, OpenCode, Pi and Claude Code inside Fly.io Sprites using Nebius
inference, without putting the Nebius API key in the Sprite.

**Bring your own key:** Nebius bills your Nebius account for inference.
Fly.io bills you separately for Sprite resources.

## Get started

### 1. Connect your Nebius account

On your laptop, follow the [connector setup guide](docs/connector-setup.md) to
add your Nebius key in **Fly dashboard → Sprites → Connectors → Custom API**.
Grant access to your Sprite using the `nebius` label and the guide's inference-only
path policy. **Keep the key in the connector—never copy it into the Sprite.**
If your administrator has already done this, skip to step 2.

### 2. Prepare your Sprite

Copy this repository into your Sprite and open its directory in **Bash or Zsh**.
All remaining commands run there, not on your laptop. You need Python 3.12+ and
at least one [installed agent](docs/installation.md#tested-agent-versions) on PATH.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-configure.txt -r proxy/requirements.txt
```

### 3. Choose your agent and model

This example uses **Codex**. Set `NEBIUS_AGENTS` to `opencode`, `pi`, `claude`,
or a comma-separated list to configure other installed agents.

```sh
NEBIUS_AGENTS=codex
.venv/bin/python scripts/verify discover
.venv/bin/python scripts/configure --agents "$NEBIUS_AGENTS" --dry-run
```

The last command lists available model IDs without changing your configuration.
If you have multiple Nebius connectors, add `--connector CONNECTION_ID` to that
command and both `on` commands below; use the ID at the end of its discovered URL.

### 4. Preview the changes, then enable Nebius

Replace the model placeholder with an exact ID from step 3, then preview:

```sh
NEBIUS_MODEL='MODEL_ID_FROM_LIST'
source scripts/use-nebius on --agents "$NEBIUS_AGENTS" --model "$NEBIUS_MODEL" --dry-run
```

Review the files it will change. If the preview looks right, enable Nebius:

```sh
source scripts/use-nebius on --agents "$NEBIUS_AGENTS" --model "$NEBIUS_MODEL" --approve-service-change
```

Selecting Claude also starts its local adapter; the approval flag permits that
service change and is unnecessary for other agents. Setup reads model lists but
does not send inference. In a new shell, repeat steps 3–4 with the same selection
to activate it there too.

### 5. Start coding

Launch the agent you selected—for the example above:

```sh
codex
```

Use `opencode`, `pi` or `claude` instead if you selected one of those.
**Agent use makes billable inference requests.** See the
[tested agent/model combinations](docs/status.md) before choosing another model.

### Switch back when you're done

```sh
source scripts/use-nebius off --approve-service-change
```

This restores the previous configuration and stops the Claude adapter if this
toolkit started it. If you hit a configuration conflict, see
[configuration and recovery](docs/agent-setup.md); do not overwrite the files.

## Security and compatibility

This toolkit uses an existing [Sprites Custom API connector](https://docs.sprites.dev/concepts/connectors/);
it does not provision a connector or implement the gateway or a managed inference service.

- Keep the real Nebius key in the connector, never in the Sprite or this repo.
  Agent configuration uses a harmless placeholder; it is not an authentication
  boundary between processes inside one Sprite.
- Grant access only to intended Sprite labels and inference paths.
- The Claude adapter binds to `127.0.0.1:8083`. Never expose it as a public
  service. It translates requests; Claude, not the adapter, executes tools.
- Review dry runs before editing existing configuration. Private backups may
  contain other credentials and must not be published.
- Native agents can make multiple paid requests; timeouts are not spending caps.

All four pinned agents passed scoped live checks with one model.
See [tested compatibility and limitations](docs/status.md) and
[adapter behaviour](proxy/README.md); this is not broad model certification or
independent security sign-off.

## Checks and reference

```sh
.venv/bin/python scripts/check
.venv/bin/python scripts/verify --help
```

Local checks and CI use offline fixtures and secret scans, not paid inference.
Live checks require explicit opt-in; a successful probe is not full acceptance.

- [Connector setup and individual probes](docs/connector-setup.md)
- [Coordinated live verification](docs/verification.md)
- [Usage reconciliation and evidence formats](docs/acceptance.md)
- [Nebius API reference](https://docs.tokenfactory.nebius.com/api-reference/introduction)

License: Apache-2.0, except the attributed MIT-derived conversion subset under
`proxy/vendor/`, which retains its source revision and license.
