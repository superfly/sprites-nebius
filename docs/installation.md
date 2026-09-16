# Install candidate runtimes

`scripts/configure` configures **already installed** agents. It never installs,
updates, or launches them. Package installation and Sprite service creation are
separate, explicit operations; obtain authorization before doing either on a
shared or live Sprite. No inference is necessary for installation.

## Prerequisites

Use a Linux Sprite with Python 3.12+, `venv`/`pip`, and Node.js **22.19.0 or
later** with npm. That Node minimum covers the declared requirements of all four
candidate packages below. Place the reviewed repository at its intended final
path before creating a service: the service records absolute repository and
Python paths. Moving the checkout or its virtual environment afterward requires
stopping the owned service and explicitly recreating it.

From the repository root, prepare a private, repository-local Python runtime:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-configure.txt -r proxy/requirements.txt
.venv/bin/python scripts/check
```

These requirements pin the configurator's comment-preserving TOML dependency
and the proxy's runtime dependencies. Ordinary checks use mocks and local HTTP
fixtures, not paid inference. Installing dependencies requires network access;
do not describe the installation itself as an offline operation. The simpler
gateway probe can still run independently without those third-party packages.

## Exact candidate agent versions

The official npm registry returned these versions on **16 September 2026**.
They are reproducible **candidate pins**, not a certified compatibility matrix.
None has completed this integration's V5–V8 acceptance through the live
connector. Keep the tested version, model, and repository revision in each
eventual acceptance record; an upgrade needs new verification.

| Agent command | Package and candidate pin | Registry metadata |
| --- | --- | --- |
| `codex` | `@openai/codex@0.154.0` | [Exact release](https://registry.npmjs.org/@openai%2Fcodex/0.154.0) |
| `opencode` | `opencode-ai@1.18.31` | [Exact release](https://registry.npmjs.org/opencode-ai/1.18.31) |
| `pi` | `@earendil-works/pi-coding-agent@0.85.1` | [Exact release](https://registry.npmjs.org/@earendil-works%2Fpi-coding-agent/0.85.1) |
| `claude` | `@anthropic-ai/claude-code@2.1.273` | [Exact release](https://registry.npmjs.org/@anthropic-ai%2Fclaude-code/2.1.273) |

After approval, an isolated npm prefix avoids replacing existing global agent
installations. Install only the agents you intend to select; the example below
installs all four. npm may execute the publishers' installation scripts and
download platform-specific binaries. Do not use `sudo`, disable optional
dependencies, or copy a provider key into the install environment.

```sh
npm install --global --prefix "$HOME/.local/share/sprites-nebius-agents" \
  @openai/codex@0.154.0 \
  opencode-ai@1.18.31 \
  @earendil-works/pi-coding-agent@0.85.1 \
  @anthropic-ai/claude-code@2.1.273

export PATH="$HOME/.local/share/sprites-nebius-agents/bin:$PATH"
codex --version
opencode --version
pi --version
claude --version
```

This changes `PATH` only in the current shell; it does not edit startup files.
Record the actual reported versions. Ensure later shells and your acceptance
runner resolve these same executables. Do not use unpinned `latest` updates
during a controlled validation batch. This repository does not disable every
agent's own update mechanism; verify versions again immediately before testing.

The package names are documented by [OpenAI](https://learn.chatgpt.com/docs/codex/cli),
[OpenCode](https://opencode.ai/docs/), [Pi](https://pi.dev/news/2026/5/7/pi-has-a-new-home),
and [Claude Code](https://code.claude.com/docs/en/setup). Pi's current package
scope is `@earendil-works`, not the older `@mariozechner` scope. Claude's npm
package uses platform-specific optional dependencies; its installed binary does
not itself run under Node.

Proceed to [agent setup](agent-setup.md) only after the connector is configured
and the chosen installed commands are available on `PATH`. Do not log into a
direct Nebius provider account inside the Sprite or paste its key into an agent.
