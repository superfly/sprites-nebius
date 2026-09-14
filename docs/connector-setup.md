# Connector setup and validation

This is a gated test procedure, not an installer. Obtain approval before creating
external resources, changing connector policies/Sprite labels, or spending money.
The CLI flags below do not replace that approval. Do not paste credentials into
chat, commit them, or pass them through a Sprite.

## Administrator setup (not automated)

Use the Sprites connector UI/API from a trusted administrator environment:

- Type: **Custom API**, display name `nebius`.
- Base URL: `https://api.tokenfactory.nebius.com/v1`.
- Authentication: header `Authorization`, prefix `Bearer`; store a dedicated
  Nebius key only in the connector. Do not reuse this key elsewhere.
- Access policy: require the `nebius` Sprite label, with `allow_all` unset/false.
- Allowed paths: `/models`, `/chat/completions`, `/responses`, `/responses/*`,
  `/embeddings`. Start narrower if the selected workflow needs fewer endpoints.
- Blocked paths: `/files*`, `/batches*`, `/fine_tuning*`.
- Test endpoint: `/models`.

Endpoint policy editing currently requires the API. See the authoritative
[connector reference](https://sprites.dev/api/connectors). Rules are relative to
the configured upstream base URL: do not add `/v1` to the allowed paths. These
are exact/prefix patterns, not regular expressions. Block rules win. Restrictions
apply to paths, not token spend or model selection.

Use an isolated, explicitly approved test Sprite. Label changes and cleanup are
administrator actions, not something this harness performs.

## Discover and check access

Copy this repository into the approved Sprite without any provider secrets.
From inside that Sprite:

```sh
python3 scripts/verify discover
python3 scripts/verify access \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --expect allowed
```

Replace the URL with the exact `gateway_url` returned by discovery. Never append
another `/v1`. The CLI deliberately rejects other hosts/providers, userinfo,
queries and extra path components. It disables HTTP redirects and inherited
HTTP proxy settings. A misconfigured corporate proxy may therefore need a
different test environment; do not weaken the credential boundary to bypass it.

The allowed probe first requires a successful `/models` response, repeats with
an intentionally invalid placeholder bearer, then checks GET denial for file,
batch and fine-tuning paths. A 403 is a path-denial observation, not by itself
proof of which hop denied it. Correlate gateway logs. GET denial does not claim
that the spec's POST `/files` check V9 has passed. No write-denial POST is sent.

Run the same access command with `--expect outside` from the laptop (expects
401), and with `--expect unlabeled` from a separate approved unlabeled Sprite
(expects 403). These are separate contexts; a single local run cannot prove all
three. Do not fake Fly identity headers.

## Inference and streaming (requires spend approval)

Select an actual model ID from the successful access probe. After explicit
approval for the connector, Sprite and spend:

```sh
python3 scripts/verify --timeout 60 inference \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --model 'MODEL_ID_FROM_DISCOVERY' \
  --max-output-tokens 256 \
  --approve-paid-requests
```

This performs one GET model preflight and at most two POSTs, with no retries.
The requested output limit applies separately to each POST; it is not a dollar
cap or a guarantee of provider billing enforcement. Default is 256; maximum
accepted is 16384. Reasoning models may exhaust a small budget without producing
text. Increase only after checking model pricing and obtaining spend approval.
Responses requests use `store: false`; the harness does not request tools or
execute generated code. Upstream retention remains subject to Nebius policy.

Results record counts, timing and numeric usage only, never model output,
reasoning, raw errors or real keys. Successful SSE termination and nonempty text
are required. A stream needs multiple text deltas spanning at least 50 ms to
report incremental delivery observed. A burst is **inconclusive**, not proof of
a broken endpoint: fast/short outputs may naturally arrive together. Conversely,
network delivery timing alone cannot prove that no buffering exists upstream.
Use a controlled delayed upstream reproduction to establish the cause of #588.

The timeout applies to socket operations and is checked between SSE lines; it
is not a strict total wall-clock deadline. Data is limited to 2 MiB per response
and 128 KiB per SSE line. Redirects, malformed/truncated streams, error events,
and non-SSE inference responses do not count as success.

## Evidence still needed

Record test time, connector ID, Sprite ID and selected model with the results.
An authorized operator must correlate gateway logs for S5. Do not publish those
internal identifiers or log records in an upstream PR without review.

Validate credential isolation from the trusted host; do not copy the actual key
into a Sprite in order to search for it. Agent tool-round-trip tests, the
Claude adapter, POST-denial validation, billing reconciliation and security
sign-off remain separate gates. No complete-spec success is claimed by this CLI.
