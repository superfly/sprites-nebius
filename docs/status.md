# Requirement-to-evidence checklist

Updated 18 September 2026. Live smoke success is not release/security sign-off.
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

| Requirement | Current evidence / remaining gate |
| --- | --- |
| S1 | Historical live connector injection check passed; retain original dated evidence |
| S2 | Historical invalid-caller-key override check passed; retain original dated evidence |
| S3 | Live 2026-09-16: Chat Completions and Responses each completed with 50 text deltas spread over 2.00s and 1.66s respectively, using Qwen3-30B-A3B-Instruct-2507 |
| S4 | GET denials and one POST `/files` policy 403 observed; test policy remains intentionally narrower than the full proposed allowlist |
| S5 | Authorized production inspection on September 17 found 12 unique completed usage records with the expected connector/Sprite attribution; server-side count also 12 |
| S6 | Pinned MIT-derived adapter ran as owned Sprite service; confined real Claude edit/test round trip passed |
| B1 | Repo, licenses and secret-scan CI implemented; 283-test gap-closure baseline at `4c82e1d` passed both private PR and push CI checks |
| B2 | V5–V7 live checks passed; configuration dry-run/apply and byte-for-byte restoration verified |
| B3 | V8 passed; service create, idempotent start, stop/delete/recreate and configuration-off exercised |
| B4 | Cross-context coordinator and streamed collector implemented with offline tests; approved live trial and V4/V10 operator-input boundary acceptance remain open |
| B5 | Conditional quickstart, exact candidate installation pins and connector guide written; independent unaided-admin acceptance still required |
| B6 | Reconciliation tooling/guide implemented; observed gateway and provider counts match, but full V10 prerequisites remain |
| L1 | Offline self-review and point-in-time dependency audit performed; independent security sign-off still required |
| L2 | Private repository/internal PR authorized; public release and ecosystem listing remain pending explicit authorization |
| L3 | No outreach; requires explicit authorization and reviewed usage evidence |
| V1 | Keyless streamed lifecycle collection and host-only matcher implemented; actual sensitive collection not authorized/run, scope/timing awaits security acceptance |
| V2 | Fresh laptop GET returned expected 401 at 07:23:26 UTC |
| V3 | Historical unlabeled-Sprite 403 recorded; no fresh rerun this implementation batch |
| V4 | Production connector Test returned 200, but omits model-list evidence; Playground is development-gated. Exact specified route or an explicitly accepted complete alternative remains required |
| V5–V7 | Passed scoped exact-OK checks above |
| V8 | Passed confined edit/test task, stream events and independent test validation above |
| V9 | One empty POST `/files` at 07:27:34–07:27:35 returned 403 with exact gateway policy error, satisfying the specified check; independent no-dispatch tracing is optional |
| V10 | Gateway: 27,100 input / 262 output tokens, exactly matching the recorded provider day view (0% difference). Project binding, aligned accounting windows and completeness/settlement still need confirmation |

## Current state

The gap-closure implementation adds one-command Bash/Zsh activation, tests of
actual configurator-written agent files, cross-context verification and a
non-persistent streamed scanner. No new live inference, real-key collection,
policy/label changes, independent acceptance or launch approval is implied.
The older live observations below are not evidence for these new code paths.
See [verification](verification.md) for permissions and remaining gates.

Local gap-closure validation on 18 September: 283 offline tests passed, including
local fixture HTTP servers, Bash/Zsh activation and streamed-capture fault tests.
All 17 installed dependencies are compatible; source secret scan and whitespace
checks passed. No live Sprite transport, native inference or real-key scan was
run for these changes. This is not independent security or unaided-admin sign-off.

Follow-up local acceptance guards on 18 September: **292 offline tests passed**
after explicitly disabling CLI startup retries and refusing stale/unrecorded
owned adapter source before reuse, readiness or a coordinated Claude run.
Fixture tests cover legacy cleanup without automatic restart. Source secret
scan, Bash/Zsh syntax and whitespace checks passed. These changes have no new
live evidence and do not close V1, V4, V10 or the independent acceptance gates.

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
