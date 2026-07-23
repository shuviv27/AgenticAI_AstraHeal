# v11 Dynamic Web AI + Crawl Fixes

This build addresses dynamic web execution problems observed on modern websites.

## Fixed issues

1. **Wrong URL guard**
   - The backend now reads the saved GUI Project Setup `base_url` whenever a button does not explicitly pass the URL.
   - A URL guard scans normalized and AI-enhanced testcase JSON and replaces accidental `127.0.0.1` or `localhost` URLs with the user-provided application URL.
   - Generated specs now use scenario `start_url` or `BASE_URL`, not the GUI server URL.

2. **Browser permission handling**
   - Playwright config grants `geolocation` and `notifications` permissions.
   - `BasePage.goto()` grants permissions for the application origin before navigation.
   - Browser launch options use fake UI/device flags to reduce permission popups.

3. **Dynamic page visibility and scrolling**
   - `BasePage` now sets a large `1920x1080` viewport.
   - Click and verify helpers auto-scroll through the full page and bring elements into view before actions.
   - Common overlays/cookie banners are dismissed automatically when possible.

4. **Full DOM crawl before generation**
   - Before Playwright generation, the pipeline runs `generated-playwright/scripts/crawlDynamicPage.ts`.
   - The crawler opens the user-provided URL, grants permissions, scrolls the full page, captures a full-page screenshot, and writes:
     - `generated-playwright/reports/dynamic-dom-map.json`
     - `generated-playwright/reports/<feature>-full-page.png`

5. **Better AI prompt guardrails**
   - Codex/Ollama prompts explicitly forbid localhost/GUI URLs.
   - Prompts now instruct AI to use scenario `start_url`, `BASE_URL`, user-facing locators, page scrolling, and permission handling.

## Recommended GUI flow

1. Start Docker services.
2. Start Codex CLI or Ollama.
3. Launch GUI.
4. Project Setup: enter correct website URL, for example `https://www.acima.com/en`.
5. Save Project Config.
6. Upload SRS and generate functional testcases.
7. Generate Reusable Playwright. This step now crawls the live page first.
8. Run Static Review.
9. Execute Generated Test in headed mode first for demo, then headless for CI.
10. Open Enterprise HTML Report.

## Manual commands

```powershell
cd C:\AI_QA_V11
.\.venv\Scripts\Activate.ps1

# Install / validate Playwright
cd generated-playwright
npm install
npx playwright install chromium
npm run build
cd ..

# Start Docker infra
Docker Desktop must be running first.
docker compose -f infra/docker/docker-compose.yml up -d redis postgres qdrant minio

# Codex check
codex login
'Return JSON only: {"ok": true}' | codex exec --skip-git-repo-check --sandbox read-only -

# Start GUI
.\START_GUI_WINDOWS.ps1
```

## Manual Playwright execution

```powershell
cd C:\AI_QA_V11\generated-playwright
$env:BASE_URL="https://www.acima.com/en"
npx playwright test tests/generated/acima.spec.ts --project=chromium --headed
npx playwright show-report
```

## Important expectation

Microsoft Playwright MCP is included for AI/browser-assist readiness and configuration. Deterministic execution is still performed by Playwright Test because it produces stable reports, screenshots, videos, and traces suitable for CI and governance.
