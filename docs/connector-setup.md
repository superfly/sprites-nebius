# Connector setup and gateway checks

An organization administrator creates the connector from a trusted host.
Keep both the Sprites API token and Nebius key out of the Sprite and repository.
Authorize resource/policy changes and paid probes before running them.

## Create the connector

In the Fly dashboard, open **Sprites → Connectors → Custom API**:

| Setting | Value |
| --- | --- |
| Name | `nebius` |
| Base URL | `https://api.tokenfactory.nebius.com/v1` |
| Authentication | Header `Authorization`, prefix `Bearer` |
| Key | Dedicated Nebius Token Factory key, stored only in the connector |
| Access | Require Sprite label `nebius`; leave `allow_all` false |
| Test URL | `https://api.tokenfactory.nebius.com/v1/models` (full upstream URL) |

Endpoint restrictions require the API. The [connector reference](https://sprites.dev/api/connectors)
describes exact/prefix matching; rules are relative to the upstream base URL,
so do not add `/v1`. Block rules win. Paths do not restrict models or token spend.

From a trusted host, use these routes relative to `https://api.sprites.dev`
with an organization-authorized Sprites bearer token:

| Purpose | Method/path | Body |
| --- | --- | --- |
| Read connector | `GET /v1/oauth/connections/CONNECTION_ID` | None |
| Create Custom API | `POST /v1/oauth/connections/custom_api` | Required `name`, `base_api_url`, `access_token`, `test_url`; optional `description`, `auth_method: "header"`, `auth_header_prefix: "Bearer"`, `access_policy` |
| Update settings/key | `PUT /v1/oauth/connections/custom_api/CONNECTION_ID` | Changed settings; **not access policy** |
| Replace policy | `PUT /v1/oauth/connections/CONNECTION_ID` | `{"access_policy": {...}}` |
| Read labels | `GET /v1/sprites/SPRITE_NAME` | None |
| Replace labels | `PUT /v1/sprites/SPRITE_NAME` | `{"labels": ["existing-label", "nebius"]}` |

Policy and label updates **replace**, not merge. Read and privately back up
existing values first; preserve other labels and deliberate restrictions.
A policy for the intended inference routes is:

```json
{
  "access_policy": {
    "allow_all": false,
    "sprite_labels": ["nebius"],
    "allowed_endpoints": ["/models", "/chat/completions", "/responses", "/responses/*", "/embeddings"],
    "blocked_endpoints": ["/files*", "/batches*", "/fine_tuning*"]
  }
}
```

All listed labels are required; an existing `name_prefix` further restricts
access. Do not widen existing access just to make a check pass. The dashboard
preserves endpoint restrictions when editing labels/prefixes, but cannot edit
the endpoint lists. Read back the complete policy and labels after changing them.

Keep authentication config, key-containing JSON and responses in owner-only host
files (`umask 077`, mode `0600`). Use a credential-aware client or
`curl --config /private/auth.conf --data-binary @/private/request.json`;
never inline tokens in arguments. Build JSON with a serializer, not shell
interpolation. Avoid redirects, verbose tracing, `set -x` and environment dumps.
Creation returns HTTP 201 with `connection`; updates return HTTP 200.
Sanitized readback exposes settings/policy, not the key. Rotate keys through the
settings route, never the policy route.

## Test the connection

On the connector detail page, select **Test** beside the intended Sprite under
**Authorized Sprites** (also available on the Sprite's Connectors tab).
This calls `POST /v1/oauth/connections/CONNECTION_ID/test_gateway` with
`{"sprite_name":"SPRITE_NAME"}`, temporarily creates a test token and executes
the gateway request inside the Sprite. Require `result.status: "ok"` and an
upstream success; HTTP 200 alone is insufficient.

The Custom API form's credential Test runs from the control plane, not the
Sprite. Neither generic Test success nor the development-only Playground is
silently substituted for a validated model-list response. See
[verification evidence](verification.md#v4-and-v10-explicit-operator-evidence).

Inside the labeled Sprite:

```sh
python3 scripts/verify discover
python3 scripts/verify access \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --expect allowed
```

Discovery lists visible Nebius connectors; use the exact returned gateway URL.
Access checks model discovery, replacement of an invalid caller bearer, and
GET denials for files/batches/fine-tuning. It sends no inference or write POSTs.
Run access separately from a laptop with `--expect outside` (401), and from an
authorized unlabeled test Sprite with `--expect unlabeled` (403).
Do not fabricate Fly identity headers.

## Optional paid and write-denial probes

The flags below are explicit opt-ins, not grants of authority. First authorize
the exact connector, Sprite and operation. For two streaming requests:

```sh
python3 scripts/verify --timeout 60 inference \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --model 'MODEL_ID_FROM_DISCOVERY' --max-output-tokens 256 \
  --approve-paid-requests
```

This makes one model GET and at most two inference POSTs, without retries.
The output limit is per POST, not a cost cap; reasoning models may exhaust it
without text. Responses uses `store: false`, but provider retention remains
subject to Nebius policy. No generated code or tools are executed.

SSE completion and nonempty text are required. Incremental delivery requires
multiple text deltas spanning at least 50 ms; a burst is inconclusive, not proof
of buffering. Output contains timing, numeric usage and provenance, not model
text or raw errors. Request deadlines cover headers/body; limits are 2 MiB per
response and 128 KiB per SSE line. Redirects, error events, malformed/truncated
streams and JSON-only inference responses cannot pass. Standalone deadlines
require a POSIX main thread with no existing real-time timer.

For the policy's POST denial check:

```sh
python3 scripts/verify write-denial \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --approve-write-denial
```

After a model-list preflight, this sends one empty JSON POST to `/files`.
A broken policy could dispatch upstream, so authorize this separately from GET
checks. Passing requires 403 and the precise gateway policy error; generic
authentication/provider errors are not a pass. No files are uploaded or retries
made. Independent no-dispatch tracing is optional additional assurance.

For an orchestrated run, use [coordinated verification](verification.md).
For BYOK accounting and the current staff-assisted gateway export limitation,
see [usage reconciliation](acceptance.md#usage-reconciliation).
