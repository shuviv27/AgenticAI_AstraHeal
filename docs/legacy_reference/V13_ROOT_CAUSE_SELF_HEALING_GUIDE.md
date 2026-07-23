# v13 Root Cause and Self-Healing Guide

This build adds production-guarded Phase 5 agents without breaking the existing GUI pipeline.

## Added agents

- Failure Analysis Agent
- Root Cause Agent
- Self-Healing Agent

The attached enterprise architecture expects failure intelligence, self-healing, RCA, reporting, drift/maintenance, and model validation to be part of the agent plane. v13 makes the Phase 5 agents visible and callable from the GUI while keeping strict safety rules.

## What RCA checks

The Root Cause Agent reads:

- `generated-playwright/reports/results.json`
- `generated-playwright/reports/playwright-mcp-execution.json`
- `generated-playwright/reports/dynamic-dom-map.json`
- screenshots/videos/traces metadata
- generated spec/page/pageObject files

It classifies failures into:

- wrong application URL such as `127.0.0.1` or `localhost`
- locator not found or unstable
- clickability, overlay, scroll, or viewport issue
- sync/navigation issue
- browser permission issue
- environment/network issue
- unknown/manual review

## What Self-Healing can patch

Safe automatic patches are limited to:

- replacing wrong localhost URLs with the GUI project `base_url`
- adding locator fallback support in `generated-playwright/utils/locatorFactory.ts`
- adding heal-aware scrolling/clickability helpers in `generated-playwright/pages/BasePage.ts`
- preparing DOM candidate evidence from a full-page crawl

It does **not** add raw locators inside generated specs.

## Strict rules

1. Specs must call page methods only.
2. Page methods must use `pageObjects` locators.
3. Back up every changed file before patching.
4. Run dynamic DOM crawl before locator repair.
5. Run static review after patching.
6. Do not auto-apply low-confidence multi-file changes.

## GUI flow

1. Run a generated Playwright test.
2. If it fails, open **RCA & Self-Healing**.
3. Click **Analyze Root Cause**.
4. Click **Propose Self-Healing Fix**.
5. Review the plan in Reports → RCA / Self-Healing.
6. Click **Apply Self-Healing Patch** only if the proposal is acceptable.
7. Click **Static Review**.
8. Re-run test headed first, then headless.

## API endpoints

- `POST /api/failure/analyze`
- `POST /api/self-heal/propose`
- `POST /api/self-heal/apply`

## Artifacts

- `generated-playwright/reports/root-cause-report.json`
- `generated-playwright/reports/root-cause-report.md`
- `generated-playwright/reports/self-healing-report.json`
- `generated-playwright/reports/self-healing-report.md`
- `generated-playwright/reports/healing-backups/`

## Important note

AI/Codex/Ollama can improve the explanation and patch guidance, but deterministic guardrails still control what files are changed. This prevents unsafe AI output from corrupting the Playwright framework.
