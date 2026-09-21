# Claude Code adapter

A loopback-only adapter translates Claude Code's text/custom-tool Messages
requests into Chat Completions through a Sprites Nebius connector. It never
accepts or installs a real provider key, and never executes tools itself.
See [tested compatibility](../docs/status.md) for the pinned agent/model checks.

## Install and start

Use Python 3.12+ and the combined environment from
[installation](../docs/installation.md). Normal setup is:

```sh
source scripts/use-nebius on --model 'MODEL_ID_FROM_DISCOVERY' --approve-service-change
source scripts/use-nebius off --approve-service-change
```

For a standalone foreground process after configuration:

```sh
.venv/bin/python proxy/server.py --config "$HOME/.local/state/sprites-nebius/proxy.json"
```

The foreground command does not create a Sprite service. Never expose port 8083
through a public Sprite service/URL or bind it externally.

## Service lifecycle

The sourced helper configures agents, creates the owned service, checks readiness
and only then activates the shell. A service-only diagnostic command is
`.venv/bin/python proxy/service.py --start --approve-service-change`; unlike
the sourced helper, it does not activate exports or roll back configuration.

Start/stop/restoration share a lock. A unique service name and private ownership
record identify the exact service definition; only that definition is removed.
Runtime logs remain. The launcher uses isolated Python and an empty environment
except PATH, HOME and a non-secret source fingerprint; no HTTP service port is set.

Readiness checks the running owned definition and loopback `/health` for at most
ten seconds, with no inference, redirects or inherited HTTP proxies. Another
port-8083 listener is never evicted. The recorded source/requirements fingerprint
must match before reuse; after source changes, explicitly switch off and back on.
This catches stale source, not malicious process replacement or dependency changes.

If a confirmed new service fails readiness, it is removed and newly applied
configuration restored. Existing setups are preserved. Uncertain creation or
cleanup retains recovery state without retry or shell activation; inspect before
retrying. Definition comparison and name-based stop/delete are separate calls,
not an atomic ownership-conditional delete. Local locking protects ordinary
setup concurrency, not hostile privileged processes replacing a service.

## Configuration

The configurator writes a private flat JSON object. Allowed settings are:

| Setting | Value |
| --- | --- |
| `OPENAI_BASE_URL` | Exact discovered `custom_api` gateway URL |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Exactly `sprites-nebius-placeholder-not-a-secret` |
| `BIG_MODEL`, `MIDDLE_MODEL`, `SMALL_MODEL` | Explicitly selected model IDs |
| `MAX_TOKENS_LIMIT` | Default 16384; range 16384–65536 |
| `REQUEST_TIMEOUT` | Default/maximum 120 seconds per upstream request |
| `HOST`, `PORT` | If set, exactly `127.0.0.1`, `8083` |

Without `--config`, only these named environment variables are read. Unknown
settings fail; no dotenv file or shell expressions are loaded. Caller headers,
custom credentials and system proxy settings are not forwarded. Transport uses
only the fixed gateway Chat Completions path, with zero retries and no redirects.

Claude uses the same placeholder at `http://127.0.0.1:8083`; it is not a security
boundary against other processes in the Sprite. Generated settings disable
thinking, request retries and the retry watchdog, and request at most 16384
output tokens per call. That limit does not cap session cost.

## Supported behaviour and limits

- Text streams incrementally; tool JSON is buffered until complete and validated.
  Multi-turn tool results preserve IDs and other text in the same user message.
- Images/documents, server-side web search and Anthropic thinking are rejected.
  Text-only mid-conversation system messages retain role/position and
  `clear_at: next_user_message`; dynamic tool changes and per-message effort
  are rejected.
- Invalid/truncated tool JSON, duplicate IDs, undeclared tools, tool-choice
  violations and tool/finish-reason mismatches fail. Parallel calls must respect
  the caller's `disable_parallel_tool_use` setting. Client permissions remain
  the tool-execution boundary.
- Stream errors emit an SSE error without `message_stop`; HTTP 200 alone does
  not prove completion. Later deltas cannot replace a finished stream.
- Completion usage requires the upstream final usage chunk.
  `/v1/messages/count_tokens` is a character-based estimate marked by
  `X-Token-Count-Estimate: true`, not billing evidence.
- Bodies are bounded to 2 MiB and streaming events to 128 KiB, including framing.
  Parsing is linear with cancellation checkpoints; compressed replies are
  rejected before decoding. This is not a public multi-tenant/quota service.
- `/health` makes no inference call. There is no spending test endpoint.
  Bodies are not logged and errors omit provider response bodies.
- Cancellation, disconnect, errors and EOF close upstream responses.
  Cancellation is covered by offline tests; a live gateway/provider cancellation
  smoke test remains outstanding.

## Provenance and checks

`vendor/SOURCE.json` records the pinned upstream commit and adapted converters;
`vendor/LICENSE` retains their MIT notice. The upstream app and OpenAI SDK
transport are not vendored. Runtime/transitive versions are pinned in
`requirements.txt`.

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_proxy*.py' -v
```

A dependency audit on 16 September 2026 reported no known vulnerabilities.
That is a dated observation, not security sign-off; rerun audits before release.
