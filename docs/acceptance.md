# Usage reconciliation and evidence formats

These offline commands assess supplied, reviewed evidence. They do not collect
logs/console data, run agents or change resources, and cannot prove an input
attestation is truthful. Exit zero means the selected assessment passed;
missing, invalid, failed or inconclusive evidence is nonzero.

Keep original evidence outside Git. Preserve collection timestamps and tested
revisions; do not relabel old observations as fresh tests. Never publish keys,
headers, raw responses, configuration backups or console exports. Outputs contain
allowlisted metadata/counts rather than input free text.

## Usage reconciliation

This is BYOK: Nebius bills your Nebius account for inference; Fly.io charges
separately for Sprite resources. Reconciliation compares token counts within 5%,
not invoices or financial settlement. The importer ignores `billing.settled`.

1. Isolate one Nebius project/model, connector, Sprite and UTC window. Verify
   which project owns the key without exporting it. Retain reviewed binding and
   project-wide isolation evidence; other keys/users can produce project usage.
2. Obtain all relevant `gateway_inference_usage` records, including unsuccessful
   requests. Client response counts are corroboration, not gateway attribution.
   Custom API connectors lack the customer token-usage export needed here:
   request a scoped, complete export from an authorized Fly operator.
3. Collect **Nebius Token Factory → Billing → Usage → Full numbers** for the same
   project/model/window. Record the source's actual freshness and collection time;
   a browser refresh is not a data watermark. Use whole-day mode if the console
   only exposes whole UTC days.
4. Include failed/disconnected requests with known usage. Missing/unknown usage,
   duplicate IDs, unrelated traffic, rounded totals or stale/incomplete sources
   are inconclusive; do not guess counts or fabricate coverage metadata.

Provider collection is manual; no supported authoritative serverless token-usage
API has been verified for this workflow. The
[billing guide](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new)
documents console usage; dedicated-endpoint observability metrics are not a
substitute. Automatic comparison does not imply automatic source collection.

```sh
python3 scripts/acceptance reconcile /private/reconciliation.json
```

### Request-set input

The default `scope.accounting_mode` is `request-set`. Use it only when both
sources cover the exact known requests/window. Replace these illustrative
values; an empty `records` list cannot pass:

```json
{
  "tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "scope": {
    "project_id": "project-example", "model": "org/model",
    "connector_id": "connector-example", "sprite_id": "sprite-example",
    "org_id": 123, "provider": "custom_api",
    "started_at": "2026-09-16T01:00:00Z", "finished_at": "2026-09-16T01:02:00Z",
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
    "started_at": "2026-09-16T01:00:00Z", "finished_at": "2026-09-16T01:02:00Z",
    "unit": "tokens", "input_count": 23, "output_count": 51,
    "collected_at": "2026-09-16T01:10:00Z", "data_through": "2026-09-16T01:05:00Z",
    "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
```

Each gateway record needs `event: "gateway_inference_usage"`, `request_id`,
`connector_id`, `sprite_id`, `org_id`, `provider`, `model`, `started_at`,
`finished_at`, integer HTTP `status`, a machine-readable `outcome`,
`usage_known: true`, `unit: "tokens"`, and nonnegative integer `input_count`/
`output_count`. Keep org IDs in their source type. Identities and timestamps
must match the declared scope; every expected ID must appear exactly once.
The result reports unsuccessful known-usage requests as
`noncompleted_request_count`; matching totals do not make those calls successful.

Billing `data_through` must cover the window; `collected_at` cannot precede it.
Use source-observed values, not timestamps inferred from matching totals.

### Whole-UTC-day input

For a closed midnight-to-midnight UTC day, use the same schema with:

- `scope.accounting_mode: "utc-day"` and matching whole-day scope/billing windows.
- `scope.isolation_sha256` referencing reviewed project-wide isolation for that
  day, in addition to the binding digest and both `isolated` attestations.
- Optional `scope.request_ids`; if provided, the exact-set check still applies.
  Do not derive a supposedly independent expected set from the exported rows.
- A complete staff-assisted export with this `gateway.export` metadata:

```json
{
  "connector_id": "connector-example", "sprite_id": "sprite-example",
  "org_id": 123, "provider": "custom_api", "model": "org/model",
  "started_at": "2026-09-16T00:00:00Z", "finished_at": "2026-09-17T00:00:00Z",
  "window_basis": "overlapping-requests", "server_count": 12, "truncated": false,
  "data_through": "2026-09-17T01:00:00Z", "collected_at": "2026-09-17T01:05:00Z",
  "query_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Retain query filters, source freshness, pagination/limit handling and an
independent server-side count for the same scope. Count all observations,
not just completed/2xx calls. Count disagreement, duplicate IDs, missing pages
or truncation are inconclusive. The maximum is 10,000 records; do not truncate
a larger day to fit.

Query overlapping requests (`started_at < day_end` and
`finished_at >= day_start`). Requests crossing either midnight, including one
finishing exactly at the next midnight, make the simple one-day comparison
inconclusive. Do not discard them or guess token allocation. The gateway needs
its own real freshness watermark covering the day, not one copied from Nebius.
Matching counts alone cannot establish complete source coverage or isolation.

### Numeric comparison

For an exact display in millions, use `unit: "million-tokens"` with decimal
strings, e.g. `"0.000023"`, that convert to whole tokens. A unit change cannot
make rounded data exact. Input and output are compared independently using
`abs(gateway - Nebius) / Nebius <= 5%`. Both zero in one direction agrees;
nonzero gateway versus zero provider fails; zero total provider usage is
inconclusive. A passing comparison is not full integration acceptance.

## Requirement ledger

This optional maintainer command summarizes reviewed integration/release evidence:

```sh
python3 scripts/acceptance ledger /private/ledger.json
```

The input has `tested_revision` (full lowercase 40-character Git SHA) and an
`entries` array. Each entry has this shape:

```json
{
  "requirement": "S1", "status": "pass", "timestamp": "2026-09-16T01:02:00Z",
  "tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "evidence": [{
    "source": "gateway-log",
    "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }]
}
```

Statuses are `pass`, `fail`, `inconclusive` or `blocked`. Sources are
`local-tests`, `gateway-log`, `gateway-playground`, `nebius-billing`,
`agent-run`, `host-scan`, `manual-review`, `publication` and `outreach`.
Digests reference real private artifacts, not invented values. The ledger emits
S1–S6, B1–B6, L1–L3 and V1–V10; missing entries are blocked, and duplicates,
invalid references or stale revisions are inconclusive. All 25 must pass for
`full_spec_verified`. `evidence_only: true` distinguishes this assessment
from a fresh test or independent sign-off.

The IDs group the checks as follows:

- S1–S6: key injection, caller-key replacement, streaming, path policy, usage
  attribution and the Claude tool round trip.
- B1–B6: repository/licenses/CI, three-agent configuration, Claude configuration,
  verification tooling, unaided setup and usage reconciliation.
- L1–L3: security review, publication/listing and partnership outreach.
- V1–V10: key isolation, laptop denial, unlabeled denial, Playground model list,
  Codex, OpenCode, Pi, Claude, POST denial and token reconciliation.

## Existing-capture scanning

For a new live collection, prefer the [streamed suite](verification.md#credential-scan).
The separate artifact scanner supports already-collected **raw** host captures:

```sh
python3 scripts/acceptance scan /private/capture-manifest.json \
  --key-file /private/nebius-key
```

Run only on the trusted host, with explicit authorization for private key access
and capture collection/transfer. The key file and captures must be owner-only
regular files (0600 or 0400); symlinks are rejected. Never put the key in Sprite
commands, prompts, environment variables or manifests. Captures can contain
other credentials: restrict retention and never upload them to an external service.

The manifest has `tested_revision`, `started_at`, `finished_at`, `coverage`
and `artifacts`. Cover all four combinations of phase (`before`, `after`)
and scope (`filesystem`, `process-environment`). Example entries:

```json
{
  "phase": "before", "scope": "filesystem",
  "captured_at": "2026-09-16T01:00:00Z", "complete": true,
  "unreadable_count": 0, "excluded_count": 0, "race_count": 0
}
```

```json
{
  "phase": "before", "scope": "filesystem", "encoding": "raw",
  "path": "/private/before-filesystem-capture",
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Before captures must precede the run; after captures must follow it. Reused
paths, changed hashes, empty/missing coverage, unreadable files, exclusions and
races prevent a pass. A match fails even with incomplete coverage. Honest full
filesystem/process coverage is required; a shell snapshot or home-only scan
cannot be declared complete.

The command reads only named files; it does not enumerate the host or collect
from Sprites. Output omits paths, matches and key hashes. Matching covers exact
raw key bytes, including across chunks, not encoded/encrypted copies. The scanner
cannot independently attest how captures were made.
