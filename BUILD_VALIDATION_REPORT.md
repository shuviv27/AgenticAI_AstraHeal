# AstraHeal AI v0.4.3 Build Validation Report

**Build:** `0.4.3`  
**Validation date:** 2026-07-16  
**Primary enhancement:** Add new test later — multi-test documents, Gherkin/BDD, framework-aware reuse, Jira/Confluence MCP-first intake, and transactional generation

## Delivered behavior

### Multi-test source intake

- PDF, DOCX, legacy DOC (when local `antiword` is available), TXT, Markdown, JSON, CSV, XLSX/XLSM, and `.feature` inputs are accepted.
- One uploaded file may contain multiple testcases.
- Test Case/Scenario headings and spreadsheet Test Case IDs are normalized into independent scenarios.
- One normalized testcase/scenario produces one Playwright `.spec.ts` file.

### Gherkin/Cucumber BDD

- Supports `Feature`, tags, `Background`, `Scenario`, `Scenario Outline`/`Scenario Template`, `Examples`, `Given`, `When`, `Then`, `And`, `But`, and `*`.
- Scenario Outline example rows expand into independent executable scenarios.
- BDD traceability is retained in the normalized payload and generation report.

### Existing-framework placement and reuse

- The framework path is taken from the Existing Framework tab.
- Playwright `testDir` and the recursively learned framework structure determine the spec destination.
- A no-write placement preview reports the recommended test folder, page/method file, locator file, match evidence, and ambiguity per scenario.
- Default placement policy stops before changes when the target is ambiguous.
- Existing methods and locators are reused first.
- New methods/locators are appended to the closest approved existing file.
- A new support file is created only when no safe reusable target exists and the user permits it.
- A separate locator repository must already be linked to the selected page class before it can be updated.

### Playwright MCP/codegen policy

- The tab exposes MCP/codegen preparation before generation.
- Existing symbols are reused before any locator is proposed.
- Newly inferred semantic locators are explicitly marked provisional until live-DOM verification through Playwright MCP, codegen, trace, or a real application session.
- Generated specs are validated with `npx --no-install playwright test <specs> --list` when local Node/Playwright dependencies are available.

### Transactional safety

- Every pre-existing page/locator file is backed up before modification.
- Every newly created spec/support file is tracked.
- If Playwright validation fails, AstraHeal restores original files and deletes newly created source/spec files automatically.
- The report preserves attempted files, validation output, and rollback evidence while returning zero committed changed files.

### Jira and Confluence

- Supports individual Jira issues, Epic children, JQL result sets, and Confluence pages.
- Epic children become independent testcases; the Epic remains contextual when children are available.
- When `uvx` is available, AstraHeal launches `mcp-atlassian` over stdio, initializes MCP, discovers tools dynamically, and invokes read-only Jira/Confluence tools first.
- Secure REST is a clearly reported fallback when MCP is unavailable, times out, or returns unusable data.
- Username, API token, password/personal token are held only for the current request.
- MCP JSON stores environment-variable placeholders only.
- Secret values are removed from non-Atlassian GUI requests and are not included in normalized testcases, reports, or returned credential summaries.

## Automated validation

| Validation | Result |
|---|---:|
| Complete Python regression suite | **36/36 passed** |
| New Add New Tests regression group | **11/11 passed** |
| Existing recursive framework discovery/execution regression group | Passed |
| Existing explainable RCA/exact approval-scope regression group | Passed |
| Python compilation (`compileall`) | Passed |
| FastAPI application import | Passed |
| FastAPI route count | **152** |
| GUI JavaScript syntax (`node --check`) | Passed |
| Setuptools wheel build | Passed |
| Built wheel version | **0.4.3** |
| `openpyxl` wheel dependency metadata | Present: `openpyxl>=3.1,<4` |
| Final ZIP integrity | Passed |
| Clean extraction regression rerun | **36/36 passed** |
| Clean extraction Python compilation | Passed |
| Clean extraction GUI JavaScript syntax | Passed |

The optional `python -m build` frontend was not installed in this environment. Package validation was completed successfully through the installed setuptools/wheel path using `python setup.py bdist_wheel`.

## New regression coverage

1. A plain document containing two testcases normalizes into two scenarios.
2. Gherkin Background, Scenario, `And`, Scenario Outline, and Examples expand correctly.
3. XLSX rows group by Test Case ID and preserve multiple steps.
4. Two normalized scenarios create two specs under configured `src/test/specs`.
5. Existing page files are updated rather than creating a root-level duplicate page file.
6. Ambiguous page placement stops before source changes.
7. An explicitly linked locator repository is updated without creating another file.
8. Failed Playwright validation restores the original page file and removes generated specs.
9. MCP configuration and fetched responses never contain supplied secret markers.
10. Jira Epic child Stories/Bugs become separate testcases and the Epic is excluded as an extra test.
11. MCP is selected before REST when a local MCP runtime is available.
12. New APIs coexist with failure analysis, self-healing, BrowserStack, and established routes.

## Existing functionality regression coverage retained

- root and nested `src/**` Playwright discovery;
- custom and parent-relative `testDir` handling;
- monorepo discovery;
- deep-learning dependency mapping;
- MCP explicit-spec fallback;
- sequential and distributed path preservation;
- BrowserStack deep-path and environment-only credential handling;
- provider gates and critical routes;
- category-specific Plain English RCA;
- exact runtime approval write boundaries;
- explicit local report/log locations.

## Files written at runtime

Normalized source:

```text
<ASTRAHEAL_ROOT>/testcases/module2_uploaded/<feature>/functional-testcases.json
```

Framework generation reports:

```text
<FRAMEWORK_ROOT>/.aiqa-history/add-new-tests/<feature>-generation-report.json
<FRAMEWORK_ROOT>/.aiqa-history/add-new-tests/<feature>-generation-report.html
<FRAMEWORK_ROOT>/.aiqa-history/new-test-generation.jsonl
```

Backups:

```text
<FRAMEWORK_ROOT>/.aiqa-history/backups/add-new-tests/<timestamp>/
```

Atlassian MCP placeholder configuration:

```text
<ASTRAHEAL_ROOT>/.qa-cache/atlassian-mcp/mcp-atlassian.json
```

## Validation limits

The following require customer credentials, network access, and the real application environment and therefore were not executed here:

- a live Jira or Confluence tenant fetch;
- a live `mcp-atlassian` session against customer data;
- a live authenticated Playwright MCP/codegen browser session;
- locator verification against the customer AUT DOM;
- BrowserStack cloud execution;
- live OpenAI, DeepSeek, Codex, Ollama, or Perplexity provider calls.

The build validates MCP protocol selection, dynamic-tool routing logic, fallback behavior, secret isolation, framework writes, rollback, and all existing local regressions. New locators remain clearly marked provisional until live-DOM verification is performed in the target environment.
