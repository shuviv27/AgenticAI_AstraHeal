# Playwright Execution Preflight Fix

## Root cause fixed

The runtime log showed every distributed shard failed before the browser launched:

```text
'playwright' is not recognized as an internal or external command,
operable program or batch file.
```

This means the generated Playwright project dependencies were not installed or were incomplete. The previous executor launched `npm --prefix generated-playwright test -- ...`; when `node_modules` was missing, the npm script could not resolve the local Playwright binary and no browser started. Because no shard produced a blob report, the merge step had nothing to merge and the GUI report URL returned `detail: not found`.

## Fix implemented

The executor now runs a mandatory Playwright runtime preflight before headed/headless execution:

1. Validate `npm` and `npx` are available.
2. Validate `generated-playwright/package.json` exists.
3. Check whether local Playwright is installed under `generated-playwright/node_modules`.
4. If missing, automatically run `npm install --registry=https://registry.npmjs.org/` in `generated-playwright`.
5. Verify `npx --no-install playwright --version`.
6. Ensure Chromium is available with `npx --no-install playwright install chromium`.
7. Execute tests with `npx --no-install playwright test ...` from the `generated-playwright` working directory.
8. If Playwright still cannot start, create a readable fallback report at `generated-playwright/reports/html/index.html` so the GUI never opens a missing report URL.

## Docker image clarification

Docker Desktop **Images** are downloaded templates. A green/present image does not mean a service is running. The pipeline needs **Containers** created by Docker Compose. Start containers from the GUI Enterprise Stack section or with:

```powershell
docker compose -f infra/docker/docker-compose.yml up -d
```

Do not click the play button beside individual images unless debugging manually. That starts an unconfigured raw container outside the compose stack and usually does not help the pipeline.
