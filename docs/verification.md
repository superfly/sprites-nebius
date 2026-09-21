# Coordinated live verification

Run `scripts/verify suite` from a trusted host to check gateway access, both
streaming APIs, four native agents and credential isolation. It previews by
default. It does not provision resources, upload code, install agents, start the
adapter or change connector policies/labels. See [tested results](status.md).

## Prepare a plan

The host needs Python 3.12+, toolkit dependencies and an authenticated `sprite`
CLI. Both test Sprites need a clean checkout at the same reviewed revision and
a usable Python environment. On the labeled Sprite, install the pinned agents,
apply configuration and start the current-source owned adapter using
[agent setup](agent-setup.md). A healthy process from old source is insufficient.

Save a private plan outside Git. Replace all placeholders with verified values:
immutable Sprite IDs from the API, numeric org ID from usage records, and its
corresponding organization slug. Never put credentials in the plan.

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
    "roots": ["/"], "max_bytes": 4294967296,
    "max_files": 100000, "timeout": 300
  }
}
```

Review mounted filesystems and data volume before authorizing a scan. The example
budget need not fit an entire Sprite. Explicit limits can reach 16 GiB, 400,000
objects and a 1,200-second scan timeout; byte/object budgets are shared across
capture streams, while timeout is per worker with the native-agent duration
added where applicable. Exceeding a limit is inconclusive. Changed budgets
require a new approved plan, not a resume with altered limits.

```sh
.venv/bin/python scripts/verify suite --plan /private/approved-plan.json
```

Preview lists targets, pinned versions, commands, scan scope and billable probes
without external calls or key reads.

## Execute only authorized checks

Flags record prior permission for the named targets and operations:

| Flag | Operation |
| --- | --- |
| `--approve-probes` | Laptop GET; labeled/unlabeled GETs with exec approval |
| `--approve-exec` | Run the reviewed worker after verifying Sprite identity/labels |
| `--approve-inference` | Two direct streaming requests, at most 256 requested output tokens each |
| `--approve-agents` | One invocation each of Codex, OpenCode and Pi |
| `--approve-claude` | Add Claude's confined arithmetic edit/test fixture |
| `--approve-denial` | One empty POST `/files`; broken restrictions may permit upstream dispatch |
| `--approve-scan` | Transfer approved files/environments to the trusted host and read its named key file |

All remote operations also require `--approve-exec`. Native timeouts/turn limits
are not request or spending caps. These flags never authorize policy, label or
service changes. For an approved GET-only batch with remote execution:

```sh
.venv/bin/python scripts/verify suite --plan /private/approved-plan.json \
  --run --result /private/nebius-run.json --approve-probes --approve-exec
```

Unapproved checks remain blocked. The mode-600 result is checkpointed before
dispatch and protected by a single-writer lock. Preserve it and its lock outside
Git. `--resume` requires the identical plan; completed or uncertain operations
are never replayed. A failure or uncertain dispatch stops subsequent work.
Transport sets `SPRITE_EXEC_MAX_RETRIES=1` to disable startup retries. Interrupting
the host can leave a remote worker running until its own deadline: inspect
remote state and cleanup before authorizing another run.

Agent checks use real configurator-written files in isolated temporary homes,
without copied user plugins or real credentials. Temporary configuration is
restored afterward. The Claude worker verifies current-source service ownership
and readiness but does not restart it. The suite does not switch off a
pre-existing user setup; normal shell activation/restoration is a separate test.

## Credential scan

Supply `--key-file /private/nebius-key` only with scan authorization. It must be
an owner-only regular host file (0600 or 0400), validated before dispatch.
Never send the key into a Sprite. Keyless workers stream bytes to a host-only
exact-key matcher; raw captures are not stored, printed or hashed into reports.

The suite samples each native agent's initial live environment and temporary
configuration/work files before cleanup, then the approved regular-file roots
and accessible current process environments. Required missing samples, read
failures, races, caps or truncated transfers prevent a pass. A match fails even
if other coverage is incomplete.

Traversal does not follow symlinks and excludes devices and canonical
`/proc`/`/sys` trees; scanning `/` includes data-bearing `/dev/shm`.
Review unexpected virtual mounts yourself. Memory, deleted-but-open files,
xattrs, transformed copies, unsampled descendants and later environment changes
are not covered. Narrow roots are not a full-filesystem scan. Transferred data
may include other credentials, even though no raw bytes are retained.

Clean captures remain inconclusive until `--scan-acceptance` supplies a reviewed
JSON object with `profile: "lifecycle-v1"`, the exact preview `plan_sha256` and
`review_sha256` referencing private scope/timing acceptance. That review cannot
expand what was sampled. This lifecycle profile differs from the legacy
[before/after artifact scanner](acceptance.md#existing-capture-scanning);
neither proves universal key absence.

## V4 and V10: explicit operator evidence

The suite retains verification IDs in its output. V4 is the Playground
model-list check; the named Playground is development-only. Production per-Sprite
Test reports status/latency, not a validated model list. A substitute needs
explicit acceptance plus model-list evidence from the same Sprite/connector.

`--v4-evidence` wraps the [requirement ledger](acceptance.md#requirement-ledger):

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

An empty ledger cannot pass: add actual V4 evidence at that revision.
The equivalence digest must reference a real acceptance decision.
`route: "gateway-playground"` uses actual Playground evidence and needs no
equivalence digest. These are reviewed attestations, not independent proof.

`--billing-evidence` takes the [usage reconciliation document](acceptance.md#usage-reconciliation).
Org, connector, Sprite, provider, model and revision must match the plan.
Source coverage must include known usage from unsuccessful calls; unknown usage
is inconclusive. V1/V4/V10 evidence can be added with `--resume` **without
execution approval flags**, so updating evidence does not repeat inference.

Only all ten checks passing sets `verification_complete: true` and exits zero.
Missing/inconclusive checks exit nonzero. `all_checks_automated` remains false
because some evidence is collected by operators; `full_spec_verified` is always
false for the suite. It is not independent security or release sign-off.
