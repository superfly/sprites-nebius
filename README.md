# Nebius Token Factory on Fly.io Sprites

Run agents inside Fly.io Sprites with Nebius inference credentials held by a
Sprites Custom API Connector, not inside the sandbox.

**Status: locally implemented setup and adapter; live agent acceptance pending.**
Connector authentication and incremental Chat Completions/Responses streaming
have been observed live. This is not yet a certified four-agent integration.
No real Nebius key belongs in this repository, a Sprite, or a command-line
argument.

## What is implemented

- `scripts/verify discover`: lists visible Custom API connectors targeting the
  exact Token Factory base URL. Run inside the intended Sprite.
- `scripts/verify access`: GET-only checks for model discovery, invalid caller
  bearer handling, and blocked endpoint paths; separate outside-Sprite and
  unlabeled-Sprite modes check expected denial.
- `scripts/verify inference`: explicit opt-in for two capped inference requests
  (Chat Completions and Responses), SSE completion validation and arrival timing.
- `scripts/configure`: installed-agent discovery, explicit connector/model
  selection, dry-run, private backups, comment-preserving edits and `--off`.
- Claude's pinned MIT-derived loopback adapter, hardened transport and explicit
  ownership-checked Sprite service helper. No service starts during configure.
- `scripts/verify acceptance`: offline requirement ledger, exact usage
  reconciliation and host-only leak scanning of separately authorized captures.
- Offline tests, canonical template checks, pinned dependencies and redacted
  Git/current-source secret scanning in CI. Ordinary CI never spends inference.

Start with [agent setup](docs/agent-setup.md), [pinned installation candidates](docs/installation.md)
and the [connector procedure](docs/connector-setup.md). Configure/probe tools do
not create connectors, edit policies, label Sprites, install agents or read keys.
The separate host-only leak scanner reads an explicitly approved private key
file; it never sends the key into a Sprite.

## Local checks (no network or credentials)

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-configure.txt -r proxy/requirements.txt
.venv/bin/python scripts/check
.venv/bin/python scripts/verify --help
.venv/bin/python scripts/verify acceptance --help
```

Probe/configuration CLIs emit `full_spec_verified: false`. Exit 0 means only the
selected operation passed; 1 means a failure or inconclusive result; 2 means
invalid arguments. The evidence ledger can report full coverage only when all
25 requirements have reviewed evidence; it is not a live test runner. See
[acceptance and reconciliation](docs/acceptance.md). Passing mock tests is not
evidence of live agent compatibility. The full runtime needs Python 3.12+;
standalone connector probes remain dependency-free on Python 3.9+.

## Remaining spec gates

The [complete requirement checklist](docs/status.md) tracks all 25 requirements.

| Gate | Still required |
| --- | --- |
| S1–S3 | Authentication/caller-key replacement recorded; both streaming routes observed incrementally on 2026-09-16 with Qwen3-30B-A3B-Instruct-2507 |
| S4 | Full intended policy/path coverage; existing approved test policy remains narrower |
| S5 | Observe connector/Sprite attribution in deployed gateway logs |
| S6 | Pinned/licensed adapter is offline-tested; real service and multi-turn task still required |
| V1, V9 | Host-side credential-isolation review and an explicitly authorized POST-denial test |
| V4–V8 | Gateway Playground and real four-agent smoke tests; no agent/model pair certified yet |
| V10 | Confirm billing source and reconcile usage; probe usage fields alone do not establish this |
| Build completion | Full live-check orchestration, approved capture collection and independent unaided-admin setup trial |
| Launch | Security sign-off, publishing and partnership outreach, with authorization |

The full scope remains the four-agent integration. We are not implementing a
Sprites backend inside Nebius's own sandbox platform or building a managed
inference service. Provider-native functionality, security and streaming tests
must pass before advertising support.

## References

- [Sprites connectors](https://docs.sprites.dev/concepts/connectors/)
- [Nebius API documentation](https://docs.tokenfactory.nebius.com/api-reference/introduction)
- [Nebius Responses API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-a-response)
- [OpenAI SSE event semantics](https://developers.openai.com/api/docs/guides/streaming-responses)

License: Apache-2.0, except the attributed MIT-derived conversion subset in
`proxy/vendor/`. Its exact source commit and adaptations are recorded there.
