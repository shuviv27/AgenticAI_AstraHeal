# Live Runtime Logs, Progress Bar and Grafana Fix

## What this build fixes

1. The GUI progress bar no longer remains at 88% after execution has finished.
2. The GUI now polls `/api/runtime/status` during every long-running action and updates the progress bar from real runtime events.
3. Playwright distributed execution writes shard-level plain-English logs while execution is running.
4. The Runtime Logs tab can auto-refresh every 2 seconds.
5. `/runtime-console` provides a self-refreshing local live console that works even when Grafana is not accessible.
6. Grafana dashboard provisioning now mounts dashboard JSON correctly into the Grafana container.
7. Prometheus metrics include current progress, current stage/status, event counts by stage, and event counts by status.

## Preferred monitoring order

For normal users:

1. Open GUI: `http://127.0.0.1:8080`
2. Open **Runtime Logs** tab.
3. Click **Start live logs**.
4. Run Jira/SRS generation, Playwright generation, or execution in another tab/window.
5. Keep Runtime Logs tab open to see what the AI QA pipeline is doing.

For a separate simple monitor:

- Open `http://127.0.0.1:8080/runtime-console`

For enterprise dashboards:

1. Start Docker stack from GUI.
2. Open Grafana: `http://localhost:3001`
3. Login: `admin / admin`
4. Open folder `AI QA Pipeline` or `QA Pipeline`.
5. Open dashboard `AI QA Pipeline Runtime Progress`.

If Grafana dashboard is empty, open Prometheus targets:

- `http://localhost:9090/targets`

Confirm target `aiqa-gui-runtime` is UP. If it is DOWN, make sure GUI is running on port 8080.

## Why logs are visible even if Docker observability is inactive

The local Runtime Logs tab and `/runtime-console` read local files from `.qa-cache/runtime/` via the FastAPI GUI. They do not depend on Grafana or Prometheus.

Grafana/Prometheus are still the enterprise monitoring path, but local GUI logs are the fastest debug path.

## Playwright execution logging

Distributed execution now logs:

- execution plan
- runtime preflight
- npm/playwright/chromium checks
- shard launch
- shard line-reporter output
- shard completion
- merge report step
- final 100% completion event

This makes headed/headless execution easier to understand and debug.
