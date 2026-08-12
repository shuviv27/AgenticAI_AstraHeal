# AstraHeal AI v0.7.4 Build Validation Report

## Scope

RACPAD-aware Playwright setup repair for missing `npm run build`, compiler-scoped dependency inference, deterministic package-lock synchronization, and repair-before-execute command timing. Existing v0.7.3 framework cache, human approval, agent pipeline, generation, RCA/self-healing, distributed execution and API behavior are preserved.

## Automated validation summary

- Python compilation (`compileall`): **Passed**
- Full pytest suite: **111 passed**
- Full unittest suite: **57 passed**
- Focused framework memory/approval/RACPAD suite: **8 passed**
- GUI inline JavaScript parse (`node --check`): **Passed**
- FastAPI application import: **Passed**
- Registered FastAPI routes: **181**
- Required agentic routes (`runs/start`, `playwright-standards`, `status`): **Present**
- Registered guarded agent tools: **12**
- Exact required command-sequence regression: **Passed**
- Framework-fix proposal phase skips prerequisite commands until repair: **Passed**
- Deep-learn retains existing prerequisite-command behavior: **Passed**
- Human-approved exact file scope: **Passed**
- Stale-approval/fingerprint protection: **Passed**
- Unapproved lockfile side-effect restoration: **Passed**
- JSONC tsconfig support: **Passed**
- Project-local framework/code-graph cache reuse: **Passed**

## Required validation sequence

The production validator still executes exactly:

1. `npm config set registry https://registry.npmjs.org/`
2. `npm install --registry=https://registry.npmjs.org/`
3. `npx playwright install chromium`
4. `npm run build`

For the `framework_fix` workflow, this sequence now runs only after the approved setup repair has been applied. This prevents an expensive workspace install/Chromium/build cycle from being performed once before repair and then a second time afterward. Other workflows keep their existing behavior.

## RACPAD-focused framework validation

Attached framework: `qa_racpad_ts_automation`

### Architecture recognized

- Root npm workspaces: `db`, `shared`
- Root executable Playwright test directory: `src/test/specs`
- Root compiler scope: `playwright.config.ts`, `src/main/**/*.ts`, `src/test/**/*.ts`
- Root compiler-scoped TS/TSX files evaluated for dependency requirements: **224**
- Workspace `typecheck` support: **db = yes, shared = yes**
- Existing root typecheck orchestration: `npm run typecheck --workspaces --if-present`
- Existing root Playwright dependency: `@playwright/test ^1.60.0`
- Existing root TypeScript dependency: `typescript ^5.9.3`
- Existing root Node types: `@types/node ^22.15.21`
- Missing root `build` script: **Detected**

### Build/dependency proposal

AstraHeal proposes this workspace-aware build contract rather than generic root-only `tsc`:

```text
npm run typecheck && tsc --noEmit
```

Root compiler-scoped direct import analysis found `js-yaml`. The dependency and type package already exist in the RACPAD workspace/lock graph, so the exact proposal adds:

```text
js-yaml: ^4.1.0
@types/js-yaml: ^4.0.9
```

The guarded dynamic `imapflow` reference is backed by `src/main/api/docusign/types/imapflow.d.ts`; it is treated as ambient-declared/optional and is **not** blindly installed.

Exact deterministic files proposed for human review:

- `package.json`
- `package-lock.json`
- `.astraheal-playwright-standard.json`

The package-lock update changes only root package dependency metadata and only because the required package nodes are already present in the existing lock graph.

Applying all three files on an isolated RACPAD copy changed **only** those three non-cache files. Re-analysis after the approved repair reported **0 structural Playwright setup gaps** and retained the build contract `npm run typecheck && tsc --noEmit`.

### Regression check on the attached ACIMA framework

The same enhanced analyzer was run against `qa_acima_fixed`. It found **0 setup gaps**, added **no new dependency/build repair**, and continued to propose only the optional `.astraheal-playwright-standard.json` role-map. This confirms the RACPAD-specific workspace/dependency logic does not force equivalent changes onto an already valid non-workspace framework.

## Human-in-the-loop behavior

1. Framework structure/dependencies are analyzed without repository writes.
2. Missing build/dependency changes are prepared as exact before/after/diff content.
3. GUI displays the workspace-aware build strategy and dependency plan.
4. User can remove any proposed file from the approval list.
5. Only approved files are written and existing approved files are backed up.
6. Stale approval is rejected if the framework changes after review.
7. Final validation then runs the four required commands exactly once.
8. Command-generated changes to unapproved project-controlled files remain protected/restored.

## Live RACPAD command evidence

On a repaired copy of the attached RACPAD framework:

- `npm config set registry https://registry.npmjs.org/`: **Passed**
- `npm config get registry`: returned `https://registry.npmjs.org/`
- Deterministic repaired `package-lock.json`: accepted by `npm install --package-lock-only --offline --ignore-scripts`
- Offline lock validation result: **62 packages audited, 0 vulnerabilities**

The execution container cannot resolve the public npm registry hostname (`curl: (6) Could not resolve host: registry.npmjs.org`). A real external dependency download therefore cannot complete in this environment, so `npx playwright install chromium` and the final live RACPAD `npm run build` are **not claimed as passed**. On a machine with npm/DNS access, AstraHeal will execute those commands in the production sequence above.

## Compatibility / regression boundary

No functional changes were made to:

- framework discovery/code-graph cache behavior;
- LangGraph agent ordering;
- AI provider routing;
- functional walkthrough;
- test generation;
- locator/page/helper reuse;
- MCP preparation;
- distributed execution;
- RCA/self-healing;
- report pipeline;
- API capability code;
- v0.7.3 human approval/fingerprint/backups.

The only graph-level timing change is scoped to `workflow == "framework_fix"`: prerequisite commands are deferred from the gap-analysis node to the existing final validation node so repair occurs first.

## Repository sample cleanup

The v0.7.3 cleanup remains intact. The release ships `generated-playwright` and does not restore the removed API sample roots.

## Final packaged artifact verification

A release candidate ZIP was created with the final source layout, extracted into a clean directory and validated from the extracted artifact:

- `python -m pytest -q`: **111 passed**
- `python -m unittest discover -s tests -q`: **57 passed**
- GUI inline JavaScript `node --check`: **Passed**
- FastAPI application import: **Passed**
- Registered FastAPI routes: **181**
- Registered guarded agent tools: **12**
- Version metadata: **0.7.4**
- Generated sample roots: **`generated-playwright` present; API sample roots absent**

The final release is packaged as `AstraHealAI_V11_Autonomous_LangGraph_v0.7.4.zip`; no code changes were made after the candidate regression gate, only this validation-report result section was finalized before the final ZIP was regenerated and checked again.
