# GUI Progress and Codex Login Fix - Module 2 Playwright TypeScript Generator

This build adds the missing percentage-based progress bar behavior and explicit Codex login actions.

## What changed

- Every backend action now shows a visible percentage from 3% to 100%.
- The progress panel shows the current phase and step-by-step checklist.
- Recent runtime events are appended after the action completes.
- `Connect Codex/Ollama` checks readiness and prompts the user to launch Codex login when Codex is not authenticated.
- `Launch Codex Device Auth` opens/runs `codex login --device-auth`.
- `Launch Codex Login` opens/runs `codex login`.
- `Run Codex Doctor` runs `codex doctor --json`.

## Why Codex credentials are not shown inside the GUI

The GUI must not collect ChatGPT/OpenAI usernames, passwords, or API keys for Codex CLI login. Codex CLI owns the secure authentication flow and stores its own local session. The GUI only launches or explains the CLI command.

## Local PC

1. Start the module GUI.
2. Go to Runtime Mode.
3. Select Local PC + Docker or No-Docker Host Runtime.
4. Click Connect Codex/Ollama.
5. If Codex is not logged in, click Launch Codex Device Auth.
6. Complete login in the terminal/browser.
7. Return to the GUI and click Connect Codex/Ollama again.

## VM/VDI

If Codex fixes run on the VDI, perform Codex login inside the VDI where the Runner Agent and framework workspace exist.
If Codex fixes run centrally on VM, perform Codex login on the VM.
