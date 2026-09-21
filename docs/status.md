# Requirement-to-evidence checklist

Updated 21 September 2026. Live smoke success is not release/security sign-off.
Keep private resource identifiers and original usage evidence out of public Git.

## Live agent evidence

All used `Qwen/Qwen3-30B-A3B-Instruct-2507` through the existing connector,
with placeholder credentials inside the Sprite. Native invocation/turn limits
are not exact provider-request or dollar caps; no automatic retries were used.

| Check | Version | Result and tested revision |
| --- | --- | --- |
| V5 Codex | 0.154.0 | Exact `OK`; `962d14f`, 07:36:26–07:36:32 UTC |
| V6 OpenCode | 1.18.31 | Exact `OK`; `f987cca`, 07:29:11–07:29:19 UTC |
| V7 Pi | 0.85.1 | Exact `OK`; `f987cca`, 07:29:19–07:29:29 UTC |
| V8 Claude | 2.1.273 | Edit + test tool results, 4 streamed deltas, independent test passed; `0f87f40`, 07:45:52–07:46:07 UTC |

The table above records 16 September 2026. After hardening, Claude alone was
rerun at clean commit `9fd19d4` on 17 September, 20:02:15–20:03:49 UTC
(18 September Melbourne). The one invocation passed with the permitted edit,
successful test tool result, four streamed deltas and an independent test rerun.
All 195 offline tests also passed on the Sprite under Python 3.13.7. No retry
was made; exact upstream request/token totals were not reconciled for this run.

Codex emits a pre-turn custom-model fallback-metadata notice. The verifier
recognizes only that exact notice; other errors and tool use still fail V5.
These are dated smoke observations, not blanket certification or evidence
silently relabeled for a later commit. No full 25-requirement pass is claimed.
The pre-PR hardening review itself was offline; the separately authorized
Claude rerun above provides live evidence for its final implementation.

### Standalone agent batch — 18 September

On **18 September 2026, 01:57:40–01:58:55 UTC**, clean revision `b880115`
passed the normal sourced on/off workflow and current-source owned-service
readiness, followed by one invocation of each pinned agent above. Codex,
OpenCode and Pi returned exact `OK`; Claude completed the confined edit/test
task with five stream deltas and an independently passing test.

The two separately capped streaming requests each produced 50 text deltas:
Chat Completions over 1,828.87 ms, Responses over 1,835.97 ms. Each requested
at most 256 output tokens and reported 23 input / 51 output tokens. These are
client observations, not reconciled gateway billing. One empty POST `/files`
returned 403 with the expected gateway policy error. No retry was made.

All 292 offline tests also passed on the Sprite under Python 3.13.7, and its
installed Python requirements were consistent. Restoration and a separate
readback verified all nine managed-file candidates' original bytes/existence,
no active/pending/service ownership markers, no remaining owned service and
no port-8083 listener. Shell activation/deactivation both passed.

This batch used the existing standalone native/probe functions with a private
sequential supervisor, not the complete two-Sprite coordinator. It does not
establish fresh V1–V4, full S4 policy, V10, cancellation behaviour, or independent
admin/security acceptance. No key scan, policy/label change or new Sprite was
authorized or performed. The current four-agent/two-stream/one-denial allowance
is consumed; further live invocations need fresh approval.

### Subsequent denial and key-isolation checks

At revision `826a930`, standalone V2 and V3 checks passed on **18 September
2026**: one laptop GET returned 401 at 03:34:58 UTC, and one GET from a newly
created unlabeled Sprite returned 403 at 03:39:20 UTC. Neither check made an
inference request or changed connector policy.

On **20 September 2026, 22:42–22:46 UTC** (21 September Melbourne), a separately
approved batch used a new test connector/key and the existing labeled Sprite.
One gateway GET `/models` returned 200 with 24 validated models. Temporary
`/models` access was restored to deny-all immediately after that GET, before
collection; final verification and an independent readback confirmed it.
The original connector and Sprite labels were unchanged. No inference or retry
was performed.

The keyless collector from `826a930` streamed regular files and live process
environments directly to the host-only exact-key matcher, without retaining or
printing raw capture data or sending the key to the Sprite. It sampled 85,172
files and 3 environments (4,294,945,515 bytes), finding **zero matching objects**
and no unreadable objects or detected races. It excluded 1,560 objects under its
declared scope and reached the approved **4 GiB byte cap**, leaving **V1
inconclusive at that point**. This is point-in-time evidence for the new test key, not proof
about historical agent executions or a complete filesystem scan.

The standalone wrapper completed successfully; its exit zero does not mean V1
passed. The allowance is consumed. Further collection needs a reviewed budget
and fresh permission. The tested revision's 4 GiB implementation ceiling was
subsequently raised for explicitly budgeted future runs; this does not extend
the consumed allowance or change this result. Private resource identifiers,
source hashes and metadata-only checkpoints remain outside this repository.

### Completed point-in-time key scan

On **21 September 2026, 01:15:10–01:21:57 UTC**, a separately approved scan at
revision `1d3317d` completed the declared regular-filesystem and current-process
environment scope. A preceding metadata-only inventory measured 180,925 regular
files totaling 9.72 GiB, explaining why the earlier 4 GiB allowance was too small.

The host-only matcher found **zero key matches** across **180,929 regular files
and 3 live process environments**, totaling **10,437,647,358 bytes (9.72 GiB)**.
The file count increased by four, matching the four newly staged keyless source
files. There were **no unreadable objects, detected races or cap hits**. The
single scan took 407.4 seconds, within its approved 16 GiB / 400,000-object /
20-minute ceiling; the matcher reported `no_match_in_declared_scope`.

This passes the **point-in-time scoped V1 check**, not a universal absence or
historical-agent guarantee. The collector excluded 1,638 symlink/device/virtual
objects; `/dev/shm` was included. Memory, deleted files, xattrs and transformed
copies were not searched. Earlier agent process environments cannot be recovered
by this scan. These explicit limits remain part of the security-review handoff;
the complete lifecycle coordinator was not run.

The key stayed on the trusted host. Raw captured bytes were neither stored nor
printed. Final readbacks confirmed the same Sprite/labels, the new connector
still deny-all, and the original connector policy unchanged. No inference,
model-list request, policy mutation or retry was made. This allowance is consumed.

### Refreshed whole-day usage comparison

Read-only inspection on **21 September 2026** compared the entire **18 September
UTC day** for the original test connector with the Nebius project's Full numbers
view. The gateway export contained **11 unique completed, known-usage, HTTP 200
records**, totaling **21,851 input / 303 output tokens**. An independent
server-side count also returned 11. The full-day query omitted the Sprite filter;
all records nevertheless belonged to the expected test Sprite, and the export
was byte-for-byte identical to the saved September 18 batch. No request crossed
the UTC-day boundary.

Nebius displayed **0.021851 million input / 0.000303 million output tokens** for
the same model and day: **0% difference**. Its displayed update time was
20 September at 23:17 UTC, after the accounting day ended. This closes the
previous window/freshness and connector-log-count gaps. The operator subsequently
confirmed on 21 September that both connector keys belonged to the selected
project and were used exclusively for these tests. With that administrative
attestation, the reviewed September 18 comparison **passes V10's 5% criterion**
and B6's acceptance condition. This is a manual evidence review, not independent
credential inspection or a new live test of later code.

The strict whole-day reconciliation importer was not marked passed: the saved
query used log-event time and did not establish a gateway ingestion watermark.
No missing metadata was fabricated. B4's fully automated source collection and
the complete coordinator trial remained open at that point. Private project/
connector identities and source evidence stay outside Git.
No inference, key access or external mutation was performed during this review.

### Coordinated live verification — 21 September

At clean revision **`fda0632`**, the complete two-Sprite coordinator ran from
**04:28:15 to 04:36:33 UTC**. Every operation completed once, with no retry.
The laptop and unlabeled-Sprite denials passed, as did connector authentication,
caller-key replacement, both incremental streaming routes, GET policy denials,
all four pinned agents, and the empty POST `/files` policy denial. Codex,
OpenCode and Pi returned exact `OK`; Claude passed the confined edit/test fixture.
The two direct streaming requests each requested at most 256 output tokens;
native invocations are not exact upstream-request or spending caps.

Each agent's initial environment and pre-cleanup fixture capture passed the
host-only key matcher. The final scan passed across **180,945 regular files,
4 live environments and 10,438,064,846 bytes**, finding no key matches. Across
all five stages there were 181,222 file observations, 8 environment observations
and 10,458,587,881 bytes, with zero matches, unreadable objects, detected races
or cap hits. These are cumulative observations, not necessarily unique objects.
The final scan excluded 1,638 symlink/device/virtual objects; `/dev/shm` was
included. Memory, deleted files, xattrs, transformed copies and later environment
mutations remain outside scope. The key stayed on the host; raw capture bytes
were neither printed nor retained.

The separately approved wrapper temporarily granted only the dedicated test
connector's narrow policy, configured the agents and started the owned adapter.
Deny-all was restored after all provider-facing operations, during the final
scan. Cleanup and independent readback confirmed all nine managed-file
candidates matched baseline, no active/pending/service ownership markers,
no remaining owned service or port-8083 listener, and unchanged Sprite labels
and original connector policy. Private staging and backups remain.

The coordinator correctly reports **`verification_complete: false`**:
V1 is `scan_scope_review_required` because no reviewed scope-acceptance artifact
was supplied; V4 and V10 are `not_observed`. Permission to capture is not security
acceptance. The September 18 manual usage comparison is not evidence for this
new batch. `all_checks_automated` and `full_spec_verified` also remain false.
The live allowance is consumed; evidence-only imports need not repeat inference.
Private plans, checkpoints and original evidence remain outside Git.

| Requirement | Current evidence / remaining gate |
| --- | --- |
| S1 | Connector injection check passed again in the `fda0632` coordinator |
| S2 | Invalid-caller-key override check passed again in the `fda0632` coordinator |
| S3 | Both Chat Completions and Responses passed incremental-delivery checks in the `fda0632` coordinator |
| S4 | GET denials and one POST `/files` policy 403 observed; test policy remains intentionally narrower than the full proposed allowlist |
| S5 | September 21 full-day inspection found the same 11 attributed completed usage records as the September 18 batch; independent server-side count also 11. Earlier September 16 evidence remains dated evidence |
| S6 | Current-source owned-service readiness and confined Claude edit/test round trip passed at `fda0632` |
| B1 | Repo, licenses and secret-scan CI implemented; 283-test gap-closure baseline at `4c82e1d` passed both private PR and push CI checks |
| B2 | V5–V7 passed at `b880115` using real configurator-written files; normal sourced on/off and restoration verified |
| B3 | V8 and normal sourced activation/service readiness/restoration passed at `b880115`; previous service lifecycle observations remain dated evidence |
| B4 | Complete cross-context coordinator and streamed collector exercised live at `fda0632`; V1 scope review, V4/V10 evidence and automated-collection/operator-input acceptance remain open |
| B5 | Conditional quickstart, exact candidate installation pins and connector guide written; independent unaided-admin acceptance still required |
| B6 | Guide implemented; reviewed September 18 V10 comparison passed after operator project/exclusive-use confirmation. Automated acquisition remains part of B4 |
| L1 | Offline self-review and point-in-time dependency audit performed; independent security sign-off still required |
| L2 | Private repository/internal PR authorized; public release and ecosystem listing remain pending explicit authorization |
| L3 | No outreach; requires explicit authorization and reviewed usage evidence |
| V1 | All four agent captures and final scan passed at `fda0632`, with no key matches or cap/read/race gaps; coordinator acceptance remains inconclusive pending review of the declared lifecycle scope |
| V2 | Laptop GET returned expected 401 in the `fda0632` coordinator |
| V3 | Unlabeled-Sprite GET returned expected 403 in the `fda0632` coordinator |
| V4 | Production connector Test returned 200, but omits model-list evidence; Playground is development-gated. Exact specified route or an explicitly accepted complete alternative remains required |
| V5–V7 | Scoped exact-OK checks passed at `fda0632` |
| V8 | Confined edit/test task and independent fixture verification passed at `fda0632` |
| V9 | Single empty POST `/files` returned 403 with the expected gateway policy error at `fda0632`; independent no-dispatch tracing is optional |
| V10 | Reviewed September 18 comparison passed: 21,851 input / 303 output tokens on both sides (0% difference), with operator-confirmed project ownership/exclusive use. Manual evidence, not a passing strict whole-day import or financial-settlement claim; September 21 batch reconciliation remains outstanding |

## Current state

The gap-closure implementation adds one-command Bash/Zsh activation, tests of
actual configurator-written agent files, cross-context verification and a
non-persistent streamed scanner. The approved batches above supply live
evidence for activation, native-agent/probe paths and the full lifecycle
coordinator within the declared capture scope, not a universal key-absence
guarantee or completed V1/V4/V10 acceptance.
Independent acceptance and launch approval remain outstanding.
See [verification](verification.md) for permissions and remaining gates.

Before the coordinated trial, **299 offline tests passed locally and on the
labeled Sprite**. Two regressions cover treating API `labels: null` as no labels
without accepting malformed labels or weakening the labeled-Sprite guard.
All 22 Python files parsed; source secret scan and whitespace checks passed.
Five additional local wrapper tests covered policy restoration, already-denied
and concurrently changed policies, ambiguous grants, and exact approved budgets.

Local gap-closure validation on 18 September: 283 offline tests passed, including
local fixture HTTP servers, Bash/Zsh activation and streamed-capture fault tests.
All 17 installed dependencies are compatible; source secret scan and whitespace
checks passed. That local validation did not run live Sprite transport, native
inference or a real-key scan; the subsequently approved live batch is recorded
above. Neither is independent security or unaided-admin sign-off.

Follow-up local acceptance guards on 18 September: **292 offline tests passed**
after explicitly disabling CLI startup retries and refusing stale/unrecorded
owned adapter source before reuse, readiness or a coordinated Claude run.
Fixture tests cover legacy cleanup without automatic restart. Source secret
scan, Bash/Zsh syntax and whitespace checks passed. The later `b880115` batch
above supplies scoped live evidence, but does not close V1, V4, V10 or the
independent acceptance gates.

On 21 September, 25 collector/matcher and 43 verifier tests passed under system
Python 3.9.6, including permitted local loopback fixtures. These focused tests
cover the dependency-free paths used by the standalone batch, not the full
Python 3.12+ template runtime. No new native-agent invocation was made.

Follow-up local validation on 21 September: **297 offline tests passed** under
Python 3.12.14 with all 17 dependency versions matching the repository pins.
The larger explicit scan ceilings preserve standalone defaults, chunk sizes,
per-run limits and no-retry/resume guards. That validation preceded the separately
approved successful live scan recorded above; it did not itself establish V1.

After the original four-agent batch, all seven managed files matched their
original bytes following `configure --off`. After the post-hardening Claude
rerun, all four tracked files matched their original bytes/existence; active
and pending state, the ownership marker and port-8083 listener were absent.
Only owned temporary adapter service definitions were removed; runtime logs and
private configuration backups remain. The pinned agent prefix and reviewed
checkout remain on the dedicated test Sprite. Neither live batch changed
connector policy or labels.

The user subsequently authorized scoped usage/billing inspection and signed
into Grafana. VictoriaLogs App Logs supplied the 12 attributed records for
06:30–07:50 UTC on September 16. The comparison uses the previously collected
Nebius full-number day view, updated through 08:39 UTC, not a fresh billing
fetch. Exact totals corroborate the run but do not establish key-to-project
binding, final settlement, or absence of unrelated project traffic. Original
evidence stays private and outside this repository.

The earlier two-request allowance was consumed only by its original
Chat/Responses batch. Later native tests followed the user's instruction to
proceed with remaining acceptance; do not charge them against that exhausted
two-request budget or imply permission for unlimited future runs.

Approval flags in these tools are deliberate friction, not permission grants.
Obtain fresh authority for the exact target, execution and spending scope.
