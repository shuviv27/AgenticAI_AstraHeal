# Workflow 1: Local PC only

Use when the Playwright framework and AUT are accessible from your local Windows/Mac.

## Windows

```powershell
cd C:\AstraHealAI
START_GUI_LOCAL_WINDOWS.cmd
```

Open:

```text
http://127.0.0.1:8080/astraheal-ai
```

## Mac

```bash
cd ~/AstraHealAI
chmod +x START_GUI_LOCAL_MAC.sh
./START_GUI_LOCAL_MAC.sh
```

## GUI workflow

1. Start Here → backend-confirm selected AI provider.
2. Select the existing Playwright framework path.
3. Deep learn framework.
4. Run MCP readiness preflight.
5. Execute tests.
6. Run RCA/self-healing when tests fail.

No worker-agent script is needed in local-only mode.
