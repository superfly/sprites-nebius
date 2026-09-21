# Installation

The configurator uses already installed agents; it never installs or updates
them. Use a Linux Sprite with Python 3.12+, `venv`/`pip`, and Node.js 22.19.0+
with npm. Install only in an environment you are authorized to change.

Keep this checkout at its final path before starting the Claude service:
the service records absolute repository and Python paths. Moving either requires
stopping the owned service and recreating it.

## Python environment

From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-configure.txt -r proxy/requirements.txt
.venv/bin/python scripts/check
```

Installation requires network access. The tests themselves use offline fixtures
and do not spend inference. The standalone gateway probes need only Python 3.9+;
the full toolkit and adapter require Python 3.12+.

## Tested agent versions

These pins passed the [documented smoke tests](status.md). Upgrades need fresh
verification; model discovery alone does not establish agent compatibility.

| Command | Package |
| --- | --- |
| `codex` | `@openai/codex@0.154.0` |
| `opencode` | `opencode-ai@1.18.31` |
| `pi` | `@earendil-works/pi-coding-agent@0.85.1` |
| `claude` | `@anthropic-ai/claude-code@2.1.273` |

Use an isolated prefix to avoid replacing global installations. npm can run
publisher install scripts and download binaries; review those changes first.
The example installs all four; omit packages you do not intend to use.

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

This changes only the current shell's PATH. With npm 12's default script policy,
OpenCode and Claude may install as non-working placeholders. After reviewing
the pinned packages' scripts, run only their binary setup steps:

```sh
node "$HOME/.local/share/sprites-nebius-agents/lib/node_modules/opencode-ai/postinstall.mjs"
node "$HOME/.local/share/sprites-nebius-agents/lib/node_modules/@anthropic-ai/claude-code/install.cjs"
```

Both were needed on the tested Sprite with npm 12.0.2. Do not globally relax
npm's script policy, use `sudo`, or disable required optional dependencies.
Verify executable versions immediately before testing; this toolkit does not
disable every agent's update mechanism.

Continue with [agent setup](agent-setup.md). Do not log into a direct Nebius
provider account inside the Sprite or put its key in an agent configuration.
