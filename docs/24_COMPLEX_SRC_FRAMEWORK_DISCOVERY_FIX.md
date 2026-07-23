# AstraHeal Complex `src/` Playwright Framework Discovery Fix

## Purpose
This build enhances AstraHeal existing-framework discovery and deep learning for enterprise Playwright repositories that do not keep tests at root `tests/**`.

Supported executable spec roots now include:

- `tests/**`
- `src/test/specs/**`
- `src/test/**`
- `src/tests/**`
- `test/specs/**`
- `specs/**`
- `e2e/**`
- configured Playwright `testDir` when it is statically readable from `playwright.config.*`

## Example supported structure

```text
src/
  main/
    api/
    config/
    pages/
    ui_base/
  test/
    specs/
      moduleName/
        test1.spec.ts
```

## What changed

1. **Find scripts in framework** now discovers specs under approved nested roots such as `src/test/specs/**`, not only root `tests/**`.
2. Hierarchical test-case discovery supports common wrapper style such as:

```ts
testDetails({...})("Some test title", async ({ page }) => {})
```

3. Deep Learn framework memory now records executable test roots, executable spec count, and sample executable specs.
4. Playwright JSON/report normalization maps testDir-relative paths back to the real framework path, for example:

```text
accountmanagement/login.spec.ts
=> src/test/specs/accountmanagement/login.spec.ts
```

5. Business module folders named `reports` under `src/test/specs/reports/**` are not blocked as generated report folders.
6. File scanning now prunes heavy ignored folders before descending into them, so Deep Learn and Find Scripts remain responsive on large enterprise repos.
7. Existing root `tests/**`, local/VM execution, BrowserStack execution-only adapter, RCA, self-healing, failed-only rerun, combined reports, and report routing are preserved.

## Validation performed

- Python syntax validation passed.
- GUI app import passed.
- Frontend JavaScript syntax validation passed.
- Uploaded `qa_racpad_ts_automation` repository was inspected.
- `src/test/specs/**` discovery returned 60 executable spec files.
- Module folder filter `src/test/specs/dashboard` returned dashboard specs.
- Custom `testDetails({...})("title")` wrapper test-case discovery was validated.
- Distributed local/VM plan accepted `src/test/specs/**` targets.
- BrowserStack execution-only plan accepted `src/test/specs/**` targets.
