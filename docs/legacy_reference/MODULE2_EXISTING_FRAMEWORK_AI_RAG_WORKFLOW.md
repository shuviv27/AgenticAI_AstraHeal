# Module 2 Existing Framework AI/RAG Workflow

This build makes existing-framework execution the primary workflow.

## Main user path

1. Start the Module 2 GUI.
2. Select runtime mode: Local PC, VM Control Plane, or VM + VDI Agent.
3. Choose Docker Runtime or No-Docker Host Runtime.
4. Open **Existing Framework**.
5. Paste the root folder of the already-created Playwright framework.
6. Click **Learn this framework with AI**.
7. Open **Run & Fix Tests**.
8. Click **Run all existing tests**.

This runs the current framework tests without generating a new script.

## Button naming

Technical labels were replaced with user-oriented labels:

- Understand Existing Framework -> Learn this framework with AI
- Execute Existing Framework -> Run all existing tests
- Analyze Existing RCA -> Explain failed tests
- Propose Existing Fix -> Create safe fix plan
- Apply Existing Fix -> Fix failed tests safely
- Rerun Existing Failed Only -> Run failed tests again

## Headed mode

The default is headed / visible-browser mode. This helps with popups, permissions, dynamic waits, locator issues and RCA validation.

## AI memory

Every major action is logged to:

- `.qa-cache/ai-memory/action-history.jsonl`
- `.qa-cache/ai-memory/action-memory-summary.json`
- `generated-playwright/reports/ai-action-history.html`

This is safe observable history, not hidden chain-of-thought. It can be reused as context by Codex/Ollama during RCA and self-healing.
