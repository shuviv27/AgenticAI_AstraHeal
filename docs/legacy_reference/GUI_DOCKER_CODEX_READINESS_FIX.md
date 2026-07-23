# GUI Docker + Codex Readiness Fix

This build keeps the existing source-scoped Jira, distributed execution, App Intelligence, RCA/self-healing, Playwright MCP, Docker enterprise stack, Codex/Ollama, and reporting features intact.

## Fixes included

1. **Connect Selected AI Provider is non-blocking now**
   - The GUI shows a provider-selection popup.
   - Codex browser login and device-auth login are launched in a separate terminal/window.
   - The GUI returns immediately instead of waiting for the interactive Codex process.
   - After login, click **Check Codex/Ollama session** or **Refresh readiness gate**.

2. **Fast AI readiness check**
   - The GUI no longer runs a full Ollama chat call during every readiness refresh.
   - It uses a quick `/api/tags` probe for Ollama only when Ollama is selected.
   - This prevents the GUI from appearing stuck when Ollama is not running.

3. **Mandatory Docker stack readiness is more robust**
   - `langsmith-bridge` stays running even when LangSmith SaaS credentials are not configured; it reports configured/unconfigured separately.
   - `github-mcp` and `jira-mcp` are GUI-managed readiness bridges so Docker readiness is not blocked before credentials are entered.
   - Jira API connectivity is still validated through the JIRA page.
   - GitHub authentication should be validated before PR/repo actions.

4. **Langfuse container stability**
   - Langfuse is pinned to the v2 image and supplied with required local development values.

## Recommended flow

1. Start Docker Desktop.
2. Start GUI using `START_GUI_WINDOWS.cmd`.
3. Open `http://127.0.0.1:8080`.
4. Go to **Enterprise Stack** and click **Pull images + start mandatory stack**.
5. Wait for Docker readiness to turn green.
6. Go to **Codex / Ollama** and click **Connect AI provider**.
7. Choose:
   - `1` for Codex browser login,
   - `2` for Codex device-auth login,
   - `3` for Ollama model.
8. Complete Codex login in the launched terminal/window.
9. Click **Check Codex/Ollama session** or **Refresh readiness gate**.
10. Continue with JIRA/SRS, functional testcases, Playwright generation, distributed execution, RCA and self-healing.
