# Provider confirmation fix

This build fixes the AI Provider confirmation button.

## Fixed behavior

When the user selects an AI provider in the GUI and clicks **Backend-confirm selected AI provider**, the GUI now sends the selected dropdown value and the current provider fields to the backend.

Expected backend confirmation:

- `Codex CLI` validates Codex CLI login only.
- `DeepSeek API` validates DeepSeek API key/base URL/model only.
- `OpenAI API` validates OpenAI API key/base URL/model only.
- `Ollama` validates Ollama host/model only.
- `Rule-based only` validates with no external AI.

## Important

OpenAI and DeepSeek do not require Codex login.

Codex is used only when the selected provider is Codex CLI or a direct Codex patch action is explicitly chosen.

## Recommended check

1. Open Start Here → AI connection.
2. Select DeepSeek or OpenAI.
3. Enter API key, base URL, and model.
4. Click **Backend-confirm selected AI provider**.
5. The status panel must show the same selected provider, not Codex.

If API credentials are missing, the backend should show `missing_configuration` for DeepSeek/OpenAI, not Codex login failure.
