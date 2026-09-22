# Contributing

Keep changes focused on user-visible behavior. Search existing issues first,
include agent/toolkit versions in bug reports, and remove credentials and private
data. Report vulnerabilities through [SECURITY.md](SECURITY.md), not public issues.
General platform support belongs in the [Fly.io community](https://community.fly.io/).

## Local checks

Use Python 3.12+ and the [manual installation steps](docs/installation.md#python-environment), then run:

```sh
.venv/bin/python scripts/check
git diff --check
```

The tests use offline fixtures, including localhost HTTP servers. They need no
Sprite credentials, agent installations or paid inference. Live tests are optional
and require explicit authorization for the resources and spending involved.

Preserve existing configuration, credential isolation, service ownership and
opt-in boundaries. Add focused regression tests for changed behavior and update
the relevant user guide. Never commit provider keys or private validation captures.
