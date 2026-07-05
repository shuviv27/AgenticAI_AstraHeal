# Existing Playwright Framework Control Guide

## Purpose

This enhancement adds a second execution path for teams that already have a Playwright TypeScript automation framework.

The original AI QA pipeline remains unchanged:

```text
Jira/SRS/PDF/Confluence/Test Management input
→ functional testcase generation
→ reusable Playwright generation
→ execution
→ RCA/self-healing
→ failed-only rerun
```

The new existing-framework path bypasses the first three generation steps:

```text
Existing Playwright framework folder from GUI
→ framework understanding / intelligence scan
→ execute existing specs in-place
→ failed-spec inventory
→ RCA/self-healing on failed specs only
→ failed-only rerun with consolidated report
```

Use this mode when your framework already has specs, pages, page objects, fixtures, utilities, and test data.

## What Was Added

### Backend agent

New module:

```text
qa_pipeline/agents/existing_framework_control/controller.py
```

Responsibilities:

- Validates the user-provided framework path.
- Detects `package.json`, Playwright config, package manager, scripts, spec files, `pages`, `pageObjects`, fixtures, utilities and test data folders.
- Builds `framework-intelligence.json` and `framework-intelligence.md`.
- Executes the existing framework in-place without copying it into `generated-playwright`.
- Copies Playwright HTML/JSON artifacts into GUI-accessible artifact paths.
- Writes a failed-only inventory for existing-framework runs.
- Performs RCA using failed specs only.
- Builds a strict patch scope from failed specs and imported page/pageObject/helper files.
- Uses Codex CLI for guarded self-healing patches when requested.
- Reruns only failed specs after patching and produces a consolidated report.

### GUI

New left-menu item:

```text
Existing Framework Control
```

Main GUI actions:

- **Understand Framework**
- **Execute Existing - Headless**
- **Execute Existing - Headed**
- **Show Failed Inventory**
- **Analyze Existing RCA**
- **Propose Existing Fix**
- **Apply Existing Patch**
- **Re-run Existing Failed Only - Headed/Headless**

### API endpoints

```text
POST /api/existing-framework/analyze
POST /api/existing-framework/execute
POST /api/existing-framework/failure/analyze
POST /api/existing-framework/self-heal/propose
POST /api/existing-framework/self-heal/apply
POST /api/existing-framework/execute/failed-only
GET  /api/existing-framework/failed-inventory
```

### CLI commands

```bash
python -m qa_pipeline.cli existing-framework-analyze \
  --framework-path /path/to/playwright-framework \
  --provider deterministic \
  --base-url https://your-app-url

python -m qa_pipeline.cli existing-framework-execute \
  --framework-path /path/to/playwright-framework \
  --project chromium \
  --base-url https://your-app-url

python -m qa_pipeline.cli existing-framework-rca \
  --framework-path /path/to/playwright-framework \
  --provider codex \
  --base-url https://your-app-url

python -m qa_pipeline.cli existing-framework-heal \
  --framework-path /path/to/playwright-framework \
  --provider codex \
  --base-url https://your-app-url

python -m qa_pipeline.cli existing-framework-heal \
  --framework-path /path/to/playwright-framework \
  --provider codex \
  --base-url https://your-app-url \
  --apply

python -m qa_pipeline.cli existing-framework-rerun-failed \
  --framework-path /path/to/playwright-framework \
  --project chromium \
  --base-url https://your-app-url
```

## GUI Usage

1. Start the existing GUI as usual:

   ```bash
   ./START_GUI_MAC.sh
   # or Windows:
   .\START_GUI_WINDOWS.ps1
   ```

2. Open:

   ```text
   http://127.0.0.1:8080
   ```

3. Go to **Project Setup** and save the application URL.

4. Go to **Existing Framework Control**.

5. Paste the root folder of your already-developed Playwright framework.

   Examples:

   ```text
   C:\repos\my-playwright-framework
   /Users/me/repos/my-playwright-framework
   /home/me/repos/my-playwright-framework
   ```

6. Click **Understand Framework**.

7. Click **Execute Existing - Headless** or **Execute Existing - Headed**.

8. If tests fail, click **Analyze Existing RCA**.

9. Click **Propose Existing Fix** to review the patch plan.

10. Click **Apply Existing Patch** only after review. This uses Codex CLI and backs up scoped files before patching.

11. Click **Re-run Existing Failed Only**. The system reruns only the specs that failed in the previous full execution and creates a consolidated original + rerun report.

## Optional Spec Targeting

Leave **Optional spec targets / patterns** blank to run the existing framework default.

To run selected specs, add one per line:

```text
tests/login.spec.ts
tests/checkout.spec.ts
```

## Optional Custom Command

Leave **Optional custom test command** blank to use the default command:

```bash
npx --no-install playwright test <targets> --project=<browser> --workers=1 --reporter=line,json,html
```

Use a custom command when your framework has a custom npm script:

```text
npm run test:e2e -- {targets}
```

The `{targets}` placeholder is replaced with the selected spec paths.

## Guardrails

The existing-framework flow follows the same safety model as the generated flow:

- Requirement parsing, testcase generation and generated-code creation are bypassed.
- The user framework is executed in-place.
- The framework is not copied into `generated-playwright`.
- RCA reads exact failed specs only from Playwright JSON/stdout evidence.
- If the failed spec cannot be identified, RCA blocks instead of assuming all specs failed.
- Self-healing scope is restricted to failed specs and imported page/pageObject/helper files.
- Backups are created before Codex applies patches.
- Page Object Model is preserved: specs should call page methods; page methods should use pageObjects/locator definitions.
- Already-passed specs are not patched or rerun during failed-only validation.

## Artifacts

GUI-accessible artifacts are written under:

```text
generated-playwright/reports/existing-framework/
```

Important files:

```text
generated-playwright/reports/existing-framework/framework-intelligence.json
generated-playwright/reports/existing-framework/framework-intelligence.md
generated-playwright/reports/existing-framework/execution-report.json
generated-playwright/reports/existing-framework/failed-tests.json
generated-playwright/reports/existing-framework/root-cause-report.json
generated-playwright/reports/existing-framework/self-healing-report.json
generated-playwright/reports/existing-framework/html/index.html
generated-playwright/reports/existing-framework/consolidated-report.html
```

Backups are stored under:

```text
.qa-cache/existing-framework/backups/
```

## Why This Does Not Disturb Existing Features

This enhancement is additive:

- Existing SRS/Jira/PDF testcase generation endpoints are unchanged.
- Existing generated Playwright execution endpoints are unchanged.
- Existing RCA/self-healing endpoints are unchanged.
- Existing failed-only rerun behavior is unchanged.
- New functionality is isolated under `existing_framework_control` and `/api/existing-framework/*`.


## Robust RCA & Self-Healing Strategy Added in This Build

The previous implementation already used failed-only scope enforcement. This build strengthens the RCA layer so it does not classify failures from the Playwright error string alone.

### New RCA principle

The RCA engine now evaluates six auditable signals:

1. **DOM snapshot diff** — detects markup, attribute, role, test id, and locator surface changes.
2. **Playwright trace replay/timing signal** — detects actions that fired too early, too late, or against non-actionable elements.
3. **Network HAR diff** — detects API status/schema/contract changes that should not be healed as a UI selector issue.
4. **Fixture/seed diff** — detects data changes between passing and failing runs.
5. **Cross-run flakiness frequency** — separates consistent regressions from intermittent environment noise.
6. **Assertion drift classifier** — blocks dangerous assertion updates unless the text/value drift looks cosmetic.

The generated audit report is written to:

```text
generated-playwright/reports/existing-framework/robust-rca/auditable-rca-chain.html
generated-playwright/reports/existing-framework/robust-rca/auditable-rca-chain.md
generated-playwright/reports/existing-framework/robust-rca/multi-signal-evidence.json
```

This report is an auditable decision summary, not hidden model chain-of-thought.

### RCA chain mapping

| RCA signal | Primary classification | Healing strategy |
|---|---|---|
| DOM snapshot diff + locator failure | Selector or DOM drift | Patch pageObjects/locator vault first, then page methods. Prefer `getByRole`, `getByTestId`, `getByLabel`; CSS/XPath only when justified. |
| Trace timing/actionability | Action too early/late, overlay, viewport, detached element | Patch reusable waits, `safeClick`, overlay dismissal, scroll/retry, navigation helper. |
| HAR status/schema diff | Backend/API contract drift | Block UI patch. Raise PR comment with before/after API evidence and validate API/test data. |
| Fixture/seed diff | Data or seeded state changed | Block code patch until fixture/data baseline is reconciled or approved. |
| Cross-run intermittent failures | Flakiness/environment noise | Patch reusable wait/actionability helpers only; avoid assertion updates. |
| Assertion drift below threshold | Possible behavioral regression | Block auto-heal. Require human review with expected/received values. |

### Assertion drift gate

Before changing an assertion, the system extracts expected/received values and computes a semantic similarity score.

Default rule:

```text
similarity < 0.30  → block auto-heal
behavioral/numeric/business-critical value seen → block auto-heal
similarity >= 0.30 and cosmetic copy drift only → may propose assertion update
```

Examples that are blocked:

```text
Expected: Approved
Received: Declined

Expected: Total $100
Received: Total $120

Expected: Checkout success
Received: Payment failed
```

Examples that may be allowed with review:

```text
Expected: Sign in
Received: Log in

Expected: Get started now
Received: Get started
```

### Second-stage confidence gate

When Codex applies a patch, the system now performs a second diff review.

Rule:

```text
patch confidence >= 0.80 → patch may remain applied and failed-only rerun becomes pending
patch confidence < 0.80  → patch is restored from backup and human approval is required
```

This prevents accidental broad rewrites, assertion deletion, unrelated spec edits, or low-confidence selector guesses.

### Feedback loop and selector vault

Accepted auto patches are recorded in:

```text
.qa-cache/existing-framework/robust-rca/healing-feedback.jsonl
.qa-cache/existing-framework/robust-rca/selector-vault.json
```

This gives the system memory across sprints. The selector vault captures accepted healing decisions, confidence, changed files, and the selected RCA chain so repeated failures can be classified faster and safer later.

### Optional TypeScript robust harness for existing frameworks

The GUI now includes **Install Robust TS Harness**. It additively creates:

```text
<your-framework>/qa-ai-support/SmartLocator.ts
<your-framework>/qa-ai-support/testTelemetry.fixture.ts
<your-framework>/qa-ai-support/README.md
```

It does not rewrite existing specs. Teams can adopt it gradually.

Recommended adoption pattern:

```ts
// Before
import { test, expect } from '@playwright/test';

// After
import { test, expect } from '../qa-ai-support/testTelemetry.fixture';
```

Recommended SmartLocator usage inside page/pageObject layers:

```ts
import { SmartLocator } from '../qa-ai-support/SmartLocator';

await new SmartLocator(page, [
  { strategy: 'testId', value: 'login-submit' },
  { strategy: 'role', role: 'button', value: 'Login' },
  { strategy: 'text', value: 'Sign in' },
], 'login submit').click();
```

The telemetry fixture writes failure bundles to:

```text
failures/run-{timestamp}/{testId}/
```

Each bundle includes:

```text
failure.png
dom-snapshot.html
network-events.har
network-events.json
trace.zip
url.txt
```

These bundles become the input for robust RCA.

### Nightly Selector Health Report

The GUI now includes **Selector Health Report**. It creates:

```text
generated-playwright/reports/existing-framework/selector-health-report.html
generated-playwright/reports/existing-framework/selector-health-report.json
```

The report shows:

- stability score per spec/component
- failure frequency trend
- heal frequency trend
- shortlist of components that need better testability hooks

This turns Codex CLI from a one-time repair utility into a continuous quality feedback loop.

## End-to-End Robust Flow from Beginning to End

### Step 1 — Start the GUI

```bash
./START_GUI_MAC.sh
# or Windows:
.\START_GUI_WINDOWS.ps1
```

Open:

```text
http://127.0.0.1:8080
```

### Step 2 — Configure project URL and AI provider

In **Project Setup**:

1. Save the application base URL.
2. Select Codex CLI for patch application.
3. Keep deterministic/Ollama for proposal-only mode when you do not want file changes.

### Step 3 — Open Existing Framework Control

Paste the root of your already-developed Playwright framework.

Example:

```text
C:\repos\enterprise-playwright-framework
/Users/you/repos/enterprise-playwright-framework
```

### Step 4 — Understand Framework

Click **Understand Framework**.

The system scans:

- package manager
- `package.json`
- Playwright config
- specs
- pages
- pageObjects
- fixtures
- utilities
- test data
- inline locator risk
- POM compliance

Output:

```text
generated-playwright/reports/existing-framework/framework-intelligence.json
generated-playwright/reports/existing-framework/framework-intelligence.md
```

### Step 5 — Install optional robust TS harness

Click **Install Robust TS Harness**.

This step is optional but strongly recommended. It gives the framework built-in failure bundles and SmartLocator adoption without rewriting current specs.

### Step 6 — Execute existing framework

Click:

```text
Execute Existing - Headless
```

or:

```text
Execute Existing - Headed
```

The system bypasses requirement parsing, testcase generation, and generated-script creation.

Output:

```text
generated-playwright/reports/existing-framework/execution-report.json
generated-playwright/reports/existing-framework/failed-tests.json
generated-playwright/reports/existing-framework/html/index.html
```

### Step 7 — Run robust RCA

If one or more specs fail, click **Analyze Existing RCA**.

The engine now does this sequence:

1. Reads `failed-tests.json`.
2. Resolves failed specs only.
3. Builds patch scope from failed specs and imported files only.
4. Collects DOM/trace/HAR/fixture/flakiness evidence.
5. Runs assertion drift classifier.
6. Selects a healing strategy.
7. Writes auditable RCA chain.

Output:

```text
generated-playwright/reports/existing-framework/root-cause-report.json
generated-playwright/reports/existing-framework/robust-rca/auditable-rca-chain.html
```

### Step 8 — Propose fix

Click **Propose Existing Fix**.

This produces a repair plan without changing files.

Use this when:

- the failure looks like API/data/assertion drift
- the team needs approval
- Codex credentials are not available
- you want to review before applying patches

### Step 9 — Apply gated fix

Click **Apply Existing Patch**.

The system:

1. Re-runs robust RCA.
2. Blocks patching if HAR/data/assertion gates say human review is required.
3. Backs up scoped files.
4. Allows Codex to patch only failed-scope files.
5. Creates diff against backup.
6. Runs second-stage confidence review.
7. Keeps patch only if confidence is at least `0.80`.
8. Reverts patch if confidence is below `0.80`.
9. Records accepted patch in the selector vault.

### Step 10 — Rerun failed only

Click:

```text
Re-run Existing Failed Only - Headless
```

or:

```text
Re-run Existing Failed Only - Headed
```

Only the original failed specs are rerun. The original full report is archived.

Output:

```text
generated-playwright/reports/existing-framework/consolidated-report.html
```

This report preserves the original result matrix:

```text
Passed first run → not rerun
Failed first run → passed after healing
Failed first run → still failing after healing
```

### Step 11 — Generate Selector Health Report

Click **Selector Health Report** after one or more runs.

Use this report in sprint retrospectives to find:

- unstable pages/components
- high-heal selectors
- specs with inline locator risk
- places where developers should add `data-test`/ARIA hooks

## CLI Commands for Robust Flow

```bash
python -m qa_pipeline.cli existing-framework-analyze \
  --framework-path /path/to/framework \
  --provider deterministic \
  --base-url https://your-app

python -m qa_pipeline.cli existing-framework-install-harness \
  --framework-path /path/to/framework

python -m qa_pipeline.cli existing-framework-execute \
  --framework-path /path/to/framework \
  --project chromium \
  --base-url https://your-app

python -m qa_pipeline.cli existing-framework-rca \
  --framework-path /path/to/framework \
  --provider deterministic \
  --base-url https://your-app

python -m qa_pipeline.cli existing-framework-heal \
  --framework-path /path/to/framework \
  --provider codex \
  --base-url https://your-app

python -m qa_pipeline.cli existing-framework-heal \
  --framework-path /path/to/framework \
  --provider codex \
  --base-url https://your-app \
  --apply

python -m qa_pipeline.cli existing-framework-rerun-failed \
  --framework-path /path/to/framework \
  --project chromium \
  --base-url https://your-app

python -m qa_pipeline.cli existing-framework-selector-health \
  --framework-path /path/to/framework
```

## CI/Nightly Recommendation

Add a nightly job with this sequence:

```bash
python -m qa_pipeline.cli existing-framework-execute \
  --framework-path $PLAYWRIGHT_FRAMEWORK_PATH \
  --project chromium \
  --base-url $BASE_URL

python -m qa_pipeline.cli existing-framework-rca \
  --framework-path $PLAYWRIGHT_FRAMEWORK_PATH \
  --provider deterministic \
  --base-url $BASE_URL || true

python -m qa_pipeline.cli existing-framework-selector-health \
  --framework-path $PLAYWRIGHT_FRAMEWORK_PATH
```

Publish these artifacts:

```text
generated-playwright/reports/existing-framework/html/index.html
generated-playwright/reports/existing-framework/robust-rca/auditable-rca-chain.html
generated-playwright/reports/existing-framework/selector-health-report.html
```
