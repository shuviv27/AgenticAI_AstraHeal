# AstraHeal AI - AI Provider Backend Confirmation and VM Workflow Guide

This guide explains how to configure Codex, DeepSeek, OpenAI, Ollama, or Rule-based mode and how the actual execution flow works in three deployment styles.

## 1. Important provider rule

AstraHeal AI now confirms the selected AI provider from the backend before AI-backed MCP readiness build fixes.

The GUI shows:

- selected provider
- backend connection status
- whether Codex login is required
- whether API key mode is used
- whether the provider is safe for MCP readiness build fix
- provider message from the backend

No silent provider switch is allowed for MCP readiness build fixes.

| Selected provider | Backend validation | Login/key requirement | Used for MCP readiness build fix |
|---|---|---|---|
| Codex CLI | checks Codex CLI availability and login status | `codex login` | Codex applies direct patch |
| DeepSeek API | checks key/base URL/model and performs live API probe | DeepSeek API key | DeepSeek guidance + guarded local TypeScript patcher |
| OpenAI API | checks key/base URL/model and performs live API probe | OpenAI API key | OpenAI guidance + guarded local TypeScript patcher |
| Ollama | checks Ollama host and model availability | local model only | Ollama guidance + guarded local TypeScript patcher |
| Rule-based only | no external AI | no login/key | guarded local TypeScript patcher only |

## 2. Configure providers on a VM

Open AstraHeal AI:

```text
http://127.0.0.1:8080/astraheal-ai
```

Go to:

```text
Start Here > AI connection
```

### Codex CLI

1. Select `Codex CLI`.
2. Click `Fresh Codex login`.
3. Complete Codex device/browser login.
4. Click `Backend-confirm selected AI provider`.
5. Expected message:

```text
Backend confirmed Codex CLI is available and authenticated.
```

Codex requires CLI login. It does not use OpenAI/DeepSeek API keys from this GUI.

### DeepSeek API

1. Select `DeepSeek API`.
2. Open `Optional API provider keys / endpoints`.
3. Enter:

```env
DEEPSEEK_API_KEY=<your key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

4. Click `Save & validate selected AI provider from backend`.
5. Expected message:

```text
Backend confirmed deepseek connection using API key/base URL/model. No Codex login is required.
```

### OpenAI API

1. Select `OpenAI API`.
2. Open `Optional API provider keys / endpoints`.
3. Enter:

```env
OPENAI_API_KEY=<your key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

4. Click `Save & validate selected AI provider from backend`.
5. Expected message:

```text
Backend confirmed openai connection using API key/base URL/model. No Codex login is required.
```

### Ollama

1. Select `Ollama`.
2. Ensure Ollama is running on that machine:

```powershell
ollama serve
ollama pull llama3
```

3. Set host/model in GUI or `.env`:

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
```

4. Click `Backend-confirm selected AI provider`.

### Rule-based only

Select `Rule-based only` when you want no external AI. MCP readiness known TypeScript fixes can still be attempted using deterministic safe rules.

## 3. Permanent VM configuration using .env

For permanent Central VM configuration, create/update `.env` in the AstraHeal AI solution folder.

Example for DeepSeek:

```env
AIQA_DEFAULT_PROVIDER=deepseek
CODEGEN_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

Example for OpenAI:

```env
AIQA_DEFAULT_PROVIDER=openai
CODEGEN_PROVIDER=openai
OPENAI_API_KEY=<your key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

Example for Codex:

```env
AIQA_DEFAULT_PROVIDER=codex
CODEGEN_PROVIDER=codex
AIQA_CODEX_PATCH_LOCATION=central_only
```

Then run:

```powershell
python scripts\validate_vm_startup.py
START_MODULE_GUI_VM_WINDOWS.cmd
```

## 4. Workflow A - Local PC only

Use this when the application under test and Playwright framework run on your local Windows/Mac.

```text
Local PC
  = AstraHeal AI GUI/backend
  = Playwright framework
  = AI provider
  = browser execution
```

Steps:

1. Extract AstraHeal AI to a short path, for example `C:\AstraHealAI`.
2. Start GUI.
3. Configure AI provider and backend-confirm it.
4. Enter local Playwright framework path.
5. Deep learn framework.
6. Run MCP readiness preflight.
7. Run tests / RCA / self-healing locally.

Best provider choice:

- Codex for direct code patching.
- DeepSeek/OpenAI for trial guidance and safe MCP readiness TypeScript fixes.

## 5. Workflow B - Single VM only

Use this when everything must run on the Central VM.

```text
VM177
  = AstraHeal AI GUI/backend
  = Playwright framework source
  = AI provider config
  = browser execution
  = reports/history
```

Steps:

1. Extract to `C:\AstraHealAI` on VM177.
2. Keep Playwright framework under a short path, for example:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

3. Start GUI on VM177.
4. Configure AI provider on VM177.
5. Click `Save & validate selected AI provider from backend`.
6. Enter framework path.
7. Deep learn framework.
8. Run tests locally on VM177.
9. Use MCP preflight/fix/RCA/self-healing.

## 6. Workflow C - Central VM + Worker VMs

Recommended enterprise model.

```text
VM177 - Central VM
  = AstraHeal AI GUI/backend
  = AI provider connection
  = framework source-of-truth
  = RAG memory
  = RCA/self-healing
  = consolidated reports

VM45 / VM135 - Worker VMs
  = browser execution
  = optional MCP/browser evidence
  = no independent framework patching
```

Steps on VM177:

1. Extract solution to `C:\AstraHealAI`.
2. Put Playwright framework in:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

3. Share the framework path if workers need shared read access:

```text
\\VM177\AIQA_Frameworks\client-playwright-framework
```

4. Start GUI on VM177.
5. Configure AI provider on VM177.
6. Backend-confirm selected AI provider.
7. Deep learn framework.
8. Choose execution target:

```text
Central VM + worker VMs
```

9. Start worker agents on VM45 and VM135.
10. Run distributed/node-hub execution from VM177 GUI.

Steps on VM45/VM135:

1. Install Node.js, npm and Playwright browsers.
2. Verify VM177 GUI connection:

```powershell
Test-NetConnection <VM177-IP> -Port 8080
```

3. Verify framework share if used:

```powershell
dir "\\<VM177-IP>\AIQA_Frameworks\client-playwright-framework"
```

4. Start worker agent.

AI provider should usually be configured only on VM177 because VM177 is the AI brain. Worker VMs should collect browser/MCP evidence and execute tests.

## 7. MCP readiness build-fix workflow

When you click `Prepare Playwright MCP assist`:

1. Backend runs MCP readiness preflight.
2. It checks `package.json`.
3. It runs `npm run build` if a build script exists.
4. It runs `npx playwright test --list`.
5. It checks Playwright browser readiness.
6. If build/list fails, GUI shows the exact error and asks:

```text
Fix with selected AI provider
Continue MCP without build
Cancel
```

When you choose fix:

1. Backend confirms selected AI provider again.
2. If not confirmed, no fix starts.
3. If confirmed, selected provider is used:
   - Codex direct patch, if Codex selected and logged in.
   - DeepSeek/OpenAI/Ollama guidance + guarded local TypeScript patcher.
   - Rule-based guarded local TypeScript patcher only.
4. Backup is created.
5. MCP preflight reruns.
6. GUI shows changed files and remaining errors if any.

## 8. Troubleshooting messages

### DeepSeek/OpenAI configured but not confirmed

Check:

- API key copied correctly
- base URL correct
- model name correct
- VM can reach internet/provider endpoint
- corporate proxy/firewall permits the API endpoint

### Codex selected but not confirmed

Run:

```powershell
codex login
codex doctor --json
```

### Worker VM cannot connect

From worker VM:

```powershell
Test-NetConnection <VM177-IP> -Port 8080
```

If false, open firewall on VM177 or use client-approved network route.

