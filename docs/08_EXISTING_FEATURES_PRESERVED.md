# Existing features preserved

This cleanup changed startup surface and worker-agent naming only. Backend modules and feature flows are preserved:

- AstraHeal AI branding and `/astraheal-ai` route
- `/api/module2` backward-compatible API routes
- `/api/astraheal` routes
- AI provider backend confirmation
- DeepSeek/OpenAI/Codex/Ollama/deterministic provider selection
- MCP readiness preflight
- MCP readiness build-fix selected-provider routing
- Framework learning
- Existing Playwright framework execution
- Distributed node-hub execution
- Central VM + worker VMs mode
- RCA/self-healing
- Human approval popup
- Rollback/backup
- Framework-local `.aiqa-history` reports

Removed items are only confusing legacy root startup wrappers.
