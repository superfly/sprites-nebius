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

## V10: attributable usage versus authoritative billing

```sh
python3 scripts/acceptance reconcile /private/path/reconciliation.json
```

1. Identify one dedicated Nebius project, model, connector, Sprite, and isolated
   UTC window. Verify which project owns the connector's key without reading or
   exporting that key. Keep a sanitized binding artifact and its SHA-256 digest.
2. Record every expected gateway inference `request_id`, including requests that
   fail or disconnect. Export the gateway's `gateway_inference_usage` records
   for the entire scope/window. Do not substitute token usage from the client
   responses: that is useful corroboration, not gateway attribution.
3. After billing settles, use **Nebius Token Factory → Billing → Usage → Full
   numbers** for the same project/model/window. Retain a private screenshot or
   export with collection time. Operational observability charts are not the
   authoritative billing source. A display last refreshed before the test is
   stale, even if its numbers happen to match.
4. Confirm there was no unrelated project traffic in the selected window and no
   omitted requests. If the console cannot express that exact window or usage
   is rounded, unsettled, or mixed with other traffic, keep V10 inconclusive.
   Never infer zero from an absent usage field.

The JSON input has these fields:

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
    "precision": "exact", "settled": true, "isolated": true,
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
`outcome: "completed"`, `usage_known: true`, `unit: "tokens"`, and nonnegative
integer `input_count` and `output_count`. Preserve the gateway's integer org ID.
Billing `data_through` records the console's actual data freshness, not the
browser refresh time. It must cover the complete test window, and `collected_at`
cannot precede it. Unknown freshness is inconclusive even with matching totals.

The exact expected request set must be present once each. Missing, extra,
duplicate (even identical), conflicting, cross-scope, partial, failed, or
unknown-usage records make reconciliation inconclusive rather than silently
changing the total. Investigate duplicates at their source and produce a
reviewed, complete export; do not cherry-pick the favorable record.

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

Capture orchestration is deliberately not implemented yet. Before collecting
anything, obtain authorization for reading the Sprite's filesystem and all
process environments, including their transfer to the trusted host. Plan a
bounded, authenticated, encrypted streaming transfer into private host files;
do not persist a second copy inside the Sprite. Restrict access and retention
because captures can contain **other credentials** even when the Nebius key is
absent. Do not upload captures to GitHub or another service.

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

The offline tools do not yet orchestrate the full V1–V10 suite. Existing
`scripts/verify` probes cover selected gateway checks; preserve their raw result
timestamps and requirement scope. V4 still needs the specified Gateway
Playground route, not a relabeled equivalent CLI request. V5–V8 require approved
agent runs (including independent file/test verification for Claude). V9 is an
actual POST denial test and needs permission because a failed restriction could
allow dispatch. Live collection and billing-console evidence remain separate,
explicit steps; missing permission or unavailable evidence is not a pass.
