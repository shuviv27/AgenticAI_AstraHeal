# AI provider configuration

Configure providers on the machine that runs the AstraHeal AI GUI/backend.

## Central VM + workers

Configure AI only on VM177.

Workers do not need:

- Codex login
- OpenAI key
- DeepSeek key
- Ollama model

Workers only execute browser jobs and send evidence to VM177.

## DeepSeek

GUI → Start Here → AI connection:

```text
AI provider = DeepSeek API
DEEPSEEK_BASE_URL = https://api.deepseek.com
DEEPSEEK_MODEL = deepseek-chat
DEEPSEEK_API_KEY = <your key>
```

Click:

```text
Save & validate selected AI provider from backend
```

Expected:

```text
Backend confirmed deepseek connection. No Codex login required.
```

## OpenAI

```text
AI provider = OpenAI API
OPENAI_BASE_URL = https://api.openai.com/v1
OPENAI_MODEL = gpt-4.1-mini
OPENAI_API_KEY = <your key>
```

## Codex

Codex requires CLI login on VM177:

```powershell
codex login
codex doctor --json
```

Use Codex only when you want direct CLI patching. DeepSeek/OpenAI use API keys and safe AstraHeal local patch application for known readiness errors.
