# Local Claude Code adapter

This is an **offline-tested spike**, not a completed S6/V8 live acceptance or
security sign-off. It translates text/custom-tool Anthropic Messages requests
to Chat Completions through the configured Sprites Nebius connector. It never
accepts or installs a provider key.

## Install and run after approval

Requires Python 3.12+. Install the reviewed runtime in this directory:

```sh
python3.12 -m venv proxy/.venv
proxy/.venv/bin/python -m pip install -r proxy/requirements.txt
proxy/.venv/bin/python proxy/server.py --config "$HOME/.local/state/sprites-nebius/proxy.json"
```

`scripts/configure` writes the private JSON config. The standalone foreground
command above does not create a Sprite service. Use the separate service
lifecycle helper only when service creation is authorized. Never assign an HTTP
service port, create a public Sprite URL for this listener, or bind it externally.

For a managed service, use the same environment that has both runtime and
configuration dependencies installed (see [agent setup](../docs/agent-setup.md)):

```sh
.venv/bin/python proxy/service.py --start --approve-service-change
.venv/bin/python scripts/configure --off
. "$HOME/.local/state/sprites-nebius/off.sh"
```

The service has a unique name and a private ownership record. Start, stop and
configuration restoration share a lock. Restoration validates unchanged owned
settings, then stops and removes only the matching service definition; runtime
logs remain. An uncertain create is never automatically retried or forgotten.
The launcher uses an empty environment and isolated Python, with only PATH and
HOME supplied. It never sets `--http-port`.

Definition comparison and the runtime's name-based stop/delete API are separate
operations, not an atomic conditional delete. Unique names and local locking
protect normal concurrent setup mistakes; they are not a security boundary
against another privileged Sprite process replacing services concurrently.
Manual service changes cause a conflict requiring operator review.

The config is a flat JSON object of string-valued settings:

- `OPENAI_BASE_URL`: the exact `custom_api` gateway URL from Sprite discovery.
- `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`: both exactly
  `sprites-nebius-placeholder-not-a-secret`.
- `BIG_MODEL`, `MIDDLE_MODEL`, `SMALL_MODEL`: explicitly selected Nebius model IDs.
- `MAX_TOKENS_LIMIT`: default `16384`; accepted range `16384`–`65536`.
- `REQUEST_TIMEOUT`: default `120`, maximum 120 seconds per upstream request.
- Optional `HOST`/`PORT` must be `127.0.0.1`/`8083`; binding is fixed in code.

No `.env` file is loaded or shell expression evaluated. Unknown settings fail
closed. Without `--config`, only those named environment variables are read.
Caller headers, system proxy settings, arbitrary custom headers and credentials
are not forwarded. Only the fixed gateway Chat Completions path is used, with
zero retries and no redirects. Configuring a proxy does not itself authorize
inference; Claude tool loops can make many separately billable requests.

Claude connects to `http://127.0.0.1:8083` with the same placeholder. This is
interoperability configuration, **not a secret or isolation boundary** against
another process already running inside the Sprite.
Its generated settings request at most 16,384 output tokens per call to match
the adapter ceiling, disable the retry watchdog, and set request retries to
zero. That per-request limit is not a session cost cap.

## Supported behavior and limits

- Text output is incremental SSE; tool JSON is buffered until complete and
  valid, then emitted as a serialized Anthropic tool block. Multi-turn client
  tool results preserve the IDs and other text in the same user message.
- The proxy never executes tools. Claude performs the requested file edits and
  tests. Server-side web search, images/documents and Anthropic thinking blocks
  are explicitly rejected; disable Claude thinking for this initial spike.
- Streaming upstream errors become an SSE `error` without `message_stop`; a
  client must not treat HTTP 200 alone as success. Invalid/truncated tool JSON
  does not become an empty tool invocation.
- Completion usage comes from the upstream final usage chunk; absent usage is
  an error, not fabricated billing evidence. `/v1/messages/count_tokens` is only
  a local character-based estimate, marked by `X-Token-Count-Estimate: true`.
  That endpoint cannot establish V10 reconciliation.
- `/health` is local-only and never makes an inference call. There is no
  `/test-connection` spending endpoint. Request/response bodies are not logged;
  safe errors omit provider error bodies.
- Explicit upstream response cleanup runs on cancellation, disconnect, errors
  and EOF. Tests cover cancellation before the first chunk and after a chunk;
  a real gateway/provider cancellation smoke test remains outstanding.

## Provenance and offline checks

`vendor/SOURCE.json` records the exact upstream commit and source files for the
minimal adapted converters. `vendor/LICENSE` retains the upstream MIT notice.
The upstream app, unrestricted configuration and OpenAI SDK transport are not
vendored. Runtime versions are independently pinned, including transitive
dependencies, in `requirements.txt`.

```sh
proxy/.venv/bin/python -m unittest discover -s tests -p 'test_proxy*.py' -v
```

The dependency set was checked with `pip-audit 2.10.1` on 2026-09-16: no known
vulnerabilities reported. This point-in-time advisory check is not proof of
security; rerun it and the offline tests before release. S6 still needs an
approved Sprite service run, compatible model selection and a real multi-turn
Claude Code edit/test task. V8 and launch security review are not complete.
