# Fixed in v9: Windows UTF-8 + AI Provider Fallback

## Issue fixed

On Windows, uploaded SRS/PDF/DOCX text can contain Unicode characters such as non-breaking hyphen (`U+2011`), smart quotes, bullets, and non-breaking spaces. When Codex CLI was invoked through Python `subprocess`, Windows attempted to encode stdin using the local console code page (`cp1252`). That caused this error:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\u2011'
```

## Fix included

- Codex CLI subprocess now forces UTF-8 pipes: `encoding="utf-8", errors="replace"`.
- Prompt text is normalized before being sent to Codex.
- Windows launcher scripts set:
  - `PYTHONUTF8=1`
  - `PYTHONIOENCODING=utf-8`
  - `chcp 65001`
- The GUI no longer returns HTTP 500 when Codex/Ollama fails.
- If AI fails, the pipeline safely falls back to deterministic testcase JSON and shows the AI error in the GUI response.

## Recommended usage

1. Start Docker stack.
2. Verify Codex/Ollama.
3. Upload SRS.
4. Generate functional testcases.
5. If Codex fails, use Ollama or deterministic fallback and continue the pipeline.

## Why fallback exists

AI is used for requirement understanding and testcase refinement. The deterministic fallback is a guardrail so a demo or pipeline run does not stop because of an LLM/session/network issue.
