# Prerequisites and Version Compatibility

## Recommended versions

| Component | Recommended version | Why |
|---|---|---|
| Python | 3.12.x | Stable library compatibility and modern typing |
| Node.js | 20 LTS or 22 LTS | Stable npm/npx and Playwright support |
| npm | Bundled with Node.js | Needed for Playwright TypeScript build/test |
| Playwright | Installed from generated-playwright/package.json | Test runner and browser automation |
| Codex CLI | Latest installed locally | Optional AI coding assistant using local login session |
| Ollama | Latest local runtime | Optional open-source local LLM provider |
| Docker Desktop | Current stable | Optional infra stack: Redis/Postgres/Qdrant/MinIO/Ollama |

## Windows checks

```powershell
python --version
node --version
npm --version
npx --version
codex --version
ollama --version
```

## Mac checks

```bash
python3 --version
node --version
npm --version
npx --version
codex --version
ollama --version
```

## Install Playwright dependencies

```bash
cd generated-playwright
npm install
npx playwright install chromium
cd ..
```

## Common Windows issue

If Python says `No module named qa_pipeline`, you are not in the repo root or editable install was not completed.

Run from the folder containing `qa_pipeline/`, `pyproject.toml`, and `generated-playwright/`:

```powershell
python -m pip install -e .
python -m qa_pipeline.cli doctor
```
