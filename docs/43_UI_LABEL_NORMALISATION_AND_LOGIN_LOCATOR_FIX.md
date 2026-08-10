# UI label normalisation and login locator fix — v0.6.9

## Problem

Manual testcases often represent buttons as `<Log In to sandbox>`. The angle brackets are documentation notation. They are not part of the DOM text or accessible name. Earlier builds generated locator candidates whose literal value was `<Log In to sandbox>`, so Playwright correctly found zero matching elements.

## Fix

The generation pipeline now normalises UI labels in three independent layers:

1. Testcase instruction normalisation removes documentation-only wrappers while preserving Gherkin outline placeholders until examples are expanded.
2. Provisional and browser-verified locator generation canonicalises the final value. `Log in to sandbox`, `Login to Sandbox`, and `<Log In to sandbox>` become `Log In to Sandbox`.
3. SmartLocator normalises existing candidate values at runtime, so older generated definitions with angle brackets can still resolve after the runtime utility is updated.

## Login candidates

For `Log In to Sandbox`, the generated locator repository now includes:

- `getByRole('button', { name: /Log\s*In\s+to\s+Sandbox/i })`
- link and visible-text alternatives
- `#Login`
- `input[name="Login"]`
- `input[type="submit"][value*="sandbox" i]`
- title and ARIA-label fallbacks

## Validation

The Page Object contract gate now reports `malformed_locator_value` when a locator repository still contains a value wrapped in `<...>`. Such source is rejected before live execution.

## Diagnostics

SmartLocator failure messages now include normalised candidates plus per-candidate element count and visibility evidence. This distinguishes a wrong accessible name from an element that exists but is hidden or delayed.
