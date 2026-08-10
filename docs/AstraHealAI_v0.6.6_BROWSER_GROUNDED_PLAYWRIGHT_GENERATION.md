# AstraHeal AI v0.6.6 — Browser-Grounded Complete Playwright Generation

**Build:** `0.6.6`  
**Date:** 28 July 2026

## Problem corrected

Previous builds could produce a readable spec that called page-object methods, but the GUI did not make the generated page methods, locator repository and test-data module sufficiently visible. Browser walkthrough evidence was also either a separate blocker or ignored during generation.

The generation action is now one integrated, non-blocking pipeline:

1. Parse Excel/document/Jira/BDD scenarios.
2. Extract scenario-specific credentials into volatile memory.
3. Inspect the selected framework and reuse existing methods/locators.
4. Optionally open a real Playwright browser and follow testcase goals.
5. Use the selected AI provider only for ambiguous live-page decisions.
6. Discover safe intermediate actions, such as `Log In to Sandbox`.
7. Verify locators against the exact live element.
8. Generate the complete Page Object Model contract.
9. Validate spec → page method → locator repository references.
10. Run TypeScript syntax and Playwright discovery validation.
11. Optionally execute the new specs sequentially.

Browser access improves generation but does not block source creation if the AUT, browser, MCP package or credentials are unavailable.

## Generated artifacts

Every scenario receives an individual spec. The feature also receives coordinated support files:

```text
tests/generated/<feature>-<scenario>.spec.ts
pages/<Page>.ts
pageObjects/<Page>.objects.ts
testData/<feature>.data.ts
testData/<feature>.env.example
```

The spec remains intentionally business-readable and delegates technical browser interaction to page methods. The page methods contain Playwright actions and assertions. The locator repository contains SmartLocator candidate bundles or browser-verified locators. The data module contains ordinary testcase data and environment-variable references for sensitive values.

## Adaptive multi-stage navigation

A spreadsheet step is treated as a business goal, not necessarily one literal click. If the password field is absent, the agent can safely discover and insert a prerequisite:

```text
Enter username
Click Log In to Sandbox       ← verified live prerequisite
Enter password
Click Login
```

Every inserted action must be backed by a unique live locator. Safe authentication prerequisites discovered for one scenario are propagated to other independent tests that start on the same application and have the same parent goal, because every generated Playwright test starts with a new page/context.

## AI provider use

The provider gateway supports Codex, OpenAI, DeepSeek, Perplexity and Ollama. High-confidence accessible DOM matches are resolved locally to avoid hundreds of unnecessary provider calls. The provider is reserved for ambiguous controls and adaptive transitions.

Credentials are never included in provider prompts. Username/password values are consumed from the volatile credential vault and filled directly by the browser process.

## Playwright MCP and codegen

The generator writes and reports Playwright MCP configuration/readiness. The integrated browser agent uses Playwright accessibility and DOM evidence to execute and verify actions. It also writes a codegen-compatible replay file containing only verified locator actions with sensitive values omitted, and reports the standard `playwright codegen` command for supervised refinement.

## New structural gate

A Page Object contract validator now proves that:

- Every generated spec exists.
- Every spec imports a resolvable page class.
- Every `screen.method()` call has a corresponding page method.
- Every page-object locator reference resolves to an imported locator repository.
- Every referenced locator property is defined.

A contract failure triggers rollback before live execution.

## Attached workbook validation

The supplied workbook was processed in an isolated copy of `generated-playwright`.

| Result | Value |
|---|---:|
| Normalised scenarios | 10 |
| Volatile credential profiles | 10 |
| Generated individual specs | 10 |
| Specs containing ordered `test.step` blocks | 10 |
| Generated/reused page files | 1 |
| Generated/reused locator repository files | 1 |
| Created page methods | 92 |
| Created locator definitions | 90 |
| Provisional locator review items without live AUT access | 247 |
| Page Object contract issues | 0 |
| TypeScript parse diagnostics | 0 |
| Raw credential values in generated TypeScript | 0 |

The 247 review items do not block generation. On the target Central VM/VDI, integrated browser grounding should replace applicable provisional candidates with verified live locators before validation/execution.

## Safety and compatibility

The build retains:

- Existing-framework analysis and repair
- Generation-first behaviour
- Optional live execution
- Operation cancellation
- LangGraph/LangChain workflows
- LangSmith observability
- SQLite memory
- Distributed workers
- Grounded RCA and self-healing
- Backup and rollback
- Existing API aliases and GUI workflows

## Target-environment verification

The private Salesforce AUT was not accessible from the build environment. A final smoke test must therefore be performed on the Central VM/VDI with AUT network access, Playwright Chromium installed and the selected AI provider authenticated. The build does not claim that provisional locators are live-correct until browser evidence verifies them.
