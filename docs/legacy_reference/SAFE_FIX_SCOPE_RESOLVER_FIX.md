# Safe Fix Scope Resolver Fix

## What the earlier warning meant

When the GUI showed:

> No allowed files resolved from failed specs. Automatic patching is blocked. Check the failed spec paths and import structure.

it meant the system found failed Playwright specs, but the self-healing guardrail could not safely map those specs to the framework files that are allowed to be patched.

The old resolver mostly handled simple relative imports such as:

```ts
import { LoginPage } from '../../pages/LoginPage';
```

Real enterprise Playwright frameworks often use more complex structures:

```ts
import { LoginPage } from '@pages/LoginPage';
import { loginLocators } from '@objects/LoginObjects';
```

or store failed specs as absolute Windows paths, partial filenames, or non-standard folders such as:

```text
tests/specs/ALL_login.specs.ts
C:\repo\client-framework\tests\specs\ALL_login.specs.ts
ALL_login.specs.ts
```

The guardrail was correct to block automatic patching instead of guessing. This build improves the resolver so it can safely identify allowed files without opening the entire repo to uncontrolled AI changes.

## What is fixed

The self-healing scope resolver now supports:

- Absolute Windows paths from execution logs.
- Partial spec names such as `ALL_login.specs.ts`.
- `tests/specs/**/*.spec.ts` and `tests/specs/**/*.specs.ts`.
- TypeScript path aliases from `tsconfig.json`.
- Common aliases such as `@pages/*`, `@pageObjects/*`, `@objects/*`, `@utils/*`, `@fixtures/*`, `@pom/*`.
- Conventional enterprise folders such as `src/pages`, `src/pageObjects`, `page-objects`, `helpers`, `fixtures`, and `utils`.
- Import graph walking up to five levels: spec -> page -> pageObject -> utility/helper.
- Limited token-matched fallback for POM/helper files when imports are dynamic or alias-heavy.

## What remains protected

The system still does not allow broad random repo patching. Codex/Ollama receives only the resolved allowed files from the failed-spec scope. The patch guardrails still block:

- unrelated files,
- passed specs,
- skipped tests,
- weakened assertions,
- blind waits,
- force click by default,
- environment/data/product-defect masking.

## Recommended workflow

1. Run selected existing tests.
2. Explain failed tests.
3. Check failed element with Playwright MCP.
4. Create safe fix plan.
5. Confirm the self-healing report shows allowed files.
6. Fresh Codex login if needed.
7. Click Fix failed tests safely.
8. Confirm changed files are listed.
9. Run failed tests again.
