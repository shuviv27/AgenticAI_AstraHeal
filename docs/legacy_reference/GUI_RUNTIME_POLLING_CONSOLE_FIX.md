# GUI Runtime Polling Console Noise Fix

## What was observed
After launching the GUI, the terminal displayed repeated lines like:

```text
GET /api/runtime/status HTTP/1.1 200 OK
```

This is not a backend failure. It is caused by the browser GUI and runtime-console pages polling the runtime status endpoint so the progress bar and live logs can update.

## What changed
- Uvicorn access logging is now disabled by default for the GUI launcher.
- Runtime polling interval during active actions was reduced.
- Progress timers are cleared safely before starting a new action.
- A command-line option is available for debugging HTTP traffic:

```powershell
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080 --access-log
```

## Expected behavior
Normal GUI launch should show startup messages only:

```text
Starting AI QA Pipeline GUI...
Open: http://127.0.0.1:8080
Uvicorn running on http://127.0.0.1:8080
```

The repeated runtime status polling will still happen internally while the GUI is open, but it no longer floods the terminal.
