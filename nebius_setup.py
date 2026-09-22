"""Interactive, single-agent onboarding. No provider key or inference probes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import nebius_configure as config
from nebius_verify import Client, PLACEHOLDER, ProbeError, discover, gateway_url, model_ids

ROOT = Path(__file__).resolve().parent
PACKAGES = {
    "codex": "@openai/codex@0.154.0",
    "opencode": "opencode-ai@1.18.31",
    "pi": "@earendil-works/pi-coding-agent@0.85.1",
    "claude": "@anthropic-ai/claude-code@2.1.273",
}
BINARY_INSTALLERS = {
    "opencode": "opencode-ai/postinstall.mjs",
    "claude": "@anthropic-ai/claude-code/install.cjs",
}


def confirm(message, approved=False):
    if approved:
        return
    if not sys.stdin.isatty():
        raise config.ConfigureError(message + " Rerun interactively or supply the stated approval flag.")
    if input(message + " [y/N] ").strip().lower() not in ("y", "yes"):
        raise config.ConfigureError("Cancelled; no further changes made")


def choose(label, choices, selected=None):
    if selected is not None:
        if selected not in choices:
            raise config.ConfigureError("Selected " + label + " is not available; run setup without that selection")
        return selected
    if not choices:
        raise config.ConfigureError("No available " + label + "; check docs/connector-setup.md")
    if label == "connector" and len(choices) == 1:
        return choices[0]
    for index, value in enumerate(choices, 1):
        print(f"  {index}. {value}")
    if not sys.stdin.isatty():
        raise config.ConfigureError("Choose --" + label + " explicitly, or rerun interactively")
    selection = input("Choose a " + label + " number: ").strip()
    if (len(selection) > 10 or not selection.isascii() or not selection.isdigit()
            or not 1 <= int(selection) <= len(choices)):
        raise config.ConfigureError("Invalid selection; rerun setup to choose again")
    return choices[int(selection) - 1]


def run_install(command, *, cwd=None):
    # Installers may echo registry credentials in errors. Do not retain/log output.
    result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=600)
    if result.returncode:
        raise config.ConfigureError("Dependency installation failed; no agent configuration applied. "
                                    "See docs/installation.md; existing downloads are retained.")


def requirements(agent):
    paths = [ROOT / "requirements-configure.txt"]
    if agent == "claude":
        paths.append(ROOT / "proxy/requirements.txt")
    pins = [line.strip() for path in paths for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    return paths, pins


def prepare_runtime(args, home):
    """Offer isolated installs; dry runs never create files or launch installers."""
    prefix = config.safe_path(home, ".local/share/sprites-nebius-agents")
    # Existing PATH installations win. Add our isolated prefix only in this process.
    os.environ["PATH"] = os.environ.get("PATH", os.defpath) + os.pathsep + str(prefix / "bin")
    executable = shutil.which(args.agent) if not args.off else "not needed for restoration"
    if executable and not args.off and not args.dry_run:
        check = subprocess.run([executable, "--version"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
        if check.returncode:
            raise config.ConfigureError("Existing agent cannot run; repair it manually. No installation replaced.")
    venv = ROOT / ".venv"
    if venv.is_symlink():
        raise config.ConfigureError("Refusing a symlinked .venv; see docs/installation.md")
    python = venv / "bin/python"
    paths, pins = requirements(args.agent)
    ready = False
    if venv.exists():
        check = subprocess.run([str(python), "-B", "-c",
                                "import sys; sys.exit(sys.version_info < (3, 12))"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if check.returncode:
            raise config.ConfigureError("Existing .venv needs Python 3.12+; repair it manually")
        check = subprocess.run([str(python), "-B", "-c",
                                "from importlib.metadata import version; import sys; "
                                "sys.exit(any(version(p.split('==')[0]) != p.split('==')[1] for p in sys.argv[1:]))",
                                *pins], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        ready = check.returncode == 0
    if not ready or executable is None:
        print("Dependencies needed (isolated installs; no system runtime changes):")
        if not ready:
            print("  Repository .venv: " + ", ".join(path.relative_to(ROOT).as_posix() for path in paths))
        if executable is None:
            print("  " + PACKAGES[args.agent] + " in " + str(prefix))
            if args.agent in BINARY_INSTALLERS:
                print("  Its pinned publisher binary installer will also run and download a binary.")
        if args.dry_run:
            print("Preview only. Install the missing dependencies before previewing configuration; "
                  "rerun without --dry-run to be prompted.")
            return False
        if executable is None:
            node, npm = shutil.which("node"), shutil.which("npm")
            if not node or not npm:
                raise config.ConfigureError("Install Node.js 22.19.0+ and npm first; see docs/installation.md")
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
            match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", version.stdout)
            if version.returncode or not match or tuple(map(int, match.groups())) < (22, 19, 0):
                raise config.ConfigureError("Node.js 22.19.0+ is required; existing runtime left unchanged")
        confirm("Install these dependencies? (--install approves this step)", args.install)
        if not ready:
            print("Installing Python dependencies in .venv; this may take a few minutes.", flush=True)
            if not venv.exists():
                run_install([sys.executable, "-m", "venv", str(venv)])
            command = [str(python), "-m", "pip", "install", "--only-binary=:all:"]
            for path in paths:
                command += ["-r", str(path)]
            run_install(command)
        if executable is None:
            print("Installing " + PACKAGES[args.agent] + "; this may take a few minutes.", flush=True)
            run_install([npm, "install", "--global", "--prefix", str(prefix), "--ignore-scripts",
                         "--no-audit", "--no-fund", PACKAGES[args.agent]])
            if args.agent in BINARY_INSTALLERS:
                installer = prefix / "lib/node_modules" / BINARY_INSTALLERS[args.agent]
                run_install([node, str(installer)], cwd=installer.parent)
            executable = shutil.which(args.agent)
            if executable is None:
                raise config.ConfigureError("Installed agent is not executable; see docs/installation.md")
            version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
            expected = PACKAGES[args.agent].rsplit("@", 1)[1]
            if version.returncode or not re.search(r"(?<![\w.])" + re.escape(expected) + r"(?![\w.])", version.stdout):
                raise config.ConfigureError("Installed agent version check failed; configuration not applied")
    # The configurator (and Claude service) must use the repository environment.
    if Path(sys.prefix).resolve() != venv.resolve():
        os.execv(str(python), [str(python), "-B", str(ROOT / "nebius_setup.py"), *sys.argv[1:]])
    return True


def saved_selection(home, agent):
    raw = config.read_file(config.safe_path(home, config.STATE + "/active.json"))
    if raw is None:
        return None
    try:
        state = json.loads(raw)
        if state["version"] != 1 or not isinstance(state["files"], list):
            raise ValueError
        if state["agents"] != [agent]:
            raise config.ConfigureError("Another agent selection is active. Use scripts/use-nebius off "
                                        "before switching; setup will not replace it.")
        gateway_url(state["gateway"])
        if not isinstance(state["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", state["model"]):
            raise ValueError
        return state
    except (ValueError, KeyError, TypeError, argparse.ArgumentTypeError):
        raise config.ConfigureError("Invalid ownership state; see docs/agent-setup.md for recovery") from None


def setup(args, *, client=None, inside_sprite=None):
    if inside_sprite is None:
        inside_sprite = Path("/.sprite").is_dir()
    if not inside_sprite:
        raise config.ConfigureError("Run setup inside the intended Sprite, not on your laptop")
    if not os.environ.get("HOME", "").startswith("/"):
        raise config.ConfigureError("An absolute HOME is required")
    home = Path.home()
    state = saved_selection(home, args.agent)
    if not args.off:
        # Check environment conflicts before offering downloads or mutating anything.
        config.preflight((args.agent,), os.environ, lambda _: "checked after bootstrap")
        if config.read_file(config.safe_path(home, config.STATE + "/pending.json")) is not None:
            raise config.ConfigureError("Interrupted setup needs recovery; see docs/agent-setup.md")
    if not prepare_runtime(args, home):
        return
    options = argparse.Namespace(agents=args.agent, model=args.model, connector=args.connector,
                                 off=args.off, dry_run=True, activate=True, approve_service_change=False)
    if not args.off:
        client = Client() if client is None else client
        connectors = sorted({row["gateway_url"].rsplit("/", 1)[1]
                             for row in discover(client)[0]["connections"]})
        options.connector = choose("connector", connectors, args.connector or
                                   (state["gateway"].rsplit("/", 1)[1] if state else None))
        gateway = "https://api.sprites.dev/v1/gateway/custom_api/" + options.connector
        with client.request(gateway + "/models", bearer=PLACEHOLDER) as response:
            # Provider-controlled strings must not inject terminal escapes or config.
            models = [model for model in model_ids(response)
                      if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", model)]
        print("Choose a model compatible with your agent; availability is not compatibility certification.")
        options.model = choose("model", models, args.model or (state["model"] if state else None))
        print(f"Agent: {args.agent}\nConnector: {options.connector}\nModel: {options.model}")
    preview = config.configure(options, client=client, inside_sprite=inside_sprite)
    for path in preview.get("paths", []):
        print("  " + str(home / path))
    if args.agent == "claude":
        print("Owned Claude adapter: " + ("stop" if args.off else "start and health-check") + " (127.0.0.1:8083).")
    if args.dry_run:
        print("Preview only; no configuration or service changes.")
        return
    if preview["status"] not in ("unchanged", "already_off") or args.agent == "claude":
        confirm("Apply these configuration/service changes? (--apply approves this step)", args.apply)
    options.dry_run = False
    options.approve_service_change = args.apply or args.agent == "claude"
    result = config.configure(options, client=client, inside_sprite=inside_sprite)
    if args.off:
        print("Nebius configuration restored. Installed dependencies and private backups are retained.")
        return
    print("Nebius is ready. Setup made no inference requests.")
    launcher = shlex.quote(str(ROOT / ("setup-nebius-" + args.agent)))
    print("Launch now or from another project directory: " + launcher + " --launch")
    print("Restore previous configuration: " + launcher + " --off")
    if args.launch:
        print("Launching the agent; its inference is billable. Project settings/hooks can override routing.", flush=True)
        # Fixed placeholder semantics, never source mutable generated shell helpers.
        environ = dict(os.environ, **{config.ENV_KEY: PLACEHOLDER})
        executable = shutil.which(args.agent)
        if executable is None:
            raise config.ConfigureError("Agent executable disappeared; configuration retained, agent not launched")
        os.execve(executable, [executable], environ)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("agent", choices=config.AGENTS)
    parser.add_argument("--connector", help="Connection ID; otherwise select from discovery")
    parser.add_argument("--model", help="Exact model ID; otherwise select interactively")
    parser.add_argument("--install", action="store_true", help="Approve isolated missing-dependency installs")
    parser.add_argument("--apply", action="store_true", help="Approve configuration and owned Claude service changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; never install, configure, or launch")
    parser.add_argument("--launch", action="store_true", help="Launch the agent with its placeholder environment (billable use)")
    parser.add_argument("--off", action="store_true", help="Restore this agent's previous configuration; retain dependencies")
    args = parser.parse_args(argv)
    if args.launch and (args.dry_run or args.off):
        parser.error("--launch cannot be combined with --dry-run or --off")
    if args.off and (args.model or args.connector):
        parser.error("--off does not accept model or connector selections")
    try:
        setup(args)
        return 0
    except (config.ConfigureError, ProbeError, OSError, subprocess.SubprocessError, EOFError, KeyboardInterrupt) as exc:
        detail = str(exc) if isinstance(exc, (config.ConfigureError, ProbeError)) else "Setup interrupted or local operation failed; no automatic retry"
        print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
