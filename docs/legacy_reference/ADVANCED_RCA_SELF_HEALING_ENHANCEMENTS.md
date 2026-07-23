# Advanced RCA and Self-Healing Enhancements

This build strengthens Phase 5 without removing existing GUI, Docker, Codex/Ollama, Playwright MCP, dynamic crawl, reporting, or agent matrix features.

## What changed

- Added `failure-evidence.json` with failed tests, failure text, URL leakage, dynamic DOM candidates, and generated file context.
- Root Cause Agent now combines deterministic signals with optional Codex/Ollama reasoning.
- Self-Healing Agent now uses strict deterministic guardrails before applying patches.
- BasePage includes heal-aware helpers for full-page scroll, overlay dismissal, DOM stabilization, clickability, and text/href discovery.
- Locator factory supports fallback locators.
- Page methods are upgraded to use reusable heal-aware helpers instead of brittle direct visibility/click checks.
- GUI version labels were removed from visible UI.

## Strict healing rules

1. Never put raw locators directly in generated spec files.
2. Patch pageObjects first, then pages/BasePage reusable helpers.
3. Do not patch code for network, environment, auth, or data-unavailable failures.
4. Always back up changed files under `generated-playwright/reports/healing-backups/`.
5. Always run Static Review and then headed rerun after applying healing.

## Recommended flow

1. Execute generated test headed.
2. Open RCA & Self-Healing.
3. Click Analyze Root Cause.
4. Click Propose Self-Healing Fix.
5. Review `root-cause-report.json`, `failure-evidence.json`, and `self-healing-report.json`.
6. Click Apply Self-Healing Patch only when confidence and scope are acceptable.
7. Run Static Review.
8. Re-run headed, then headless.
