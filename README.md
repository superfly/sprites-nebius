# Nebius Token Factory on Fly.io Sprites

Run agents inside Fly.io Sprites with Nebius inference credentials held by a
Sprites Custom API Connector, not inside the sandbox.

**Status: local spike harness, not a completed or live-verified integration.**
This first slice prepares connector validation before agent configuration or
proxy vendoring. No real Nebius key belongs in this repository, a Sprite, or a
command-line argument.

## What is implemented

- `scripts/verify discover`: lists visible Custom API connectors targeting the
  exact Token Factory base URL. Run inside the intended Sprite.
- `scripts/verify access`: GET-only checks for model discovery, invalid caller
  bearer handling, and blocked endpoint paths; separate outside-Sprite and
  unlabeled-Sprite modes check expected denial.
- `scripts/verify inference`: explicit opt-in for two capped inference requests
  (Chat Completions and Responses), SSE completion validation and arrival timing.
- Offline tests; no third-party Python dependencies. Requires Python 3.9+.

See [connector setup and test procedure](docs/connector-setup.md). These tools do
not create connectors, edit policies, label Sprites, install agents, or read keys.

## Local checks (no network or credentials)

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify --help
```

The CLI emits JSON with `full_spec_verified: false`. Exit 0 means only the
selected probes passed; 1 means a failure or inconclusive timing result; 2 means
invalid arguments. Passing mock tests is not evidence of live compatibility.

## Remaining spec gates

| Gate | Still required |
| --- | --- |
| S1–S4 | Run the prepared probes on an approved connector and test Sprite |
| S3 | Incremental delivery through the gateway; buffering is tracked in [sprites-api #588](https://github.com/superfly/sprites-api/issues/588) |
| S5 | Observe connector/Sprite attribution in deployed gateway logs |
| S6 | Select/license/review the Claude Code adapter and prove a multi-turn task |
| V1, V9 | Host-side credential-isolation review and an explicitly authorized POST-denial test |
| V5–V8 | Agent configuration/restore tooling and real agent smoke tests |
| V10 | Confirm billing source and reconcile usage; probe usage fields alone do not establish this |
| Launch | Security review, publishing and partnership outreach, with authorization |

The full scope remains the four-agent integration. We are not implementing a
Sprites backend inside Nebius's own sandbox platform or building a managed
inference service. Provider-native functionality, security and streaming tests
must pass before advertising support.

## References

- [Sprites connectors](https://docs.sprites.dev/concepts/connectors/)
- [Nebius API documentation](https://docs.tokenfactory.nebius.com/api-reference/introduction)
- [Nebius Responses API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-a-response)
- [OpenAI SSE event semantics](https://developers.openai.com/api/docs/guides/streaming-responses)

License: Apache-2.0. No third-party proxy code has been vendored.
