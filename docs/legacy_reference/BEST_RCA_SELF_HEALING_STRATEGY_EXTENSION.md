# Best RCA and Self-Healing Strategy Extension

This extension is additive. It enhances the RCA/self-healing layer only and does not replace the existing requirement ingestion, testcase generation, reusable Playwright generation, execution, reporting, or existing-framework-control paths.

## 1. Target operating model

Use this fixed order:

```text
Full/selected execution
  -> detect failed tests only
  -> collect evidence bundle
  -> classify RCA with deterministic multi-signal rules
  -> decide whether healing is safe
  -> generate minimal patch only in allowed layers
  -> validate policy + confidence
  -> typecheck/lint/failed-only rerun
  -> merge healed result into original report
  -> feed accepted patch into selector vault/learning store
```

Never allow the AI to modify code simply because a test failed. RCA must decide whether healing is allowed.

## 2. Evidence bundle required for real RCA

For every failed test, collect as many of these as available:

- Playwright error text
- trace.zip
- screenshot-before-failure/failure screenshot
- video.webm
- console logs
- network HAR or network-events.json
- page URL
- DOM snapshot
- failed locator metadata
- browser/context permissions
- popup/dialog events
- test data or seed snapshot
- retry number and cross-run history

## 3. Multi-signal classification

The classifier should use these signals together rather than error string alone:

| Signal | Purpose | Healing outcome |
|---|---|---|
| DOM snapshot diff | Detect selector/markup drift | Patch pageObjects/locator vault |
| Trace replay/timing | Detect too-early/too-late actions | Patch safe action/wait/navigation helpers |
| Network HAR diff | Detect API/schema/status change | Block UI healing or patch exact API wait only |
| Fixture/seed diff | Detect changed data state | Reconcile seed/test data before code patch |
| Cross-run flakiness | Detect intermittent infra/timing noise | Patch deterministic waits or mark flaky env |
| Assertion drift classifier | Distinguish cosmetic copy from behavior regression | Block assertion patch below threshold |

## 4. Healing policy gate

The new deterministic policy lives at:

```text
configs/self-healing-policy.json
qa_pipeline/agents/phase5_failure_healing/healing_policy.py
```

Default policy:

- max healing attempts per same failure: 2
- minimum patch proposal confidence: 0.70
- minimum auto-apply confidence: 0.80
- assertion semantic threshold: 0.30
- force click disabled by default
- assertion changes disabled by default
- raw locators in specs disabled by default
- failed-only rerun required

## 5. Allowed and blocked patch zones

Allowed normally:

```text
pageObjects/*.ts
pages/*.ts
utils/*.ts
fixtures/*.ts
testData/*.json|yaml
qa-ai-support/*
```

Manual approval required:

```text
tests/*.spec.ts
playwright.config.ts
package.json
assertion lines
business expected-result changes
```

Blocked anti-patterns:

```text
test.skip
test.fixme
.only
waitForTimeout
force: true by default
expect.soft as a way to hide failure
raw locator additions inside specs
```

## 6. Failure category to healing strategy

| RCA category | Healing strategy | Patch location |
|---|---|---|
| Locator not found | Rediscover semantic locator, prefer testId/role/label | pageObjects |
| Strict locator ambiguity | Scope locator with parent/filter/exact accessible name | pageObjects |
| Element disabled | Diagnose missing input/API/role/session; do not force click | pages/fixtures/testData |
| Element not interactable | Close overlay, scroll, wait visible/enabled/stable | utils/safeActions/pages |
| Unexpected popup | Update central popup/dialog handler | utils/fixtures |
| Browser permission | Configure context/project permission profile | fixtures/config |
| Network/API | Patch exact API wait only if API healthy; otherwise product/env issue | pages/fixtures/testData |
| Assertion failure | Manual review unless cosmetic drift passes threshold | manual review |
| iframe/shadow DOM | Use frameLocator or shadow-safe locator | pageObjects |
| Timing/flakiness | Replace sleeps with web-first/API waits | pages/utils |

## 7. TypeScript support utilities

Added reusable support files:

```text
generated-playwright/utils/popupHandler.ts
generated-playwright/utils/dialogHandler.ts
generated-playwright/utils/safeActions.ts
generated-playwright/utils/networkEvidence.ts
```

These files are additive. Existing specs do not need to be rewritten immediately. New or healed page methods should prefer these utilities.

## 8. Step-by-step GUI execution

1. Start GUI.
2. Run the existing pipeline normally, or open Existing Framework Control.
3. Execute the full suite or selected existing framework specs.
4. Let the runner produce `failed-tests.json`.
5. Run RCA.
6. Review the structured RCA JSON and auditable RCA summary.
7. Generate a patch proposal.
8. Apply only when policy and confidence gates pass.
9. Rerun failed tests only.
10. Open the consolidated report showing original failed -> healed passed/still failed.
11. Generate Selector Health Report nightly or before sprint review.

## 9. CLI examples

```bash
python -m qa_pipeline.cli existing-framework-rca --framework-path generated-playwright --provider deterministic
python -m qa_pipeline.cli existing-framework-heal --framework-path generated-playwright --provider codex --apply
python -m qa_pipeline.cli existing-framework-rerun-failed --framework-path generated-playwright --project chromium
python -m qa_pipeline.cli existing-framework-selector-health --framework-path generated-playwright
```

## 10. Human approval cases

Always require review when:

- assertion value changes
- API/HAR contract changed
- fixture/seed changed
- product returns 401/403/500
- patch touches spec/config/package files
- confidence is below 0.80
- same failure already consumed 2 healing attempts
- patch contains sleeps, skips, `.only`, or force-click

## 11. Final reporting expectation

The original report must be enriched, not replaced:

```text
Total scripts
Passed first attempt
Failed first attempt
Healed and passed after retry
Still failed after healing
Product/env/data issue
Manual review required
```
