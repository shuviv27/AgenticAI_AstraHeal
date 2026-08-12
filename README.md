# AstraHeal AI v0.7.4 — RACPAD-Aware Build Contract Repair

This build preserves the v0.7.3 multi-agent pipeline and strengthens only the **Existing Framework → Validate & fix framework** setup-repair contract for complex Playwright TypeScript repositories, with special handling for RACPAD-style npm workspaces/monorepos.

When `package.json` has no `build` script, AstraHeal now analyzes the root TypeScript compiler scope, npm workspaces, existing `typecheck` scripts, direct third-party imports, ambient module declarations, workspace package manifests and `package-lock.json` before proposing a repair. A RACPAD-style repository that already exposes `typecheck: npm run typecheck --workspaces --if-present` receives the workspace-aware build proposal `npm run typecheck && tsc --noEmit`, so workspace packages are validated first and root Playwright TypeScript is validated second. Existing valid build scripts are never overwritten.

Missing dependencies are proposed only when they are required by root compiler-scoped source and can be grounded in repository evidence. Versions are reused from workspace package manifests or the existing lock graph where possible. Optional modules covered by local ambient declarations are not blindly installed. When new direct dependencies already exist in the lock graph, AstraHeal also prepares an exact `package-lock.json` root-metadata diff so both files can be reviewed and approved together.

The human-approval boundary remains mandatory. **Validate & fix framework** no longer performs the expensive npm/Chromium command sequence before the repair proposal. It first prepares exact file/content diffs, waits for approval, applies only approved files with backups, and then runs the required sequence exactly once: `npm config set registry https://registry.npmjs.org/` → `npm install --registry=https://registry.npmjs.org/` → `npx playwright install chromium` → `npm run build`. Other AstraHeal workflows retain their existing command behavior.

See `AstraHealAI_v0.7.4_RACPAD_BUILD_CONTRACT_FIX.md` and `BUILD_VALIDATION_REPORT.md`.

# AstraHeal AI v0.7.3 — Cached Framework Intelligence + Human-Approved Standardization

This build keeps the existing AstraHeal agentic pipeline and strengthens the **Existing Framework** workflow for large and differently structured Playwright repositories. First-pass architecture understanding is fingerprinted and saved under each selected framework's `.qa-cache/existing-framework` plus durable SQLite framework memory; unchanged follow-up analysis reuses that knowledge and code graph instead of repeating the full walkthrough. Long first-pass stages stream meaningful GUI milestones.

**Validate & fix framework** is now a two-phase human-in-the-loop workflow. AstraHeal first runs diagnosis and prepares exact file-by-file diffs without source writes. The GUI shows the selected Playwright standard, standard audit, required validation commands, reason, before/after content and exact diff for each proposed file. Only files explicitly left in the approval list may be changed; stale approvals are rejected when the framework fingerprint changes. Approved setup changes are backed up and every changed file is logged before the final validation sequence runs.

The recommended **Adaptive Enterprise Playwright Standard** standardizes semantic roles instead of forcing every valid client repository into one physical folder layout. An optional `.astraheal-playwright-standard.json` role-map can be installed only with user approval. This supports root `tests/pages`, `src/main + src/test`, BDD hybrids and workspace/monorepo layouts. A strict `src/main + src/test` profile remains available as an explicit migration target rather than an implicit bulk move.

The repository now ships only the `generated-playwright` sample project; API sample project folders/mocks/collections were removed while API capability code was left intact to avoid breaking unrelated product behavior. See `AstraHealAI_v0.7.3_FRAMEWORK_MEMORY_APPROVAL_STANDARD.md` and `AstraHealAI_v0.7.3_BUILD_VALIDATION_REPORT.md`.

# AstraHeal AI v0.7.2 — Unified Execution Evidence and Reliable Plain-English RCA

This build adds a supervised Playwright Codegen workflow that lets a tester record a real AUT journey and then imports the sanitized actions and locators into AstraHeal. The generator reuses matching framework methods and locator objects first, creates only missing components, preserves captured evidence for multiple testcase IDs, and keeps earlier generated scenarios across later upload rounds.

The Plain-English RCA button now uses a stable backend report endpoint. It returns an explanatory report even before RCA evidence exists instead of a confusing `Detail not found` page. Generation reports link directly to the same RCA workflow: run tests → explain failures → review the plain-English RCA → create a safe fix plan → approve → rerun failed tests.

See `AstraHealAI_v0.7.2_RCA_EVIDENCE_HANDOFF_FIX.md` for the latest RCA evidence-routing correction. The v0.7.1 Codegen and iterative-generation features remain available.

# AstraHeal AI v0.7.0 — Page-state-aware Playwright locator evidence

This build fixes multi-stage login and other repeated-control flows where the same DOM control appears on more than one page state. Browser grounding now captures native input-button accessible names from the HTML `value` attribute, preserves stable `id`/`name` selectors, rejects undefined ARIA roles or accessible names, and validates that every accepted locator uniquely resolves one live element. The same Salesforce submit control can therefore be used for both the username-stage **Log In to Sandbox** action and the password-stage **Log In** action even when its visible label changes.

Generated login locators include page-state-independent stable candidates such as `#Login` and `input[name="Login"]`, plus browser-observed role/name aliases. SmartLocator no longer silently selects the first of multiple matches and now reports current URL, candidate counts, visibility, and visible controls when resolution fails.

See `AstraHealAI_v0.7.0_PAGE_STATE_LOCATOR_FIX.md`.

# AstraHeal AI v0.6.8 — Reliable Playwright validation and runtime data

This build fixes the generation rollback in which `playwright test --list` evaluated runtime credentials and generic spreadsheet placeholders while merely discovering tests. Required credential checks now run in `test.beforeAll`, after structural discovery. Workbook labels such as `Date`, `Time`, `Product`, and `Appointment Type` are optional runtime overrides with deterministic QA defaults; they are no longer treated as missing secrets. Generated specs still use readable named data such as `data.username`, `data.firstName`, and `data.expectedLeadStatus`.

Spreadsheet credentials are copied during generation into `.env.astraheal.local`, which is automatically Git-ignored and loaded by the generated Playwright runtime. If credentials are unavailable after a backend restart, source generation is retained and the report identifies the missing runtime inputs instead of rolling back otherwise valid specs, page methods, and locators.

The complete generated contract remains: one spec per testcase, reusable page methods, locator repository definitions, browser-grounded locator reuse, MCP/codegen evidence, TypeScript/POM contract validation, optional execution, grounded RCA, and user-controlled cancellation.

See `docs/42_EXECUTABLE_NAMED_TEST_DATA_PLAYWRIGHT_GENERATION.md`.

This build adds a unified **Stop current operation** control for long-running GUI actions. It cancels LangGraph workflows, managed npm/npx/Playwright/Codex subprocess trees, local parallel shards, BrowserStack launcher processes, and Central-VM worker jobs. The progress panel shows elapsed time and an expected-duration warning. Cancellation is cooperative for Python work and forceful only for AstraHeal-owned subprocesses.

See `docs/40_ABORT_LONG_RUNNING_OPERATIONS.md` for architecture, API and operational details.

# AstraHeal AI — Multi-Agent Playwright Automation Studio

Clean enterprise build for developing, executing, diagnosing, and fixing existing Playwright TypeScript automation frameworks.

## Autonomous multi-agent build 0.6.3

AstraHeal now includes a LangGraph supervisor, LangChain tool agents, LangSmith tracing, project-root SQLite memory, SSE backend streaming, optional Graphify code indexing, Playwright framework diagnosis/fix automation, VDI distributed-execution hardening, evidence-gated RCA, and a no-code AI Functional Walkthrough Agent that verifies browser steps and locators before Playwright generation.

Read `docs/33_AUTONOMOUS_LANGGRAPH_LANGSMITH_GRAPHIFY.md`.


### v0.6.3 adaptive goal-driven browser walkthrough

- Treats every Excel/document testcase step as an intent rather than assuming one line always maps to one browser action.
- Adds an observe → plan → act → verify loop before every guided action.
- Uses the selected AI provider to choose the minimum safe prerequisite action when the intended target is not yet available, with deterministic DOM fallback.
- Handles multi-stage authentication and wizard flows such as username → **Log In to Sandbox** → password → final login.
- Persists AI-discovered prerequisite actions and verified locators into the enhanced testcase so Playwright generation reproduces the real application flow.
- Prevents loops with state fingerprints, action limits and destructive-action filters; ambiguous flows still pause for supervised human guidance.
- Adds explainable prerequisite-action details to the walkthrough HTML/JSON reports.
- Restores complete `placeholder` strategy handling in the default generated Playwright locator factory.

See `docs/38_ADAPTIVE_GOAL_DRIVEN_FUNCTIONAL_WALKTHROUGH.md`.

### v0.6.2 sequential walkthrough and generation reliability

- Transfers Excel credential rows through an expiring, process-memory-only vault so the browser can complete login without persisting secrets.
- Reuses authenticated sessions by testcase credential profile and continues scenarios in workbook order.
- Falls back from an unavailable AI provider to verified live-DOM matching instead of unnecessary manual timeouts.
- Enables approved QA/sandbox mutation steps by default while retaining a hard production guard.
- Retains partial verified locator evidence and blocks generation only for unresolved new locators.
- Writes non-secret testcase values to a feature data module, creates scenario-specific credential environment bindings, and can execute newly generated specs once using volatile workbook credentials.
- Adds readable functional-walkthrough and Playwright-generation HTML reports under **Logs & Reports**.

See `docs/37_FUNCTIONAL_WALKTHROUGH_EXECUTION_AND_GENERATION_FIX.md`.

### v0.6.1 AI-provider connection hardening

- Fixed the Codex login API crash caused by an undefined `cwd` variable in v0.5.2.
- Every API failure now returns JSON so the GUI no longer throws `Unexpected token 'I'` for plain-text 500 responses.
- Codex login runs in a separate interactive terminal without captured subprocess pipes.
- Added explicit Codex login-status and health-diagnostic controls.
- Non-Codex providers no longer trigger Codex login accidentally.

See `docs/36_CODEX_PROVIDER_CONNECTION_AND_JSON_ERROR_FIX.md`.

Install: `pip install -e .`  
Optional Graphify: `pip install -e ".[codegraph]"`

Install the Playwright browser used by the functional walkthrough: `python -m playwright install chromium`

## Start here

Read:

```text
docs/00_README_CLEAN_STARTUP.md
```

## Root startup scripts

| Scenario | Windows | Mac/Linux |
|---|---|---|
| Local PC only | `START_GUI_LOCAL_WINDOWS.cmd` | `./START_GUI_LOCAL_MAC.sh` |
| Central VM only | `START_GUI_CENTRAL_VM_WINDOWS.cmd` | `./START_GUI_CENTRAL_VM_MAC.sh` |
| Central VM + worker VMs | `START_GUI_VM_WITH_WORKERS_WINDOWS.cmd` | `./START_GUI_VM_WITH_WORKERS_MAC.sh` |
| Worker VM agent | `START_WORKER_AGENT_WINDOWS.cmd` | `./START_WORKER_AGENT_MAC.sh` |

## Recommended VM setup

```text
VM177 = Central VM: GUI/backend, AI provider, framework source-of-truth, RCA/self-healing, reports
VM45  = Worker VM: worker agent + browser execution
VM135 = Worker VM: worker agent + browser execution
```

Workers do not need OpenAI/DeepSeek/Codex keys. Workers need the worker agent, Node/npm/npx, Playwright browsers, AUT access, and framework path access.

## Open GUI

```text
http://127.0.0.1:8080/astraheal-ai
```

From worker/VDI when VM177 is central:

```text
http://<VM177-IP>:8080/astraheal-ai
```

## Main docs

- `docs/01_LOCAL_PC_WORKFLOW.md`
- `docs/02_CENTRAL_VM_ONLY_WORKFLOW.md`
- `docs/03_VM177_WITH_VM45_VM135_WORKERS.md`
- `docs/04_AI_PROVIDER_CONFIGURATION.md`
- `docs/05_WORKER_AGENT_REFERENCE.md`
- `docs/06_STARTUP_SCRIPTS_REFERENCE.md`
- `docs/07_VALIDATION_AND_TROUBLESHOOTING.md`
- `docs/31_ADD_NEW_TESTS_MULTI_SOURCE_BDD_ATLASSIAN.md`
- `docs/32_EXCEL_FUNCTIONAL_TESTCASE_GENERATION_VALIDATION_FIX.md`
- `docs/33_AUTONOMOUS_LANGGRAPH_LANGSMITH_GRAPHIFY.md`
- `docs/35_AI_FUNCTIONAL_WALKTHROUGH_AGENT.md`

Legacy reference documents are moved under:

```text
docs/legacy_reference/
```
