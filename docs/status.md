# Requirement-to-evidence checklist

Updated 16 September 2026. Live smoke success is not release/security sign-off.
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

Codex emits a pre-turn custom-model fallback-metadata notice. The verifier
recognizes only that exact notice; other errors and tool use still fail V5.
These are dated smoke observations, not blanket certification or evidence
silently relabeled for a later commit. No full 25-requirement pass is claimed.

| Requirement | Current evidence / remaining gate |
| --- | --- |
| S1 | Historical live connector injection check passed; retain original dated evidence |
| S2 | Historical invalid-caller-key override check passed; retain original dated evidence |
| S3 | Live 2026-09-16: Chat Completions and Responses each completed with 50 text deltas spread over 2.00s and 1.66s respectively, using Qwen3-30B-A3B-Instruct-2507 |
| S4 | GET denials and one POST `/files` policy 403 observed; test policy remains intentionally narrower than the full proposed allowlist |
| S5 | Gateway emits attributed records in deployed code; actual records for this batch still need authorized inspection |
| S6 | Pinned MIT-derived adapter ran as owned Sprite service; confined real Claude edit/test round trip passed |
| B1 | Licenses, pinned dependencies, 165 offline tests and redacted Git/source secret scans pass; public GitHub CI not run |
| B2 | V5–V7 live checks passed; configuration dry-run/apply and byte-for-byte restoration verified |
| B3 | V8 passed; service create, idempotent start, stop/delete/recreate and configuration-off exercised |
| B4 | Gateway probes, permission-gated POST denial, evidence ledger/reconciliation and host capture scanner implemented; full cross-context collection/orchestration remains incomplete |
| B5 | Conditional quickstart, exact candidate installation pins and connector guide written; independent unaided-admin acceptance still required |
| B6 | Exact, attributable reconciliation tooling/guide implemented; live V10 result pending |
| L1 | Offline self-review and point-in-time dependency audit performed; independent security sign-off still required |
| L2 | Not published; requires explicit authorization |
| L3 | No outreach; requires explicit authorization and reviewed usage evidence |
| V1 | Host-only matcher and coverage checks tested with fake captures; actual before/after filesystem and all-process-environment collection not performed |
| V2 | Fresh laptop GET returned expected 401 at 07:23:26 UTC |
| V3 | Historical unlabeled-Sprite 403 recorded; no fresh rerun this implementation batch |
| V4 | Production connector Test returned 200, but Playground is development-gated; exact specified route remains blocked |
| V5–V7 | Passed scoped exact-OK checks above |
| V8 | Passed confined edit/test task, stream events and independent test validation above |
| V9 | One empty POST `/files` at 07:27:34–07:27:35 returned 403 with exact gateway policy error; independent no-dispatch evidence still needed |
| V10 | Earlier streaming responses reported 46 input / 102 output tokens, not authoritative gateway accounting; last accessible billing snapshot refreshed at 05:41 UTC, before those requests |

## Current state

All seven managed files were independently compared to their original bytes
after `configure --off`; all matched. Only our owned temporary adapter service
definitions were removed; runtime logs and private configuration backups remain.
The pinned agent prefix and reviewed checkout remain on the dedicated test
Sprite. No connector policy, labels, GitHub content or publication was changed.

The post-acceptance billing refresh was blocked by browser safety review on
private-account access grounds. Do not route around it; obtain authorization
for the usage-only view. A scoped production-log approval question is also open.

The earlier two-request allowance was consumed only by its original
Chat/Responses batch. Later native tests followed the user's instruction to
proceed with remaining acceptance; do not charge them against that exhausted
two-request budget or imply permission for unlimited future runs.

Approval flags in these tools are deliberate friction, not permission grants.
Obtain fresh authority for the exact target, execution and spending scope.
