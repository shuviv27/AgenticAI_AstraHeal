# Headed execution, Fresh Codex Login and AI Memory

## What changed

- Playwright execution now defaults to **headed mode** for generated and existing frameworks.
- The GUI exposes a visible **Run Playwright in headed mode** checkbox.
- Codex is **not connected automatically**.
- Fresh Codex login runs `codex logout` first, then starts `codex login --device-auth` or `codex login`.
- Every major GUI/backend action is stored in `.qa-cache/ai-memory/action-history.jsonl`.
- The action history is also rendered at `generated-playwright/reports/ai-action-history.html`.

## Why headed mode by default?

Headed mode is better for complex enterprise apps because the browser is visible during execution. It helps with popups, browser permissions, app overlays, shadow DOM, dynamic waits, RCA review and self-healing validation.

## Fresh Codex rule

The GUI never asks for ChatGPT/OpenAI credentials. It also does not silently reuse Codex login for a fresh connection. When a user clicks Fresh Connect Codex, the system launches a terminal and starts with:

```powershell
codex logout
codex login --device-auth
```

Run this on the same machine where Codex will patch files: local PC for local mode, VM for VM-only mode, or VDI for Hybrid mode where fixes happen inside the VDI workspace.

## AI memory

The AI memory stores observable history, not hidden chain-of-thought. It contains execution starts, RCA outputs, self-healing proposals, patch results, failed-only reruns, Codex login actions and report pointers. Future RCA/self-healing prompts can use it to avoid repeating past mistakes.
