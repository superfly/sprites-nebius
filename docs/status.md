# Tested compatibility and limitations

Last live run: **21 September 2026**, revision `fda0632`, using
`Qwen/Qwen3-30B-A3B-Instruct-2507` through a Sprites Custom API connector.
These are scoped smoke tests, not certification of other versions, models or
arbitrary coding tasks.

| Agent | Tested version | Observed result |
| --- | --- | --- |
| Codex | 0.154.0 | Exact `OK` |
| OpenCode | 1.18.31 | Exact `OK` |
| Pi | 0.85.1 | Exact `OK` |
| Claude Code | 2.1.273 | Confined file edit and streamed test-tool round trip, independently verified |

The coordinated run also passed connector authentication, caller-key
replacement, laptop/unlabeled-Sprite denial, incremental Chat Completions and
Responses streams, and the tested blocked-path checks. No operation was retried.
Configuration restoration and temporary service cleanup were independently
verified. All 299 offline tests passed locally and on the labeled Sprite.

## Credential-isolation evidence

The four agent captures and final filesystem/environment scan found no exact
key matches. The final scan covered 180,945 regular files and four live
environments, with no unreadable objects, detected races or cap hits.
The key stayed on the host and raw capture bytes were not retained.

This is evidence within a declared scope, not proof of universal key absence.
Symlinks/devices/virtual trees, memory, deleted files, xattrs, transformed copies
and later environment mutations are not fully covered. See
[scan scope](verification.md#credential-scan) before relying on the result.

## Known limitations

- The adapter supports text and custom tools, not every Anthropic feature.
  See [supported behaviour](../proxy/README.md#supported-behaviour-and-limits).
- Live tests used a narrower endpoint allowlist than the complete documented
  policy. Broader policy coverage and live cancellation remain unverified.
- The full verification result remains incomplete pending scan-scope acceptance,
  Playground evidence or an accepted alternative, and usage reconciliation for
  the 21 September batch. Evidence acquisition is not fully automated.
- A separately reviewed 18 September usage comparison matched exactly:
  21,851 input and 303 output tokens. It does not reconcile later runs or
  constitute a passing invocation of the strict whole-day importer.
- Independent security review and unaided administrator setup validation remain
  outstanding.

See [verification](verification.md) for reproducible checks and
[reconciliation](acceptance.md) for source and coverage requirements.
