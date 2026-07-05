# MCP Readiness AI Provider Routing Guide

This build fixes provider confusion in the MCP readiness build-fix flow.

## Previous confusing behavior

The GUI label said **Fix with Codex** and the MCP readiness fix path was Codex-first. If you selected DeepSeek or OpenAI, the message could still refer to Codex.

## New behavior

The GUI now says **Fix with selected AI provider**.

Provider routing is explicit:

| Selected provider | Login/API requirement | How MCP readiness fix works |
|---|---|---|
| Codex CLI | `codex login` required | Codex directly applies a local patch inside the framework workspace. |
| OpenAI API | API key/base URL/model required, no Codex login | OpenAI provides API-key guidance; the local safe patcher applies only known TypeScript readiness fixes. |
| DeepSeek API | API key/base URL/model required, no Codex login | DeepSeek provides API-key guidance; the local safe patcher applies only known TypeScript readiness fixes. |
| Ollama | Local Ollama model running | Ollama provides local guidance; the local safe patcher applies only known TypeScript readiness fixes. |
| Rule-based only | No AI login/key | Only known deterministic TypeScript readiness fixes are attempted. |

## Important security and audit behavior

OpenAI and DeepSeek are API-key providers. They do not need interactive login.

Codex is a CLI provider. It requires CLI authentication on the VM where the patch is executed.

To avoid uncontrolled source-code edits from remote API text, OpenAI/DeepSeek do not directly write arbitrary files. The system uses their guidance and then applies a narrowly scoped local patcher only for known safe TypeScript readiness patterns, such as:

- `Element.offsetParent` -> cast to `HTMLElement`
- `catch (e)` unknown -> safe `e instanceof Error ? e.message : String(e)` conversion
- `page.locator("text=a", "text=b")` misuse -> `getByText(/a/i)`

All changed files are backed up under:

```text
<framework>/.aiqa-history/backups/
```

The MCP readiness report is written under:

```text
<framework>/.aiqa-history/reports/mcp-readiness-preflight.html
<framework>/.aiqa-history/reports/mcp-readiness-preflight.json
```

## Recommended usage

1. Select your provider in **Start Here > AI connection**.
2. Save API keys/endpoints in the GUI or `.env`.
3. Click **Check AI status**.
4. Run MCP readiness preflight.
5. If build fails, choose **Fix with selected AI provider**.

If you want Codex direct file patching, select Codex and run Fresh AI login first.
If you want DeepSeek/OpenAI trial mode, select DeepSeek/OpenAI and ensure the API key is configured.
