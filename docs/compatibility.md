# Compatibility

The following versions passed scoped live checks with
`Qwen/Qwen3-30B-A3B-Instruct-2507` through a Sprites Custom API connector on
21 September 2026:

| Agent | Version | Tested behaviour |
| --- | --- | --- |
| Codex | 0.154.0 | Text generation through Responses |
| OpenCode | 1.18.31 | Text generation |
| Pi | 0.85.1 | Text generation through Chat Completions |
| Claude Code | 2.1.273 | File edit and streamed tool round trip through the local adapter |

These are smoke tests, not certification of other versions, models or arbitrary
coding tasks. The newer `setup-nebius-*` onboarding scripts have offline test
coverage but have not yet been exercised end-to-end on a live Sprite.

## Limitations

- Model discovery means a model is available, not that it supports the selected
  agent's protocol, reasoning or tool use. Start with a tested combination.
- The Claude adapter supports text and custom tools, not every Anthropic
  feature. See [supported behaviour](../proxy/README.md#supported-behaviour-and-limits).
- Project settings, hooks and extensions can override user-level routing.
  Test in a clean project before relying on an existing agent configuration.
- Connector labels and endpoint restrictions are access controls, not token
  quotas or spending caps. Agents can make multiple paid requests.
- Cancellation is covered by offline tests; live gateway/provider cancellation
  and broader endpoint-policy coverage remain unverified.

This toolkit has not had an independent security review. Keep provider keys
outside the Sprite and follow the [connector setup guidance](connector-setup.md).
