# Deep Recursive Framework Discovery and AI-Control Fix

**Build:** 0.4.1  
**Validation date:** 15 July 2026

## Problem addressed

Some Playwright repositories do not keep tests in a root-level `tests` folder. A common enterprise structure is:

```text
src/
  main/
    api/
    config/
    pages/
    ui_base/
  test/
    specs/
      module-name/
        test1.spec.ts
```

Earlier logic had recursive file walking, but several acceptance and downstream validation paths still depended on a limited set of folder names. This could cause a test to be visible in one step and then be rejected or lost in selection, distributed execution, MCP preparation, RCA inventory, or full-control fixing.

## Implemented design

A shared structure-discovery engine now provides one source of truth for all Existing Framework flows.

### Three independent executable-test signals

A `.spec`, `.specs`, or `.test` file is accepted when at least one safe signal proves it is executable:

1. It is under a Playwright `testDir` parsed from configuration.
2. It is under a recognized root or nested test area such as `tests`, `src/test/specs`, `e2e`, or a monorepo equivalent.
3. Its code contains executable Playwright test evidence, allowing approved custom locations.

Supported extensions include TypeScript, TSX, JavaScript, JSX, MJS, and CJS.

### Playwright configuration parsing

The scanner understands common forms such as:

```ts
testDir: './src/test/specs'
testDir: path.join(__dirname, 'src', 'test', 'specs')
testDir: path.resolve(process.cwd(), 'src', 'test', 'specs')
testDir: TEST_ROOT
```

Relative values are resolved against the configuration file safely. Paths escaping the selected framework root are not accepted as patch or execution targets.

### Component-directory model

Deep learning now explicitly maps reusable layers including:

- `pages` and page-object/locator repositories
- `config` and environment folders
- `api`, service, and client folders
- `ui_base`, base-page, and core framework folders
- fixtures, hooks, test data, resources, utilities, and reporters
- executable spec roots and modules

The model is supplied to dependency mapping, RAG memory, MCP readiness, and AI full-control prompts.

## Button behavior

### Find scripts in framework

This button now performs lightweight deterministic recursive discovery only. It does not silently trigger full AI/RAG indexing. It returns the exact executable files that sequential or distributed execution will receive.

### Deep learn this framework with AI

This button performs the complete architecture and semantic pass:

- structure and folder-role mapping
- spec-to-page-to-helper dependency chains
- unresolved import and alias analysis
- locator strategy and anti-pattern analysis
- AUT flow hints
- reusable framework memory and RAG chunks
- safe patch-scope recommendations

### AI full-control framework fix

Before an AI provider can propose a patch, the flow now runs structure discovery and deterministic deep understanding. The prompt instructs the provider to:

- preserve the discovered test location
- reuse existing page, locator, API, config, `ui_base`, fixture, helper, and test-data layers
- inspect dependency chains before creating members
- avoid duplicate locators, methods, page classes, and configuration files
- report changed/impacted files

Existing provider confirmation, backup, scope, skip/only/fixme blocking, validation, and rollback behavior remains in place.

### Prepare Playwright MCP assist

MCP preflight first runs normal `npx playwright test --list`. When the default configuration does not prove tests but recursive discovery has found valid specs, preflight retries with explicit discovered spec paths. This distinguishes a stale `testDir`/`testMatch` from a repository with no executable tests.

## Cross-flow consistency

The same proven test paths are preserved across:

- selectable script discovery
- sequential execution
- local parallel browser sharding
- central/worker distributed execution
- BrowserStack execution-only mode
- failed-test inventory and console parsing
- RCA and self-healing target resolution
- failed-only reruns and combined report updates

Generated, dependency, cache, backup, history, result, and report directories remain excluded.

## Main files changed

```text
qa_pipeline/agents/existing_framework_control/structure_discovery.py
qa_pipeline/agents/existing_framework_control/controller.py
qa_pipeline/agents/existing_framework_control/deep_framework_agents.py
qa_pipeline/agents/existing_framework_control/framework_intelligence.py
qa_pipeline/mcp/mcp_readiness_preflight.py
qa_pipeline/mcp/framework_full_control_fix.py
qa_pipeline/core/distributed_history.py
qa_pipeline/gui/static/index.html
tests/test_recursive_playwright_discovery.py
```

## Validation

The included regression suite covers the requested `src/main` plus `src/test/specs` structure, root `tests`, monorepos, configured custom paths, content-proven custom paths, TSX/JS variants, ignored generated folders, sequential/distributed commands, MCP fallback, full-control context, provider gating, critical API routes, and BrowserStack path/credential handling.

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q qa_pipeline tests
```
