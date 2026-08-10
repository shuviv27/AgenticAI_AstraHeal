# Framework Analysis GUI and LangSmith Context Fix — v0.5.1

## Why the old Start Here container was confusing

The former **Autonomous Multi-Agent Control** card was a shortcut launcher. It duplicated actions already available in other tabs:

- **Learn framework** started the deep framework-analysis workflow.
- **Diagnose & fix framework** started a guarded framework-repair workflow.
- **Grounded RCA** started failure analysis without guiding the user to run tests first.
- **Agent system status** returned technical dependency and runtime details.

The labels exposed internal architecture rather than the user’s task. The card has therefore been removed from **Start Here**.

## New GUI organisation

### Start Here

Contains only:

- Runtime selection and readiness.
- AI-provider configuration and validation.

### Existing Framework

Contains all framework understanding and preparation operations:

1. **Analyse framework & check setup**
   - Learns folders, tests, fixtures, page objects, locators, imports, aliases and conventions.
   - Creates the code relationship graph and framework memory.
   - Checks Playwright configuration and runs the requested prerequisite commands.
   - Does not automatically rewrite source configuration, although npm/browser installation can update dependency folders, browser caches or lockfiles.

2. **Validate & fix framework**
   - Diagnoses package.json, tsconfig.json and playwright.config.*.
   - Creates backups before approved changes.
   - Applies guarded fixes and validates the result.
   - Rolls back unsuccessful changes.

3. **Prepare browser-assisted diagnosis (MCP)**
   - Prepares Playwright MCP/browser evidence support.
   - Can apply approved MCP readiness fixes when blockers are detected.

A dedicated **Framework analysis progress** panel now shows plain-language events only.

### Run & Fix Tests

Contains test execution, failed-test evidence, RCA, safe-fix planning, self-healing, failed-only reruns and rollback.

### Logs & Reports

Contains generated reports, saved memory and the optional multi-agent service-health check.

## Root cause of `generator didn't stop after throw()`

The LangSmith tracing wrapper was implemented as a Python generator context manager with a broad `try/except` around its `yield`:

```python
try:
    with langsmith_context(...):
        yield
except Exception:
    yield
```

When the framework workflow raised any exception, that exception was thrown back into the generator. The broad `except` caught it and attempted to yield a second time. Python then replaced the real framework error with:

```text
RuntimeError: generator didn't stop after throw()
```

## Correction

The wrapper now distinguishes two cases:

- Importing or entering the optional LangSmith context fails: continue without tracing.
- The workflow body fails: propagate the original exception unchanged.

`ExitStack` is used so tracing setup remains optional without swallowing workflow failures.

## Streaming cleanup

- Raw `LangGraph node completed` events are no longer published to the normal GUI stream.
- Agent names are translated to plain-language labels.
- The global backend stream is stopped for autonomous framework runs, avoiding duplicate agent events.
- Duplicate progress lines are suppressed.
- Technical traces remain available in LangSmith and saved run records.

## Regression coverage

The build adds tests confirming that:

- A real workflow exception remains the original exception when LangSmith tracing is active.
- The Start Here tab does not contain the former autonomous control container.
- Framework analysis, framework fixing, MCP preparation and progress appear under Existing Framework.

## Validation

- Python compilation: passed.
- GUI JavaScript syntax: passed.
- FastAPI application import: passed.
- Automated tests: 45 passed.
- Deep framework-analysis workflow on a temporary Playwright project: passed.
