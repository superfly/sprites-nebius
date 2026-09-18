# Connector setup and validation

This is a gated test procedure, not an installer. Obtain approval before creating
external resources, changing connector policies/Sprite labels, or spending money.
The CLI flags below do not replace that approval. Do not paste credentials into
chat, commit them, or pass them through a Sprite.

## Administrator setup (host only, not automated)

Use the Fly dashboard's **Sprites → Connectors → Custom API** form, or the
token-authenticated API from a trusted administrator host. The Sprites API token
and Nebius key are different credentials. Neither belongs in the test Sprite.
Prefer entering the Nebius key directly into the connector form from your
approved credential store; do not include it in screenshots or acceptance output.

- Type: **Custom API**, display name `nebius`.
- Base URL: `https://api.tokenfactory.nebius.com/v1`.
- Authentication: header `Authorization`, prefix `Bearer`; store a dedicated
  Nebius key only in the connector. Do not reuse this key elsewhere.
- Access policy: require the `nebius` Sprite label, with `allow_all` unset/false.
- Allowed paths for the full S4 policy: `/models`, `/chat/completions`,
  `/responses`, `/responses/*`, `/embeddings`. A deliberately narrower test
  policy is useful for isolation but does not establish full S4 coverage.
- Blocked paths: `/files*`, `/batches*`, `/fine_tuning*`.
- Test URL field: **`https://api.tokenfactory.nebius.com/v1/models`** (the full
  upstream URL, not the relative gateway path).

Endpoint policy editing currently requires the API. See the authoritative
[connector reference](https://sprites.dev/api/connectors). Rules are relative to
the configured upstream base URL: do not add `/v1` to the allowed paths. These
are exact/prefix patterns, not regular expressions. Block rules win. Restrictions
apply to paths, not token spend or model selection.

### API fields and safe readback

The following routes are verified against sprites-api main
[`ce7dadb5`](https://github.com/superfly/sprites-api/blob/ce7dadb5a1857348df456289434a184b9bd83652/lib/sprites_web/router.ex#L714)
and ui-ex main
[`c08b752f`](https://github.com/superfly/ui-ex/blob/c08b752ff8a7f14743fe0be8c1563b26e990db86/lib/fly/stripe_projects/sprites_client.ex#L1646).
This is source verification, not a claim about the currently deployed revision.
All paths below are relative to `https://api.sprites.dev`; requests use a host-only
Sprites bearer token with the necessary organization access.

| Purpose | Method and path | JSON body |
| --- | --- | --- |
| Read an existing connector | `GET /v1/oauth/connections/CONNECTION_ID` | None |
| Create Custom API | `POST /v1/oauth/connections/custom_api` | Required nonempty strings `name`, `base_api_url`, `access_token`, `test_url`; optional `description`, `auth_method: "header"`, `auth_header_prefix: "Bearer"`, `access_policy` |
| Update Custom API settings/key | `PUT /v1/oauth/connections/custom_api/CONNECTION_ID` | Changed settings above; this route **does not update access policy** |
| Replace connector policy | `PUT /v1/oauth/connections/CONNECTION_ID` | `{"access_policy": {...}}` |
| Read Sprite labels | `GET /v1/sprites/SPRITE_NAME` | None |
| Replace Sprite labels | `PUT /v1/sprites/SPRITE_NAME` | `{"labels": ["existing-label", "nebius"]}` |

Creation returns HTTP201 with `connection`; policy/settings updates return
HTTP200. Connector readback is sanitized: verify the ID, provider
`custom_api`, base/test URLs, auth settings, and policy without expecting a key
in the response. For rotation, only the settings route receives a new
`access_token`; never put it in the policy document.

For API operations, keep auth configuration, any creation/rotation JSON, and
responses in owner-only host files outside this repository (`umask 077`, mode
`0600`). Use a credential-aware client or `curl --config /private/auth.conf
--data-binary @/private/request.json`; the configuration supplies the bearer
header without putting its value in process arguments. Build key-containing JSON
with a local JSON serializer reading the existing private key file, not shell
interpolation. Do not use verbose/trace logging, `set -x`, environment dumps,
inline tokens, or redirects. Review the exact destination before sending.
These are manual steps, not permission to create or change anything.

After approval, read existing state before each change. The policy and label
operations **replace**, rather than merge, their values. Retain a private backup,
preserve existing labels, and preserve any deliberate connector restrictions.
Use a reviewed full policy such as:

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

All listed labels are required; a saved `name_prefix` also restricts access.
Do not remove a test-only prefix or other existing scope restriction merely to
make a test pass: widening access needs approval. Read the connector and Sprite
back after changes and compare their complete policy/label values. The current
Fly UI preserves saved endpoint restrictions when editing labels/prefixes but
cannot edit the endpoint lists itself. Keep provider keys and raw identifiers
out of public reports.

### Production per-Sprite test and independent-admin gate

Use an isolated, explicitly approved test Sprite. On the connector detail page,
save the policy, then select **Test** next to that Sprite in **Authorized
Sprites**. The Sprite's own Connectors tab also has a Test button. Both use:

```text
POST /v1/oauth/connections/CONNECTION_ID/test_gateway
{"sprite_name":"APPROVED_SPRITE_NAME"}
```

This runs curl inside the Sprite through the gateway and derives `/models` from
the stored full Test URL. It temporarily creates a test token and executes in
the Sprite, so obtain approval before running it. Require `result.status: "ok"`
and a successful upstream HTTP result; HTTP200 alone is not a pass. The Custom
API form's separate credential **Test** (`POST /connections/custom_api/test`
under `/v1/oauth`) runs from the control plane and is not equivalent.

Scott's V4 names **Gateway Playground**, which is still dev-only/unported in
current source. The production per-Sprite Test is the proposed equivalent,
**not yet an accepted change to the spec**. Obtain Scott's acceptance and record
the actual route used before marking V4 passed. Production Test does not return
or validate the model list: a generic 2xx success alone is insufficient. An
accepted alternative must also retain a model-list check from the same Sprite
and connector; see [verification](verification.md#v4-and-v10-explicit-operator-evidence).

For B5, ask a separately authorized administrator to follow this guide unaided,
including readback, labeling and the per-Sprite test. Record their outcome and
any clarifications needed; the guide's existence is not a B5 pass. Resource,
label and policy changes, cleanup, and any access widening remain administrator
actions, not something this harness performs.

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
that the spec's POST `/files` check V9 has passed. `access` sends no write-denial
POST. After separate authorization, use:

```sh
python3 scripts/verify write-denial \
  --gateway-url 'https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID' \
  --approve-write-denial
```

This does a successful model-list preflight followed by exactly one empty JSON
POST `/files`, with no retry or actual file content. A broken policy could still
dispatch to Nebius, so ordinary read-only/spend approval is not authorization
for this operation. A pass requires HTTP 403 plus the gateway's precise policy
error, not a generic provider/authentication denial. Independent no-upstream-
dispatch evidence is optional hardening, not an additional V9 requirement.

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

The request advertises `Accept: text/event-stream, application/json` for
compatibility with older gateway releases. The deployed streaming fix also
accepts SSE-only negotiation. Streaming is requested with `stream: true`, and
a JSON response does **not** pass the probe: it requires `text/event-stream`
and valid completion events. Obtain fresh approval before retrying inference
after a failed run.

Results record the harness SHA-256, per-request UTC interval, model, requested
output limit, attempt count, timing and numeric usage only, never model output,
reasoning, raw errors or real keys. Successful SSE termination and nonempty text
are required. A stream needs multiple text deltas spanning at least 50 ms to
report incremental delivery observed. A burst is **inconclusive**, not proof of
a broken endpoint: fast/short outputs may naturally arrive together. Conversely,
network delivery timing alone cannot prove that no buffering exists upstream.
Use a controlled delayed upstream reproduction to establish the cause of #588.

The timeout covers each complete HTTP request, including status, headers and
body reads, so a peer sending occasional bytes cannot extend it indefinitely.
These standalone probes require a POSIX main-thread process with no existing
real-time timer; unsupported contexts fail before network access. This is not
a hard real-time guarantee against OS scheduling or uninterruptible system
calls. Data is limited to 2 MiB per response and 128 KiB per SSE line. Redirects,
malformed/truncated streams, error events and non-SSE inference responses do
not count as success.

## Evidence still needed

Record test time, connector ID, Sprite ID and selected model with the results.
An authorized operator must correlate gateway logs for S5. Do not publish those
internal identifiers or log records in an upstream PR without review.

For v0, the proposed billing workflow is **staff-assisted reconciliation**:
request a scoped, complete, sanitized `gateway_inference_usage` export and
compare it with the customer's authoritative Nebius Billing → Usage view as
described in [acceptance](acceptance.md). The existing
`GET /v1/oauth/connections/CONNECTION_ID/usage` route supports only
provisioned/platform connections and returns 404 for Custom API; its USD totals
are not a Nebius token export. Do not invent a customer endpoint or claim
self-service reconciliation. Agreement to this v0 workflow is an acceptance
decision, not implied by this guide.

For checkpointed live runs and host-streamed credential scanning, follow
[verification](verification.md). That workflow requires explicit approval of
the Sprite, filesystem roots, live-process scope and any paid operations; it
does not grant connector-policy or label mutation permission.

Validate credential isolation from the trusted host; do not copy the actual key
into a Sprite in order to search for it. Agent tool-round-trip tests, the
Claude adapter, POST-denial validation, billing reconciliation and security
sign-off remain separate gates. No complete-spec success is claimed by this CLI.
