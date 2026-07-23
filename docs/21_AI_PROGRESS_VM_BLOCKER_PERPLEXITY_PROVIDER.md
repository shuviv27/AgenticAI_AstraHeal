# AI Progress, VM Slow-Mode, Browser Blockers and Perplexity Provider

This build adds visible progress for long AI operations without changing the existing execution/RCA/self-healing flow.

## Visible AI operation progress

The main progress panel now shows:

- waiting cursor while AI-heavy operations run
- percent completed / percent remaining
- latest backend stage message from `.qa-cache/runtime/runtime-events.jsonl`
- a warning if no backend event arrives for a long time

Covered operations include framework learning, MCP prepare/fix, AI full-control framework fix, failure explanation, safe-fix planning and approved self-healing apply.

Important: the percentage is progress/event based. It is designed to tell the user that the backend is still active on slow VM/VDI machines. It does not expose hidden private chain-of-thought.

## Slow VM/VDI handling

Long synchronous AI calls are moved to FastAPI's threadpool for the main RCA/self-healing/MCP/fix paths so the GUI can keep polling `/api/progress/events` while the backend works. Existing source patching, backup, rollback and report generation behavior is preserved.

The build keeps the 30-second explicit-wait cap:

```text
ASTRAHEAL_MAX_EXPLICIT_WAIT_MS=30000
```

Codex apply timeout remains configurable:

```text
ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS=300
```

## Browser and app-level blockers

The optional robust harness now includes:

```text
qa-ai-support/BrowserBlockerGuard.ts
```

It provides helpers to grant geolocation/notification permissions, handle dialogs/popups, and dismiss common cookie/modal/location blockers. Install it from:

```text
Run & Fix Tests -> Stability insights -> Install browser blocker / telemetry harness
```

This is additive. It does not rewrite existing specs automatically. AI self-healing can use the helper in a shared BasePage/fixture after human approval.

## Perplexity provider

Perplexity can now be selected in Start Here -> AI connection as an OpenAI-compatible API provider for RCA and fix-plan guidance. Codex CLI remains the recommended direct file patcher because it provides local workspace patching with backup and rollback.

Environment setup:

```bat
setx PERPLEXITY_API_KEY "your_key_here"
setx PERPLEXITY_BASE_URL "https://api.perplexity.ai"
setx PERPLEXITY_MODEL "sonar"
```

Or enter these values in the GUI and click **Save & validate selected AI provider from backend**.
