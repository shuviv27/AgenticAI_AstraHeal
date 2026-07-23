# Demo and AI Provider Setup

## Recommended initial demo

Use **Codex CLI** if it is already configured with `codex login`. Use **Ollama** if local `llama3` is installed and running. The deterministic generator remains as a safety fallback and framework guardrail.

The pipeline now uses AI in two places when provider is Codex or Ollama:

1. Functional testcase planning from Jira/SRS/PDF/DOCX/manual steps.
2. Code-generation assistance after reading testcase JSON and framework inventory.

The final file write is still protected by the deterministic reuse guardrail so the generated Playwright does not become isolated or inconsistent.

## Example pasted input

```text
launch application as "https://your-application-url"
enter username as 'your_user'
enter password as 'your_password'
click 'Login' button
verify dashboard page is displayed
```

Expected spec style:

```ts
await loginPage.goto('https://your-application-url');
await loginPage.fillUsername('your_user');
await loginPage.fillPassword('your_password');
await loginPage.clickLoginButton();
```

The spec still calls only page methods. Locators are created/reused in `pageObjects`, not inline in spec.

## Codex CLI

Codex is configured through the local CLI session, not username/password in `.env`.

```bash
codex login
codex login --device-auth
```

In the GUI:

1. Click **Codex / Ollama**.
2. Click **Check Codex/Ollama**.
3. Confirm Codex is available and login is OK.
4. Select **Codex CLI login session** as provider.
5. Generate functional testcases, then Playwright.

If Codex is unavailable or login fails, the GUI explains the issue and safely falls back to deterministic guardrail generation.

## Ollama

```bash
ollama pull llama3
ollama serve
```

Set `.env` if required:

```text
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
```

## Docker

Docker Compose can start supporting services consistently:

- Redis for event-bus readiness.
- Postgres for metadata/run history readiness.
- Qdrant for RAG/vector search readiness.
- MinIO for screenshots, traces, and report artifacts.
- Ollama as an optional local LLM runtime.
- GUI app as an optional containerized runtime.

For a quick GUI demo, Docker is optional. For team onboarding and CI-like execution, Docker is recommended.
