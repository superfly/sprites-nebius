# Acceptance evidence and reconciliation

The local unit suite tests the implementation; it is not live acceptance. The
offline commands below evaluate **supplied, reviewed evidence**. They do not run
agents, make inference requests, change connector policy, collect browser data,
or prove that the input attestations are truthful. Exit status is zero only for
a passing result; failed, missing, blocked, or inconclusive evidence is nonzero.

Keep original evidence private outside this repository. Preserve collection
timestamps and the tested Git revision; never relabel an older observation as a
new test. Do not include provider keys, headers, request/response bodies, or raw
console exports in a public report. Output is allowlisted metadata and counts.

## Requirement ledger

```sh
python3 scripts/acceptance ledger /private/path/ledger.json
```

The input is an object with `tested_revision` (the full, lowercase 40-character
Git SHA) and `entries`. Each entry has this shape:

```json
{
  "requirement": "S1",
  "status": "pass",
  "timestamp": "2026-09-16T01:02:00Z",
  "tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "evidence": [{
    "source": "gateway-log",
    "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }]
}
```

These are schema examples, not actual observations. Status is `pass`, `fail`,
`inconclusive`, or `blocked`. Sources are `local-tests`, `gateway-log`,
`gateway-playground`, `nebius-billing`, `agent-run`, `host-scan`, `manual-review`,
`publication`, and `outreach`. Compute artifact SHA-256 digests locally and keep
the private mapping to original evidence. Free-text notes, file paths, and other
unknown input fields are deliberately omitted from output.

The ledger always emits S1–S6, B1–B6, L1–L3, and V1–V10. Missing entries are
blocked. Duplicates, invalid references, and evidence for a different tested
revision are inconclusive. A full-spec pass requires passing evidence for all 25
requirements at the target revision. `evidence_only: true` is a reminder that
this is an evidence assessment, not a fresh end-to-end test or security sign-off.
Record manual review, independent admin setup, publication, and outreach only
after those activities actually happen with their necessary authorization.

## V10: attributable usage versus the Nebius console

This BYOK integration does not invoice or collect Nebius payments. V10 compares
recorded token usage with the customer's Nebius console, within 5%; it does not
certify financial settlement. The legacy `billing.settled` field is ignored in
both modes. Matching source scope, complete counts and actual data freshness
are still required; an unsettled invoice does not imply stale token data.

```sh
python3 scripts/acceptance reconcile /private/path/reconciliation.json
```

1. Identify one dedicated Nebius project, model, connector, Sprite, and isolated
   UTC window. Verify which project owns the connector's key without reading or
   exporting that key. Keep a sanitized binding artifact and its SHA-256 digest.
   Retain evidence of project isolation, not just a claim that the Sprite was
   isolated: another user or key in that project could produce billable traffic.
2. Record every expected gateway inference `request_id`, including requests that
   fail or disconnect. Export the gateway's `gateway_inference_usage` records
   for the entire scope/window. Do not substitute token usage from the client
   responses: that is useful corroboration, not gateway attribution.
3. When source coverage is known, use **Nebius Token Factory → Billing → Usage → Full
   numbers** for the same project/model/window. Retain a private screenshot or
   export with collection time. Operational observability charts are not the
   authoritative billing source. A display last refreshed before the test is
   stale, even if its numbers happen to match.
4. Confirm there was no unrelated project traffic in the selected window and no
   omitted requests. If the console only offers whole UTC days, use the
   whole-day mode below instead of pretending it displays a short test interval.
   Rounded, stale, unknown-coverage or mixed-scope evidence is
   inconclusive. Never infer zero from an absent usage field or invent a
   data watermark, independent server count, or isolation fact.

### Existing exact request-set mode

The original schema remains supported (`scope.accounting_mode` defaults to
`request-set`). It requires an exact expected request set and matching source
coverage, not a final invoice or settlement assertion. Keep this mode for
sources that can truthfully establish that coverage. The JSON input has these fields:

```json
{
  "tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "scope": {
    "project_id": "project-example", "model": "org/model",
    "connector_id": "connector-example", "sprite_id": "sprite-example",
    "org_id": 123, "provider": "custom_api",
    "started_at": "2026-09-16T01:00:00Z",
    "finished_at": "2026-09-16T01:02:00Z",
    "request_ids": ["request-example"], "isolated": true,
    "project_binding_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "gateway": {
    "complete": true,
    "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "records": []
  },
  "billing": {
    "source": "nebius-billing-usage", "view": "full-numbers",
    "precision": "exact", "isolated": true,
    "project_id": "project-example", "model": "org/model",
    "started_at": "2026-09-16T01:00:00Z",
    "finished_at": "2026-09-16T01:02:00Z",
    "unit": "tokens", "input_count": 23, "output_count": 51,
    "collected_at": "2026-09-16T01:10:00Z",
    "data_through": "2026-09-16T01:05:00Z",
    "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
```

Replace examples with actual observations. The empty `records` array above
**cannot pass**. Each gateway record must contain `event` equal to
`gateway_inference_usage`, `request_id`, `connector_id`, `sprite_id`, `org_id`,
`provider`, `model`, `started_at`, `finished_at`, integer HTTP `status`,
nonempty machine-readable `outcome`, `usage_known: true`, `unit: "tokens"`, and nonnegative
integer `input_count` and `output_count`. Preserve the gateway's integer org ID.
Billing `data_through` records the console's actual data freshness, not the
browser refresh time. It must cover the complete test window, and `collected_at`
cannot precede it. Unknown freshness is inconclusive even with matching totals.

The exact expected request set must be present once each. Missing, extra,
duplicate (even identical), conflicting, cross-scope or unknown-usage records
make reconciliation inconclusive rather than silently changing the total.
**Include failed and disconnected requests when the gateway recorded known
usage**: they may still be billed. `noncompleted_request_count` discloses how
many were included; a billing match does not make those requests successful.
Unknown usage on even one request remains inconclusive. Investigate duplicates
at their source and produce a reviewed, complete export; do not cherry-pick the
favorable record.

### Whole-UTC-day mode

Set `scope.accounting_mode` to `utc-day` when the authoritative console's useful
granularity is one UTC day. Both `scope` and `billing` must span exactly one
closed midnight-to-midnight UTC day, e.g. `[2026-09-16T00:00:00Z,
2026-09-17T00:00:00Z)`. This is an alternative completeness model, not permission
to widen a narrow export or relabel its window.

Start from the schema above and make these changes:

- Set both windows to the same whole day and add `scope.accounting_mode:
  "utc-day"` plus `scope.isolation_sha256`, the digest of reviewed project-wide
  isolation evidence covering that entire day. Keep the project-binding digest
  and both `isolated` attestations.
- `scope.request_ids` becomes optional. If present, it is still checked exactly;
  do not derive a supposedly independent expected set from the exported rows.
- Request a **staff-assisted** gateway export with the metadata below. The
  existing customer `/connections/:id/usage` endpoint excludes Custom API
  connections; no private customer export API is assumed.
- Whole-day mode requires a closed day and actual recorded
  `data_through` coverage at or after its end, collected after that watermark.
  The output does not claim final invoicing or promise that provider billing
  will never be revised.
  If source freshness is unknown, **do not substitute the browser refresh time**:
  reconciliation remains inconclusive, even after waiting or seeing equal totals.

Provider collection is still manual. As of 18 September 2026, the official
[Token Factory billing guide](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new)
documents the console Usage view, but we have not verified a supported API for
authoritative project/model daily token totals or inference-key project lookup.
Its [observability documentation](https://docs.tokenfactory.nebius.com/ai-models-inference/observability)
restricts metrics to dedicated endpoints and excludes billing reconciliation;
do not use Prometheus metrics as a substitute for serverless billing evidence.
Automating retrieval needs a supported source with project/model identity,
input/output token units, window boundaries and actual freshness semantics.
Until then, automatic arithmetic over operator evidence is not automatic
collection and does not close literal B4.

Add this `gateway.export` metadata, filled with observed values rather than the
example identifiers/digests:

```json
{
  "connector_id": "connector-example", "sprite_id": "sprite-example",
  "org_id": 123, "provider": "custom_api", "model": "org/model",
  "started_at": "2026-09-16T00:00:00Z",
  "finished_at": "2026-09-17T00:00:00Z",
  "window_basis": "overlapping-requests",
  "server_count": 12,
  "truncated": false,
  "data_through": "2026-09-17T01:00:00Z",
  "collected_at": "2026-09-17T01:05:00Z",
  "query_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

The retained query/coverage artifact must show the exact identity filters and
window, source freshness, pagination/limit handling, and an independent
server-side count for the same query. Count all matching gateway observations,
not just completed/2xx requests. `server_count` must equal the number of uniquely
identified records in the complete export; duplicate IDs, truncation, missing
pages and count disagreement are inconclusive. The accepted bound is 10,000
records; a larger day requires a reviewed workflow change, not truncation.

Query requests **overlapping** the day, not merely those starting inside it
(`started_at < day_end` and `finished_at >= day_start`). Inspect neighbouring
boundary evidence as necessary. A request crossing either UTC midnight makes
this simple one-day reconciliation inconclusive (including a request finishing
exactly at the next midnight): it cannot safely assign tokens to a provider
billing day. Do not discard the boundary request or guess its
allocation. Absent/incomplete observations cannot be declared complete merely
because the returned rows equal a query count; coverage and isolation remain
reviewed evidence prerequisites.

The gateway export needs its own actual `data_through` and `collected_at`, not a
watermark copied from Nebius. Both systems must cover the entire accounting
window. Binding, isolation, source coverage and exact billing precision are
still required even if input/output totals match exactly. A whole-day comparison
is not a fresh test of the current harness revision: retain the revisions and
provenance of the requests it accounts for in the reviewed evidence.

### Numeric comparison (both modes)

For an **exact** display in millions, use `unit: "million-tokens"` and decimal
strings such as `"0.000023"`, not floating-point numbers. Conversion must yield
whole tokens; changing the unit cannot make a rounded display exact. The
comparison uses `abs(gateway - Nebius) / Nebius` independently for input and
output, with an inclusive 5% bound. Both zero in one direction agrees; nonzero
gateway versus zero provider fails. Zero total provider usage is inconclusive.
A V10 pass does not imply full-spec acceptance.

## V1: host-only key-leak scan

```sh
python3 scripts/acceptance scan /private/path/capture-manifest.json \
  --key-file /private/path/nebius-key
```

Run this **on the trusted host**, never inside the Sprite. The key must already
exist in an owner-only regular local file (mode `0600` or `0400`); do not paste it
into a command, prompt, environment variable, or manifest. The command rejects
symlinks and group/world-accessible files. It reads only the explicitly supplied
key file and capture paths. It never enumerates the host filesystem, sends the
key anywhere, prints paths, prints matching text, or emits a key hash.

The artifact scanner remains available for already-collected captures. The
separate streamed collector uses `nebius_capture.CaptureWriter` and a host-side
`scan` with the private key-file; see [verification](verification.md) for its
API, suite checkpoints and permission gates. It does not persist raw captures
on either side. Before collecting anything, obtain approval for the precise
filesystem roots, live-process environment scope, and their transfer to the
trusted host. Do not send the actual key to the Sprite as a search argument.
If using the legacy artifact scanner below, restrict capture access and
retention because they can contain **other credentials** even when the Nebius
key is absent. Do not upload captures to GitHub or another service.

Capture the full filesystem scope and every process environment both before
and after the approved agent runs. Keep raw, uncompressed bytes and a coverage
manifest accounting for traversal failures, permissions, exclusions, processes
that disappear, and races. Do not label a partial home-directory scan as the
whole filesystem. A `/proc` environment snapshot alone is not a filesystem
scan, and the current shell's environment is not all process environments.

The manifest contains `tested_revision`, `started_at` and `finished_at` for the
agent-run window, plus `coverage` and `artifacts` arrays. Include all four
combinations of `phase` (`before`, `after`) and `scope` (`filesystem`,
`process-environment`). Each coverage entry has:

```json
{
  "phase": "before", "scope": "filesystem",
  "captured_at": "2026-09-16T01:00:00Z", "complete": true,
  "unreadable_count": 0, "excluded_count": 0, "race_count": 0
}
```

Each artifact names a private owner-only host file:

```json
{
  "phase": "before", "scope": "filesystem", "encoding": "raw",
  "path": "/private/path/before-filesystem-capture",
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Before timestamps must be at or before the run; after timestamps must be at or
after completion. Reusing the same path across phases cannot pass. SHA-256
digests are checked while scanning; changed captures, missing scope/phase,
empty-only captures, unreadable files, exclusions, or races produce incomplete coverage. A match
fails even if other evidence is incomplete. Results contain only status,
revision/time, and aggregate coverage/scan counts; no key, capture paths, or
matched values. Scanning checks exact raw key bytes, including across read
boundaries; it does not claim detection of encrypted or transformed copies.

The scanner cannot independently attest how a capture was made. Honest,
reviewed coverage is a prerequisite, not an optional flag to obtain a pass.
Do not run this command on real captures until the host-side collection and
private key access have been explicitly approved.

## Remaining live gates

The [coordinator](verification.md) combines the V1–V10 checks, but its complete
live trial and acceptance of operator-supplied V4/V10 evidence remain open.
Preserve standalone probe timestamps and requirement scope rather than treating
them as a completed coordinated run. V4's proposed equivalent is the existing
production per-Sprite connector **Test**, which executes a gateway `/models`
request inside the selected Sprite. It is not the dev-only Gateway Playground;
obtain Scott's acceptance of this substitution and preserve that decision with
the actual UI/API result before marking V4 passed. V5–V8 require approved
agent runs (including independent file/test verification for Claude). V9 is an
actual POST denial test and needs permission because a failed restriction could
allow dispatch. Live collection and billing-console evidence remain separate,
explicit steps; missing permission or unavailable evidence is not a pass.

The 16 September live smoke run passed V5–V8 and observed the required policy
403 for V9. See [status](status.md) for exact versions and revisions. Those
observations do not supply V1 capture evidence. The separately approved
20 September key scan found no matches but hit its byte cap. A separately
approved larger scan on 21 September completed the declared regular-file and
live-environment scope with no matches, read/race gaps or cap hits. This is a
point-in-time scoped V1 pass, not a historical/lifecycle or universal absence
guarantee; its exclusions are recorded in the checklist. Earlier authorized
gateway inspection established S5 attribution. On 21 September, refreshed
September 18 whole-day provider totals matched the gateway's 21,851 input /
303 output tokens exactly. A full-day connector export and independent
server-side count both contained the same 11 requests; the provider display
was updated after that UTC day ended. V10 still needs key-to-project binding
and confirmation that the project had no unrelated traffic. Production's
connector Test button is available, but Gateway Playground itself is gated
behind development mode. Staff-assisted reconciliation is the proposed v0
workflow, not a customer self-service export or an already-approved change to
US5. Settle both acceptance decisions before claiming those gates closed.
