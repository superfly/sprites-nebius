# Installation

The [quickstart](../README.md#get-started) setup scripts offer to install missing
Python dependencies in this checkout's `.venv`, plus the selected agent at the
pinned version below if it is not already on PATH or in our isolated prefix.
Existing agent installations are not upgraded. Installation requires your
confirmation (or `--install`); configuration/service changes require a separate
confirmation (or `--apply`). `--dry-run` never installs anything.

Use a Linux Sprite with Python 3.12+ and `venv`/`pip`. Installing a missing agent
also requires Node.js 22.19.0+ with npm. Setup does not install or upgrade system
runtimes, change your shell profile, or provision a connector. Install only in
an environment you are authorized to change. The lower-level configurator still
uses already installed agents and never installs or updates them itself.

Keep this checkout at its final path before starting the Claude service:
the service records absolute repository and Python paths. Moving either requires
stopping the owned service and recreating it.

## Manual installation

Use these steps instead if you prefer to manage dependencies yourself. Setup
installs only the configurator requirements for non-Claude agents; install both
requirements files below to run the full offline suite.

### Python environment

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

These pins passed the [documented smoke tests](compatibility.md). Upgrades need fresh
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

The setup scripts use `--ignore-scripts` for npm installation, then explicitly
run only the selected OpenCode/Claude binary installer above, after warning you
about its downloads. Installer output is suppressed to avoid logging registry
credentials. If installation fails, no agent configuration is applied; downloads
are retained for inspection. Use the manual steps to diagnose the failure in a
trusted terminal. Restoring configuration with `--off` does not uninstall packages.

Continue with [agent setup](agent-setup.md). Do not log into a direct Nebius
provider account inside the Sprite or put its key in an agent configuration.
