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

### Latest approved agent batch

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
declared scope and reached the approved **4 GiB byte cap**, so **V1 remains
inconclusive**. This is point-in-time evidence for the new test key, not proof
about historical agent executions or a complete filesystem scan.

The standalone wrapper completed successfully; its exit zero does not mean V1
passed. The allowance is consumed. Further collection needs a reviewed budget
and fresh permission; increasing the current 4 GiB implementation ceiling also
requires code review and tests. Private resource identifiers, source hashes and
metadata-only checkpoints remain outside this repository.

| Requirement | Current evidence / remaining gate |
| --- | --- |
| S1 | Historical live connector injection check passed; retain original dated evidence |
| S2 | Historical invalid-caller-key override check passed; retain original dated evidence |
| S3 | Fresh `b880115` batch above: Chat Completions and Responses each completed with 50 deltas spread over approximately 1.83s |
| S4 | GET denials and one POST `/files` policy 403 observed; test policy remains intentionally narrower than the full proposed allowlist |
| S5 | Authorized production inspection on September 17 found 12 unique completed usage records with the expected connector/Sprite attribution; server-side count also 12 |
| S6 | Fresh `b880115` owned service/source readiness and confined Claude edit/test round trip passed |
| B1 | Repo, licenses and secret-scan CI implemented; 283-test gap-closure baseline at `4c82e1d` passed both private PR and push CI checks |
| B2 | V5–V7 passed at `b880115` using real configurator-written files; normal sourced on/off and restoration verified |
| B3 | V8 and normal sourced activation/service readiness/restoration passed at `b880115`; previous service lifecycle observations remain dated evidence |
| B4 | Cross-context coordinator and streamed collector implemented with offline tests; standalone collection exercised live, but the complete coordinator trial and V4/V10 operator-input boundary acceptance remain open |
| B5 | Conditional quickstart, exact candidate installation pins and connector guide written; independent unaided-admin acceptance still required |
| B6 | Reconciliation tooling/guide implemented; observed gateway and provider counts match, but full V10 prerequisites remain |
| L1 | Offline self-review and point-in-time dependency audit performed; independent security sign-off still required |
| L2 | Private repository/internal PR authorized; public release and ecosystem listing remain pending explicit authorization |
| L3 | No outreach; requires explicit authorization and reviewed usage evidence |
| V1 | Authorized point-in-time scan at `826a930` found no matches but hit its 4 GiB cap; incomplete coverage is inconclusive, not a pass |
| V2 | Standalone laptop GET returned expected 401 on 18 September at 03:34:58 UTC, using the verifier from `826a930` |
| V3 | Standalone unlabeled-Sprite GET returned expected 403 on 18 September at 03:39:20 UTC, using the verifier from `826a930` |
| V4 | Production connector Test returned 200, but omits model-list evidence; Playground is development-gated. Exact specified route or an explicitly accepted complete alternative remains required |
| V5–V7 | Fresh scoped exact-OK checks passed at `b880115` |
| V8 | Fresh confined edit/test task, five stream deltas and independent test passed at `b880115` |
| V9 | Fresh single empty POST `/files` at 01:58:53 UTC returned 403 with the expected gateway policy error; independent no-dispatch tracing is optional |
| V10 | Gateway: 27,100 input / 262 output tokens, exactly matching the recorded provider day view (0% difference). Project binding, aligned accounting windows and complete usage coverage still need confirmation; financial settlement is not required |

## Current state

The gap-closure implementation adds one-command Bash/Zsh activation, tests of
actual configurator-written agent files, cross-context verification and a
non-persistent streamed scanner. The approved batches above supply live
evidence for activation, isolated native-agent/probe paths and bounded
standalone collection, not the full coordinator or complete V1 coverage.
Independent acceptance and launch approval remain outstanding.
See [verification](verification.md) for permissions and remaining gates.

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
