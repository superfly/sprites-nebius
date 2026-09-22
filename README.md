# Nebius Token Factory on Fly.io Sprites

Run Codex, OpenCode, Pi and Claude Code inside Fly.io Sprites using Nebius
inference, without putting the Nebius API key in the Sprite.

**Bring your own key:** Nebius bills your Nebius account for inference.
Fly.io bills you separately for Sprite resources.

## Get started

### 1. Connect your Nebius account

Follow the [connector setup guide](docs/connector-setup.md) to
add your Nebius key in **Fly dashboard → Sprites → Connectors → Custom API**.
Grant access to your Sprite using the `nebius` label and the guide's inference-only
path policy. **Keep the key in the connector—never copy it into the Sprite.**
If your administrator has already done this, skip to step 2.

### 2. Set up your chosen agent

Copy this repository into your Sprite and open its directory. All remaining
commands run **inside the Sprite**, not on your laptop. You need Python 3.12+
with `venv`/`pip`; installing a missing agent also needs Node.js 22.19.0+ and npm.
See [installation](docs/installation.md) if these runtimes are missing.

For **Pi**, run:

```sh
./setup-nebius-pi
```

Prefer another agent? Use `./setup-nebius-codex`, `./setup-nebius-opencode`, or
`./setup-nebius-claude` instead—choose one, not all four.

The script offers to install missing dependencies, lets you choose a connector
and model, then shows which files it will change and asks before applying them.
It keeps existing agent installations. Claude setup also starts and checks its
local adapter. **Setup does not send inference or ask for your Nebius key.**

### 3. Start coding

Use the same command with `--launch`:

```sh
./setup-nebius-pi --launch
```

It remembers your selection, checks the configuration, and launches Pi with the
required placeholder environment. Use this launcher in new shells too; setup
does not edit your shell profile. It prints the full command to use from another
project directory. You can also pass `--launch` on the initial setup command.

**Agent use makes billable inference requests.** Model discovery does not prove
compatibility: see the [tested agent/model combinations](docs/compatibility.md).

### Switch back when you're done

```sh
./setup-nebius-pi --off
```

Use your chosen agent's script. It previews and restores the previous
configuration, stopping the Claude adapter if this toolkit started it. Installed
dependencies and private backups are retained. Switch off before selecting a
different agent, connector, or model. For conflicts or multi-agent setup, see
[configuration and recovery](docs/agent-setup.md); do not overwrite the files.

Want a preview? Add `--dry-run` (never installs or changes configuration; missing
dependencies are listed first). Run a setup command with `--help` for explicit
installation/application approvals suitable for unattended use.

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
See [tested compatibility and limitations](docs/compatibility.md) and
[adapter behaviour](proxy/README.md); this is not broad model certification or
independent security sign-off.

## Checks and reference

```sh
.venv/bin/python -m pip install -r requirements-configure.txt -r proxy/requirements.txt
.venv/bin/python scripts/check
.venv/bin/python scripts/verify --help
```

Local checks and CI use offline fixtures and secret scans, not paid inference.
Optional gateway probes require explicit opt-in for billable requests and
write-denial checks; see the connector guide below.

- [Connector setup and individual probes](docs/connector-setup.md)
- [Agent compatibility and limitations](docs/compatibility.md)
- [Nebius API reference](https://docs.tokenfactory.nebius.com/api-reference/introduction)

License: Apache-2.0, except the attributed MIT-derived conversion subset under
`proxy/vendor/`, which retains its source revision and license.
