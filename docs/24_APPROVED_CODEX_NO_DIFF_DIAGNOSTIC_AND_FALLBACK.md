# Approved Codex No-Diff Diagnostic and Deterministic Fallback

## Problem fixed

Earlier, after the user approved **Fix failed tests safely**, AstraHeal could show a generic message:

```text
No framework files were changed. Connect Codex CLI/fresh login, grant safe files through the human update section...
```

This was confusing because the same message appeared even when:

- the user had approved the runtime popup,
- Codex CLI was already connected,
- Codex executed successfully but returned a plan/explanation without editing files.

## New behavior

The apply step now separates these cases clearly:

1. Codex CLI is missing from the GUI backend PATH.
2. Codex CLI is present but the backend user session is not authenticated.
3. Codex patch execution failed.
4. Codex executed successfully but produced no file diff.
5. Codex no-diff was followed by a focused second patch attempt.
6. If still no diff, AstraHeal checks a conservative deterministic locator/actionability fallback for common BasePage/helper patterns.

## What the GUI/report now shows

The GUI and self-healing report include:

- backend Codex availability,
- login/status result,
- primary Codex attempt result,
- focused retry result,
- deterministic fallback result,
- changed files if a patch was applied,
- exact explanation if no patch was applied.

## Deterministic fallback scope

The fallback is intentionally conservative. It only patches known reusable helper patterns such as BasePage `assertVisible`, `locator.click`, or `locator.tap` when evidence is locator/actionability related. It does not skip tests, weaken assertions, or increase waits above 30 seconds.

All fallback changes still go through backup, policy validation, rollback, and failed-only rerun validation.
