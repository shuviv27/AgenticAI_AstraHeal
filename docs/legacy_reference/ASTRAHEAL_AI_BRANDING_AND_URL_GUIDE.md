# AstraHeal AI Branding and URL Guide

This build replaces the visible **Module 2** product naming with:

```text
AstraHeal AI — Multi-Agent Playwright Automation Studio
```

## Browser URLs

Use the branded GUI route:

```text
On the Central VM:
http://127.0.0.1:8080/astraheal-ai

From another VM/VDI:
http://<Central-VM-IP>:8080/astraheal-ai
```

The root URL still works for backward compatibility:

```text
http://127.0.0.1:8080
```

## Branded API alias

The GUI now calls branded API paths such as:

```text
/api/astraheal/existing/prepare-ai-rag
/api/astraheal/distributed/plan
/api/astraheal/agentic-nodehub/run
```

For backward compatibility, existing internal routes are still supported:

```text
/api/module2/...
```

The FastAPI middleware rewrites `/api/astraheal/...` internally to `/api/module2/...` so old scripts, saved bookmarks, and automation hooks do not break.

## What changed in the GUI

Visible product name changed from **Module 2** to **AstraHeal AI**.

The GUI header now shows:

```text
AstraHeal AI
Multi-Agent Playwright Automation Studio
Agentic RAG + Distributed Execution + RCA + Self-Healing
```

## Why old routes were not deleted

Enterprise users may already have:

- bookmarks
- scripts
- API calls
- documentation
- worker-agent integrations

that still use `/api/module2/...`. Those routes remain active to avoid breaking existing functionality.
