# Same-session multiple testcase generation fix

## Problem fixed

When a user generated Playwright for testcase1 and then uploaded testcase2 in the same GUI session, execution could fail with `Generated spec not found: ...test2.spec.ts`.

## Root cause

The runner expected `generated-playwright/tests/generated/<feature>.spec.ts` to already exist for the currently selected feature. If the user changed the feature/testcase and clicked Execute before the matching Playwright materialization completed, the runner returned a technical missing-file error instead of safely generating or guiding the user.

## Fix

- Each testcase generation now updates session project config for `feature`, `source_type`, provider, model, and base URL.
- Playwright generation records `.qa-cache/latest_playwright_generation.json`.
- Execution performs a deterministic precheck.
- If `<feature>.spec.ts` is missing but `<feature>.scenarios.json` exists, the framework auto-generates the missing spec before running Playwright.
- If neither testcase JSON nor spec exists, the GUI returns a simple actionable message with available specs.

## Existing features preserved

No change was made to the POM rule: spec -> pages -> pageObjects. No locator generation, self-healing, Docker, Codex/Ollama, or MCP behavior was removed.
