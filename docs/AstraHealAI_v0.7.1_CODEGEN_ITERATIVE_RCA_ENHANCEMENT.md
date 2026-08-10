# AstraHeal AI v0.7.1 — Codegen, Iterative Generation, and Stable RCA

## Purpose

This release makes repeated Playwright automation work predictable:

1. Load one or more functional testcases.
2. Optionally record a difficult testcase with Playwright Codegen.
3. Import the sanitized capture.
4. Generate framework-aligned specs, page methods, locators, and test data.
5. Run the tests.
6. Open the stable Plain-English RCA report for failures.
7. Create and approve a safe fix plan.
8. Rerun only failed tests.
9. Repeat with later testcase uploads without deleting earlier work.

## Supervised Playwright Codegen capture

The **Add New Tests into Existing Framework** tab now provides:

- **Optional A. Record selected testcase with Playwright Codegen**
- **Optional B. Stop & import Codegen capture**

The tester enters a testcase ID, starts Codegen, manually completes the AUT flow, adds useful assertions in Playwright Inspector, and then closes or imports the capture.

AstraHeal:

- starts `npx playwright codegen` inside the selected framework;
- stores the raw recording only inside `.aiqa-history/codegen-captures` during the session;
- removes typed credential values;
- deletes the raw recording after import;
- parses supported Playwright actions and locators;
- maps actions to the selected testcase;
- inserts real intermediate steps that were missing from the source testcase;
- saves an HTML/JSON capture report;
- uses imported Codegen evidence before AI/browser guesses.

Supported imported locator forms include:

- `getByRole`
- `getByTestId`
- `getByLabel`
- `getByPlaceholder`
- `getByText`
- CSS through `locator(...)`
- XPath through `locator(...)`

Supported actions include navigation, click, fill, selection, check/uncheck, keyboard actions, and common visibility/text/value assertions.

## Framework alignment and reuse

During generation, AstraHeal follows this order:

1. Reuse an existing page method whose locator and action match the Codegen evidence.
2. Reuse an existing locator definition whose strategy and value match.
3. Add a missing method to the strongest existing page class.
4. Add a missing locator to the strongest existing locator repository.
5. Create a support file only when the selected policy allows it and no suitable file exists.

Each generated spec is validated through the full contract:

```text
Spec call → page method → locator import → locator definition → supported strategy
```

## Multiple Codegen captures

Codegen is normally recorded one testcase at a time. Capturing TC_02 no longer overwrites the imported evidence for TC_01. The feature-level enhanced testcase file retains Codegen evidence for every previously captured scenario.

When a valid imported Codegen capture exists, the duplicate live AI browser-grounding pass is skipped. Codegen becomes the authoritative browser record; AI/browser grounding is used only for steps not covered by Codegen.

## Iterative testcase rounds

Generated spec names are stable. Regenerating the same scenario updates its existing spec instead of creating `-2`, `-3`, or similar duplicates.

A feature-level manifest is stored at:

```text
<framework>/.aiqa-history/add-new-tests/<feature>-scenario-manifest.json
```

The manifest merges later uploads with earlier scenarios:

- a new testcase ID is added;
- an existing testcase ID is updated;
- unrelated earlier testcase IDs remain available;
- the shared feature data module is regenerated from the cumulative manifest;
- timestamped generation reports preserve the history of each round.

## Stable Plain-English RCA report

The stable report endpoint is:

```text
GET /api/existing-framework/rca/plain-english/report
```

The endpoint always returns an HTML page:

- after RCA, it renders the persisted test-by-test explanation;
- before RCA, it explains which evidence exists and what button to click next;
- before any failed execution, it explains that tests must be run first.

The GUI no longer opens a guessed file path that can return `Detail not found`.

## Safe continuous flow

```text
Generate tests
  → structural validation
  → execute
  → collect actual evidence
  → explain failures
  → open Plain-English RCA
  → create safe fix plan
  → human approval
  → backup and patch
  → rerun failed tests
  → retain or roll back
```

The generator result and report include the stable Plain-English RCA URL and next-action guidance.

## Security

- Codegen credentials are removed from imported source.
- Raw Codegen files are deleted after import.
- Sanitized evidence is stored under `.aiqa-history`.
- Existing `.env` and secret handling remain unchanged.
- Generated patches still use backup, scope, validation, and rollback controls.
- The operation-abort control remains available for long Codegen, generation, execution, RCA, and repair work.

## Main implementation files

```text
qa_pipeline/modules/playwright_ts_generator/codegen_capture.py
qa_pipeline/modules/playwright_ts_generator/controller.py
qa_pipeline/modules/playwright_ts_generator/enterprise_add_new_tests.py
qa_pipeline/agents/existing_framework_control/controller.py
qa_pipeline/gui/app.py
qa_pipeline/gui/static/index.html
tests/test_codegen_capture_and_iteration.py
```
