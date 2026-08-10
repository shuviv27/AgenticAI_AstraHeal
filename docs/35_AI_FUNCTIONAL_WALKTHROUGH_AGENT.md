# AI Functional Walkthrough Agent — v0.6.0

## Purpose

The AI Functional Walkthrough Agent runs immediately after testcase normalization and before Playwright TypeScript generation. It opens a real browser, follows the approved functional steps, improves ambiguous wording, captures non-secret test-data bindings, and records verified live locators. It does not create or modify Playwright source code.

## User workflow

1. Select the existing Playwright framework.
2. Upload Excel, DOCX, PDF, BDD, Jira, or pasted testcase content.
3. Click **Load / normalize testcase source**.
4. Click **AI walkthrough application (no code)**.
5. Review the streamed scenario/step evidence.
6. Click **Preview placement**.
7. Click **Generate & add tests**.

When **Require walkthrough evidence** is enabled, generation is blocked if a required new locator has not been verified in the live application.

## Architecture

```text
Normalized testcase scenarios
          |
          v
LangGraph functional_walkthrough node
          |
          v
AI Functional Walkthrough Agent
  - deterministic DOM ranking
  - optional selected LLM reasoning
  - Playwright browser control
  - supervised human takeover
          |
          +--> enhanced testcase JSON
          +--> locator evidence report
          +--> test-data bindings
          +--> SQLite framework memory
          |
          v
Existing Playwright generator
```

## Why Playwright is the browser-control layer

The product provides a Comet-like user experience, but it does not depend on a private or undocumented browser-control interface. Playwright supplies deterministic actions, locator validation, browser events, timeouts, and repeatable evidence. Perplexity can still be selected as the reasoning provider through the existing provider gateway.

An optional custom Chromium-compatible executable path is available for controlled experiments. It is not required and should not be treated as a supported Comet automation SDK.

## Agent actions

The agent accepts only these bounded actions:

- `goto`
- `click`
- `fill`
- `select`
- `check`
- `press`
- `verify`
- `wait`
- supervised manual interaction

The selected LLM cannot invent a browser action or DOM element. It receives a sanitized list of visible interactive elements and must select an existing element ID. Invalid output becomes a supervised/manual step rather than a guessed action.

## Locator strategy

Verified locator priority is:

1. `getByTestId`
2. `getByRole` with accessible name
3. `getByLabel`
4. `getByPlaceholder`
5. `getByText`
6. stable CSS ID

Each evidence record contains confidence, locator candidates, page URL/title, original step, improved step, and non-secret test-data binding.

## Human supervision

Headed supervised mode is recommended for enterprise applications. The browser remains visible so a tester can:

- complete MFA or CAPTCHA;
- select the intended element when the DOM is ambiguous;
- navigate custom Salesforce/iframe flows;
- confirm actions that change QA data.

The injected interaction listener records only element attributes. It never records the value typed into an input.

## Mutation and navigation safety

By default, the agent blocks operations that may create, submit, save, delete, transfer, approve, purchase, or otherwise change application data. The user must explicitly enable mutation approval for a QA environment.

Cross-origin navigation is also blocked by default. It must be explicitly enabled for valid SSO, payment sandbox, or other approved multi-domain flows.

## Credential handling

Username and password fields in the GUI are sent only to the specialized walkthrough endpoint. They are placed in a process-memory one-time vault keyed by the new run ID and consumed once by the browser agent. The run ID already exists for orchestration, so no credential token is placed in the persisted workflow request.

The system does not write credentials to:

- SQLite;
- LangGraph checkpoints;
- LangSmith prompts;
- screenshots;
- reports;
- enhanced testcase files;
- Playwright source files.

Only environment-variable bindings such as `WALKTHROUGH_USERNAME` and `WALKTHROUGH_PASSWORD` appear in evidence.

## Outputs

Per feature, the agent writes:

```text
.qa-cache/functional_walkthrough/<feature>/latest.json
testcases/module2_uploaded/<feature>/<feature>.walkthrough.scenarios.json
```

The report is also saved to SQLite framework memory under:

```text
functional_walkthrough:<feature>
```

## Browser installation

Install Python dependencies and the browser runtime on the Central VM:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

The agent now distinguishes between:

- missing Python Playwright package;
- missing Playwright browser runtime;
- invalid custom browser executable;
- application/browser execution failure.

It reports the exact corrective command without modifying the framework.

## Generation hand-off

The existing generator can consume the enhanced testcase file and verified locator evidence. New locator creation is blocked before repository modification when evidence is required but missing. Existing known locators and page methods remain reusable, preserving all prior generation behaviour.

## Main implementation files

```text
qa_pipeline/agentic/functional_walkthrough.py
qa_pipeline/agentic/credential_vault.py
qa_pipeline/agentic/graph.py
qa_pipeline/agentic/api.py
qa_pipeline/agentic/tools.py
qa_pipeline/modules/playwright_ts_generator/enterprise_add_new_tests.py
qa_pipeline/gui/static/index.html
tests/test_functional_walkthrough_agent.py
```
