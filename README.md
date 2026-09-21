# Nebius Token Factory on Fly.io Sprites

Run Codex, OpenCode, Pi and Claude Code inside Fly.io Sprites using Nebius
inference, without putting the Nebius API key in the Sprite.

A [Sprites Custom API connector](https://docs.sprites.dev/concepts/connectors/)
holds your key, authorizes Sprites by label, and forwards inference requests.
This toolkit configures the agents and provides a local Claude Code adapter;
it does not implement the gateway or a managed Nebius service.

**Bring your own key:** Nebius bills your Nebius account for inference.
Fly.io bills you separately for Sprite resources.

## Quickstart

You need a Linux Sprite, Python 3.12+, an authorized Nebius connector and the
agents you want to use. Follow [connector setup](docs/connector-setup.md) and
[installation](docs/installation.md) first. The commands below run inside the
Sprite from this checkout, in Bash or Zsh.

1. Discover available connectors and models:

   ```sh
   .venv/bin/python scripts/verify discover
   .venv/bin/python scripts/configure --dry-run
   ```

2. Choose an exact model ID from discovery, preview the changes, then enable:

   ```sh
   source scripts/use-nebius on --model 'MODEL_ID_FROM_DISCOVERY' --dry-run
   source scripts/use-nebius on --model 'MODEL_ID_FROM_DISCOVERY' --approve-service-change
   ```

   This configures all four installed agents and starts the loopback Claude
   adapter. For a subset, add `--agents codex,opencode,pi` to both configure and
   on commands; no service approval is needed without Claude. If discovery finds
   multiple connectors, add `--connector CONNECTION_ID` to those commands.

3. Run your selected agent normally. Its inference is billable. To restore the
   previous configuration:

   ```sh
   source scripts/use-nebius off --approve-service-change
   ```

Setup reads discovery/model lists but does not send inference. It does not
install agents, create connectors or change policies/labels. See
[configuration and recovery](docs/agent-setup.md) for ownership and conflicts.

## Security and compatibility

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
