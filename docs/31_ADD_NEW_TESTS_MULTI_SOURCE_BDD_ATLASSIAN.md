# Add New Tests: Multi-source, BDD, Jira and Confluence

**Build:** 0.4.3  
**GUI tab:** Add new test later  
**Target:** The Playwright framework selected in Existing Framework

## Purpose

This workflow converts approved functional test sources into reusable Playwright TypeScript tests without creating a parallel framework or silently writing to unrelated folders.

The workflow has four controlled stages:

1. Load or fetch the source.
2. Split and normalize every independent testcase/scenario.
3. Preview exact test, page-method and locator placement.
4. Generate, back up and validate the approved changes.

## Supported local source formats

| Format | Behavior |
|---|---|
| PDF | Extracts page text and splits multiple testcase/scenario sections. Scanned image-only PDFs require an external OCR process before upload. |
| TXT / MD / CSV | Detects testcase/scenario headings, numbered steps and expected results. |
| DOCX | Extracts paragraphs and tables. |
| DOC | Uses local `antiword` only when it is installed; otherwise returns an explicit conversion requirement. |
| XLSX / XLSM | Groups rows by Test Case ID and preserves multiple steps for each testcase. |
| JSON | Accepts a normalized `scenarios` payload or a list of scenario objects. |
| FEATURE | Parses Gherkin/Cucumber BDD syntax. |

A single source may contain many testcases. Each normalized testcase/scenario receives a stable ID and produces a separate `.spec.ts` file.

## Gherkin and Cucumber input

The parser supports:

- `Feature`
- tags
- `Background`
- `Scenario`
- `Scenario Outline` / `Scenario Template`
- `Examples`
- `Given`, `When`, `Then`, `And`, `But`, and `*`

`And` and `But` inherit the previous primary keyword for action inference. Scenario Outline rows expand into independent executable scenarios. The generated report keeps the original BDD traceability flag and scenario ID.

The current output mode generates Playwright Test specs. It does not install or force a separate Cucumber runtime into an existing framework.

## Existing-framework placement and reuse

The selected framework path comes from the Existing Framework tab. AstraHeal reads Playwright configuration and the learned structure model to identify:

- configured or proven test directories such as `src/test/specs`;
- existing page classes and reusable methods;
- existing locator repositories or page-owned locators;
- imports and page-to-locator object relationships.

Before generation, **Preview placement** shows, per testcase:

- destination test folder;
- recommended page/method file;
- recommended locator file;
- match evidence and ambiguity;
- whether a new support file is required.

Default policy is **Ask me when placement is ambiguous**. In this mode no source file is changed until an unambiguous target is found or the user explicitly chooses a target.

Existing locator and method symbols are reused first. New symbols are appended to the closest existing file. A new page support file is created only if no safe reusable target exists and **Create a new page support file only when required** is enabled.

For a separate locator repository, the selected locator class must already be imported and instantiated by the selected page class. This prevents generation into an unrelated object file.

## Playwright MCP and codegen policy

The tab exposes **Prepare MCP/codegen locator assist**. The deterministic generator does not claim that guessed semantic locators are live-DOM verified. New locators are marked provisional in the generation report until they are checked with Playwright MCP, codegen, trace, or a live application session.

Recommended order:

1. Deep-learn the existing framework.
2. Load/fetch and normalize testcases.
3. Preview placement.
4. Prepare MCP/codegen and verify the application/base URL.
5. Generate and validate.

## Jira and Confluence intake

Supported Jira sources:

- individual Story, Task or Bug key;
- Epic plus child stories/tasks/bugs;
- JQL result set.

Supported Confluence source:

- page ID or page URL.

For an Epic, child issues become separate normalized testcases. The Epic itself supplies context and is not automatically treated as one executable testcase when child issues are available.

### Credential handling

The GUI accepts:

- Jira URL;
- optional Confluence URL;
- username/email;
- API token (preferred);
- optional password fallback for compatible Data Center installations.

Security rules:

- credentials are used only in the current request;
- token/password values are removed from non-Atlassian GUI requests;
- secrets are not written to testcase payloads, reports, logs, project files or MCP JSON;
- the prepared MCP configuration contains `${JIRA_API_TOKEN}` and related environment placeholders only;
- when `uvx` is available, AstraHeal launches `mcp-atlassian` over stdio, performs MCP initialization, discovers `tools/list`, and invokes read-only Jira/Confluence tools such as `jira_get_issue`, `jira_search`, and `confluence_get_page`;
- the response states the actual transport and MCP tool calls used;
- secure Jira/Confluence REST retrieval is the deterministic fallback when MCP is unavailable, times out, or cannot return usable data.

## Safe generation and rollback

Every existing file that may be updated is backed up under:

```text
<FRAMEWORK_ROOT>/.aiqa-history/backups/add-new-tests/<timestamp>/
```

Generation reports are stored under:

```text
<FRAMEWORK_ROOT>/.aiqa-history/add-new-tests/
```

History is appended to:

```text
<FRAMEWORK_ROOT>/.aiqa-history/new-test-generation.jsonl
```

When validation is enabled and local Node/Playwright dependencies are available, AstraHeal runs:

```text
npx --no-install playwright test <generated-specs> --list
```

If validation fails:

- every pre-existing page/locator file is restored from its original backup;
- every newly created spec/support file is deleted;
- `changed_files` is returned empty;
- attempted files, Playwright output and rollback details remain in the generation report for review.

If validation cannot run because `npx` or `package.json` is unavailable, the result is explicitly marked as skipped rather than falsely reported as a live execution success.

## Non-regression boundaries

This enhancement does not replace or bypass:

- Existing Framework recursive discovery;
- sequential or distributed execution;
- BrowserStack execution adapter;
- RCA and Plain English reports;
- self-healing and exact approval boundaries;
- failed-only rerun and combined reports;
- AI provider readiness gates.
