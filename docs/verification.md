# Coordinated verification (host-side)

`scripts/verify suite` coordinates the existing probes and native-agent tests.
It previews by default. It does **not** create Sprites/connectors, upload code,
install agents, start the adapter or change policy/labels. Its remote transport
and the new activation wrapper still need an explicitly approved live trial.

## Prepare an explicit plan

Use a trusted host with Python 3.12+, toolkit dependencies and an authenticated
`sprite` CLI. Both existing test Sprites need the reviewed, **clean Git checkout
at the specified commit** and its virtual environment. The labeled Sprite needs
the selected agents installed at the documented pins, configuration applied,
and the owned Claude adapter already healthy. Use the normal
[`use-nebius` workflow](agent-setup.md) for that separately approved setup.

Save a reviewed plan outside the repository; these are placeholders, not live
targets. Obtain immutable Sprite IDs from their API records. `org_id` is the
numeric organization ID used in gateway usage records; have the operator verify
its binding to the organization slug. Never put a token or key in this file.

```json
{
  "schema_version": 1,
  "tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "gateway": "https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID",
  "model": "provider/model",
  "org": "YOUR_ORG",
  "org_id": 123,
  "labeled": {
    "name": "labeled-test", "id": "sprite-labeled-id",
    "checkout": "/home/sprite/sprites-nebius",
    "python": "/home/sprite/sprites-nebius/.venv/bin/python"
  },
  "unlabeled": {
    "name": "unlabeled-test", "id": "sprite-unlabeled-id",
    "checkout": "/home/sprite/sprites-nebius",
    "python": "/home/sprite/sprites-nebius/.venv/bin/python"
  },
  "agent_bin": "/home/sprite/agent-pins/bin",
  "agent_timeout": 120,
  "scan": {
    "roots": ["/"],
    "max_bytes": 4294967296,
    "max_files": 100000,
    "timeout": 300
  }
}
```

The scan example is a ceiling, not a promise that an entire Sprite fits within
it. Review its mounted filesystems and data volume before approving. Smaller
root lists narrow the evidence: never present a home-only scan as a full
filesystem scan. Exceeding a byte/object/time limit is inconclusive.
Byte and object allowances are shared across the five lifecycle/final capture
streams; each worker receives only the remaining allowance. The timeout is per
worker, with the native-agent duration added where applicable.

```sh
.venv/bin/python scripts/verify suite --plan /private/approved-plan.json
```

Preview lists targets, pinned versions, native commands, scan scope and the
potentially billable probes. No external call or key read occurs in preview.

## Authorize only the intended operations

These flags record **separately obtained permission**, not permission grants:

| Flag | Operation |
| --- | --- |
| `--approve-probes` | Laptop GET; with exec approval, labeled/unlabeled GET checks |
| `--approve-exec` | Execute the reviewed worker on the named Sprites; read back Sprite identity/labels first |
| `--approve-inference` | Exactly two direct streaming probes, Chat and Responses, at most 256 requested output tokens each |
| `--approve-agents` | One native invocation each of Codex, OpenCode and Pi; adds Claude only with its separate flag |
| `--approve-claude` | The existing confined arithmetic edit/test task, not arbitrary tool use |
| `--approve-denial` | One empty POST `/files`, expecting the gateway's policy 403 |
| `--approve-scan` | Read and transfer the declared files/process environments to the trusted host, and read the explicitly named host key |

All remote operations also require `--approve-exec`. Agent timeouts and Claude's
turn limit are **not** exact provider-request or spending caps. No retries are
made. No service/policy/label changes are implicitly authorized by these flags.

For example, **after approval for GET probes and remote execution only**:

```sh
.venv/bin/python scripts/verify suite --plan /private/approved-plan.json \
  --run --result /private/nebius-run.json --approve-probes --approve-exec
```

Other checks remain blocked. Add only the flags authorized for a later batch.
The result is mode 0600, checkpointed **before** each dispatch and protected by
a single-writer lock. Keep it and its lock outside Git. `--resume` uses the same
`--result` and exact plan; completed or uncertain operations are never replayed.
An uncertain operation or failed check stops later work. Inspect cleanup before
requesting a new run and fresh spending allowance. Transport interruption may
leave the remote worker running until its own deadline; inspect the Sprite,
do not assume killing the local CLI immediately cancels remote execution.

## What the suite actually proves

- V2/V3: laptop/unlabeled denial, in distinct checked target contexts.
- V5–V8: native agent results using files emitted by the real configurator in
  isolated temporary homes, plus configured-route validation. Safety restrictions
  are seeded before configuration; no copied user plugins or real credentials.
  Temporary configuration is restored and directories removed after execution.
- V9: the specified 403 **and** gateway policy error. Independent no-dispatch
  tracing is optional extra assurance, not a new acceptance requirement.
- S1/S2/S3 and GET-denial observations are retained separately. They do not prove
  complete S4 policy coverage or actual deployment of every current-main feature.

The suite does not switch off the user's pre-existing configuration or adapter.
Independently exercise normal shell on/off and compare original files when
validating the new wrapper. That and the unaided-admin trial remain distinct
from isolated native-agent acceptance.

### V1: streamed, scoped and point-in-time

With scan approval, supply `--key-file /private/nebius-key`, an existing owner-only
regular host file, mode 0600 or 0400. Never place the key inside a Sprite or plan.
The host validates it **before dispatching** a scan-enabled worker. A keyless
collector streams framed bytes directly into the host matcher; no raw capture
is stored, printed, hashed into reports or sent to an external service.

The suite samples each native agent's initial process environment while alive,
then its temporary configuration/work files before cleanup, and finally the
approved regular-file roots plus accessible live-process environments. An
exited process's environment cannot be reconstructed; the initial sample does
not cover every descendant or later mutation. Required missing samples,
unreadable files, races and truncated transfers prevent a pass. A detected key
remains a failure even if later collection fails.

The collector uses no-follow descriptor traversal, excludes symlinks/devices/
canonical `/proc` and `/sys` trees, and includes data-bearing `/dev/shm` when
traversing `/`. A virtual filesystem mounted elsewhere needs explicit review
when choosing roots; this is not automatic mount-type discovery. Memory,
deleted-but-open files, xattrs and transformed/encoded copies are not covered.
Collection can transfer other sensitive data: obtain permission for its scope
and transfer even though bytes are not retained.

This lifecycle profile is a practical proposed interpretation of V1, **pending
security acceptance**, not the older artifact scanner's stronger before/after
contract. The existing offline artifact command remains available unchanged.
Do not manufacture coverage flags or claim a universal absence guarantee.

Even clean scans leave V1 inconclusive until `--scan-acceptance` supplies a
reviewed JSON object with `profile: "lifecycle-v1"`, the exact `plan_sha256`
printed by preview, and `review_sha256` referencing the private scope/timing
acceptance. This can be added later with an evidence-only resume; it never
retroactively expands the sampled scope or grants permission for another scan.

### V4 and V10: explicit operator evidence

The named Playground remains dev-only. Production per-Sprite **Test** already
executes `/models` from the Sprite when configured appropriately, but Scott's
acceptance of that equivalence is still required. The suite does not silently
substitute a CLI GET or mutate the spec.

`--v4-evidence` accepts this wrapper around the existing requirement-ledger
format from [acceptance.md](acceptance.md):

```json
{
  "route": "production-test",
  "equivalence_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "context": {
    "org_id": 123, "sprite_id": "sprite-labeled-id",
    "gateway": "https://api.sprites.dev/v1/gateway/custom_api/CONNECTION_ID"
  },
  "ledger": {"tested_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "entries": []}
}
```

An empty ledger cannot pass. Supply actual reviewed V4 evidence at that revision;
the equivalence digest references the private acceptance decision, not an
invented identifier. `route: "gateway-playground"` uses actual Playground
evidence and does not need an equivalence digest. These inputs are reviewed
attestations, not cryptographic proof that the observation was truthful.

`--billing-evidence` takes the V10 reconciliation document. Prefer the documented
whole-UTC-day scope, verified project/key binding, complete operator log export
and authoritative full-number Nebius billing counts with actual freshness.
Record known usage from unsuccessful calls too; unknown potentially billed
usage is inconclusive. Numeric org, connector, Sprite, provider, model and tested
revision must match the plan. Imports can be added with `--resume` **without any
execution approval flags**, so billing refresh cannot repeat inference.

Only V1–V10 all passing makes `verification_complete: true`. Operator evidence
keeps `all_checks_automated: false`: literal B4 remains open until retrieval is
automated or Scott explicitly accepts this operator-input boundary. Independent
admin acceptance, security sign-off, publication and outreach are separate.
`full_spec_verified` is always false for this suite. Keep the repository private
and do not publish logs, key files, plans or original evidence.
