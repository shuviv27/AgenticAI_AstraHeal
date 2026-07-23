# AstraHealAI Fix: TypeScript Path Alias RCA and Runtime Resolver

## Why this fix was added

Some enterprise Playwright repositories compile or load TypeScript files that use aliases from `tsconfig.json`, for example:

```ts
import { environment } from '@config/environment';
```

In the RACPAD framework, `tsconfig.json` maps aliases such as:

```jsonc
"@config/*": ["src/main/config/*"],
"@fixtures/*": ["src/test/resources/fixtures/*"],
"@dataLoader/*": ["src/test/resources/data-loader/*"],
"@pages/*": ["src/main/pages/*"],
"@base/*": ["src/main/ui_base/*"]
```

When Playwright/Node starts without a runtime alias resolver, it can fail before the browser opens:

```text
Error: Cannot find module '@config/environment'
Require stack:
- src/test/resources/fixtures/accountmanagement/test-fixture.js
- src/test/specs/accountmanagement/past-due-contact-logs.spec.ts
```

This is a framework module-resolution problem, not a DOM, locator, or Playwright MCP locator problem.

## What changed

1. AstraHeal now reads `tsconfig.json` / `jsconfig.json` with JSONC support, including comments and trailing commas.
2. Deep framework learning and failed-spec scoping now resolve aliases such as `@config`, `@dataLoader`, `@testData`, `@reporters`, `@api`, `@base`, `@fixtures`, and `@pages`.
3. Playwright execution now generates and preloads a dependency-free runtime resolver file under:

```text
<framework>/reports/existing-framework/.astraheal-tsconfig-paths-register.cjs
```

4. The resolver is injected through `NODE_OPTIONS=--require ...` during:
   - sequential local execution,
   - failed-only reruns,
   - distributed local/VM shards,
   - BrowserStack shards,
   - Playwright `--list` test-count preflight.
5. RCA now classifies `Cannot find module`, `MODULE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, and `Require stack` as `typescript_path_alias_or_module_resolution`.
6. Plain-English RCA and safe-fix plans now recommend config/runtime alias fixes first and explicitly avoid locator edits for module-resolution errors.

## BrowserStack note

BrowserStack remains execution-only. AI learning, RCA, self-healing, safe-fix planning, memory, and reports remain on the central VM/local AstraHeal process. BrowserStack shard execution inherits the generated alias runtime environment so the same enterprise alias-heavy framework can run remotely without changing BrowserStack AI responsibilities.

## Guardrails preserved

- No automatic source edit is made just because an alias resolver is needed.
- The generated resolver lives in reports and is runtime-only.
- Any permanent framework change to `package.json`, `tsconfig.json`, `playwright.config.*`, or bootstrap files remains subject to human approval, backup, policy validation, and failed-only rerun validation.
- Passed tests remain out of RCA/self-healing scope.
