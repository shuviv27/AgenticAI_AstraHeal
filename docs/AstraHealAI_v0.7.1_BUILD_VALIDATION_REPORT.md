# AstraHeal AI v0.7.1 — Build Validation Report

**Build:** `0.7.1`  
**Validation date:** 29 July 2026  
**Purpose:** Stable Plain-English RCA, supervised Playwright Codegen import, framework-aware refactoring, and repeatable iterative test rounds.

## Result

The repository-level regression suite passed.

```text
Automated tests:                     99 passed
Python source compilation:           Passed
GUI JavaScript syntax:               Passed
FastAPI application import:          Passed
Registered FastAPI routes:           179
Required new routes:                 Present
Attached-workbook integration:       Passed
Two-round cumulative generation:     Passed
Page Object contract issues:         0
Codegen credential masking:          Passed
Operation cancellation regressions: Passed
SQLite distributable state:          Reset before packaging
```

## New workflow validation

### Stable Plain-English RCA

Validated:

- stable HTML endpoint registration;
- report generation when detailed RCA exists;
- explanatory fallback when execution evidence exists but RCA has not run;
- explanatory fallback when no failed execution evidence exists;
- no direct GUI dependency on a guessed artifact file path.

Endpoint:

```text
GET /api/existing-framework/rca/plain-english/report
```

### Playwright Codegen capture and import

Validated:

- parsing of `goto`, `click`, `fill`, `selectOption`, check/uncheck, keyboard actions, and common assertions;
- `getByRole`, `getByTestId`, `getByLabel`, `getByPlaceholder`, `getByText`, CSS, and XPath conversion;
- credential masking before persisted capture evidence is written;
- deletion of the raw recording after import;
- insertion of a missing multi-page login transition in the correct order;
- preservation of earlier scenario captures when later testcase IDs are recorded;
- authoritative Codegen capture skipping a duplicate live browser-grounding pass;
- exact existing locator and page-method reuse before new code is created.

A private AUT was not available in the validation environment. The interactive `npx playwright codegen` browser session must receive one smoke test on the target Central VM/VDI with AUT access.

### Iterative testcase rounds

The attached workbook was normalized into ten scenarios and generated in an isolated framework copy. A second simulated upload containing three additional testcase IDs was then generated.

```text
First-round generated specs:        10
Imported Codegen actions:            5
Codegen evidence used:              Yes
Second-round generated specs:        3
Cumulative scenario manifest:       13
Page Object contract issues:         0
```

Validated:

- stable spec filenames;
- update-in-place for an existing testcase ID;
- no `-2.spec.ts` / `-3.spec.ts` duplicate growth;
- retention of earlier testcase data;
- addition of later testcase IDs;
- timestamped per-round reports;
- cumulative feature data regeneration;
- safe rollback support for invalid structural changes.

## Existing capability regression coverage

The 99-test suite covers:

- Excel/document testcase normalization;
- credential redaction and volatile credential profiles;
- framework discovery and nested Playwright layouts;
- page-object and locator generation;
- SmartLocator runtime behavior;
- browser-grounded and adaptive-login logic;
- agentic graph fallback behavior;
- evidence-gated RCA and `No idea to fix` handling;
- Codex provider connection and JSON error handling;
- local/worker operation cancellation;
- iterative generation and Codegen import;
- GUI workflow labels and routes.

## Native dependency note

The build environment contained Playwright Python but did not contain the optional runtime packages `langchain`, `langgraph`, or `langsmith`. The repository declares them in `requirements.txt`, `pyproject.toml`, and `setup.py`; their deterministic/fallback integration paths are covered by tests. On the target machine run:

```bash
python -m pip install -r requirements.txt
```

Then confirm:

```text
GET /api/agentic/status
```

returns `langgraph_available: true` and `langchain_available: true`.
