## Summary

What changes for a sprites-nebius user, and why?

## Verification

- [ ] `.venv/bin/python scripts/check`
- [ ] `git diff --check`
- [ ] Documentation updated when behavior changed
- [ ] Regression test added for a bug fix or security boundary

## Safety review

- [ ] No credentials, private Sprite/connector identifiers or customer data included
- [ ] Existing configuration and service ownership are preserved
- [ ] New network requests, installations or billable operations require explicit opt-in

Live inference is not required for a PR. Describe any authorized live testing separately.
