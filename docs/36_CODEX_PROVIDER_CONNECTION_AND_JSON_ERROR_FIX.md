# Codex Provider Connection and JSON Error Fix — v0.6.1

## Reported symptoms

The GUI showed:

```text
SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON
```

The backend log showed:

```text
NameError: name 'cwd' is not defined
POST /api/llm/codex/login 500 Internal Server Error
```

A separate Windows asyncio message was also visible:

```text
ConnectionResetError: [WinError 10054]
```

## Root cause

The v0.5.2 Codex login endpoint evaluated:

```python
launch_cwd = Path(cwd or REPO_ROOT).expanduser().resolve()
```

but `cwd` was not declared in the endpoint parameters. FastAPI therefore returned a plain-text 500 response. The browser then called `response.json()`, producing the secondary JavaScript syntax error.

The WinError 10054 callback is a Windows connection-reset message commonly seen when a browser, SSE client, terminal, or HTTP connection closes. It was not the source of the undefined-variable failure.

## Changes in v0.6.1

### Backend

- Added `cwd: str = Form("")` to the Codex login endpoint.
- Invalid or missing working directories fall back safely to the AstraHeal root.
- Added a global API exception handler that always returns JSON.
- Added `/api/llm/codex/status` for version and login-status checks.
- Reworked `/api/llm/codex/doctor` so login status is authoritative even when a Codex CLI version does not support `doctor --json`.
- Unified legacy Codex login routes with the same safe implementation.
- Codex login opens in a separate interactive terminal without captured subprocess pipes.
- The login route returns immediately and never waits for credentials or OAuth completion.

### GUI

- Added a safe `readApiResponse()` function.
- Plain-text or empty backend errors are converted into readable diagnostic objects.
- Added **Check Codex login status**.
- Renamed the diagnostic action to **Run Codex health diagnostics**.
- Only the Codex provider launches Codex login.
- OpenAI, DeepSeek, Perplexity, Ollama, Claude CLI, Copilot CLI, and deterministic mode use backend confirmation instead of accidentally launching Codex.

## Recommended flow

1. Select **Codex CLI**.
2. Click **Fresh Codex login**.
3. Complete authentication in the separate terminal/browser.
4. Click **Check Codex login status**.
5. Click **Backend-confirm selected AI provider**.
6. Use **Run Codex health diagnostics** only when deeper diagnostics are needed.

## Manual commands

```bash
npm install -g @openai/codex
codex --version
codex logout
codex login
codex login --device-auth
codex login status
```

For a VM/VDI, run the login in the same Windows user session that runs AstraHeal. Device authentication may need to be enabled in the ChatGPT account or workspace security policy.

## Validation

- Python compilation passed.
- GUI JavaScript syntax passed.
- 58 automated tests passed.
- Four Codex/provider routes are uniquely registered.
- FastAPI application import passed.
- Error responses remain valid JSON.
- CLI-missing, successful-launch, terminal-blocked, invalid-path, and exception-handler cases are covered by tests.

A live Codex authentication flow was not performed in the build sandbox because Codex CLI was not installed and no user account was available.
