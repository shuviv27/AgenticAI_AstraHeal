# Runtime Logging, Review Gate and Grafana Enhancement

This build adds a strict source-driven flow for enterprise usage:

1. Start Docker Desktop.
2. Start GUI.
3. Start mandatory Docker enterprise stack from GUI.
4. Connect Codex or Ollama from GUI.
5. Save Project Setup with the real Application URL before JIRA/SRS/PDF input.
6. Generate functional testcases from the active source only.
7. Review and approve functional testcases in the Functional Testcases screen.
8. Generate reusable Playwright from the approved active source context only.
9. Run static review.
10. Execute headed/headless or distributed.
11. Review runtime logs, Grafana, reports and self-learning suggestions.

## Why Playwright generation may be controlled sequential

Functional testcase generation can run in parallel because each Jira story/source block writes isolated JSON/Markdown files. Playwright generation is correctness-first because multiple stories for the same web app often update the same page class and pageObjects file. Blind parallel writes can corrupt reusable framework files. This build runs one AI batch preflight and then serializes guarded framework writes when shared page/pageObjects files are detected.

## Runtime logs

Runtime events are written to:

- `.qa-cache/runtime/runtime-events.jsonl`
- `.qa-cache/runtime/current-status.json`
- `generated-playwright/reports/runtime-summary.json`
- `generated-playwright/reports/runtime-summary.md`

GUI endpoint:

- `GET /api/runtime/logs`
- `GET /api/runtime/status`
- `GET /metrics`

Prometheus scrapes the GUI runtime metrics at `host.docker.internal:8080/metrics`.
Grafana auto-provisions a dashboard named `AI QA Pipeline Runtime Progress`.

## Source isolation

A fresh build does not include old generated `acima.spec.ts` or old default SRS testcase files. After JIRA Epic fetch, the active context locks to the returned child stories/tasks/bugs. Playwright generation and execution use only that context.

## Mandatory Project Setup

The backend blocks JIRA/SRS/PDF testcase generation when no Application URL is saved/provided. This prevents empty steps like `Open browser and navigate to` and improves app crawling/locator strategy.
