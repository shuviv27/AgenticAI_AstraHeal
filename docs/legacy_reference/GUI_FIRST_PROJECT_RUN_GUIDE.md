# GUI-First Project Run Guide

## Goal

This build is designed so the user runs only one local launcher before opening the project GUI. After that, all project operations are controlled from the browser at:

```text
http://127.0.0.1:8080
```

The GUI controls:

- Docker / Docker Compose enterprise stack
- Codex CLI login/readiness
- Ollama model readiness if selected
- Project setup and application URL
- Existing Playwright framework understanding
- Existing Playwright framework execution
- Generated Playwright framework execution
- RCA and self-healing
- Failed-only rerun
- Selector health report
- Runtime logs and reports

## One file to run before GUI

### Windows

Double-click or run:

```powershell
START_AI_QA_GUI_WINDOWS.cmd
```

Alternative PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_AI_QA_GUI_WINDOWS.ps1
```

### Mac

```bash
chmod +x START_AI_QA_GUI_MAC.sh
./START_AI_QA_GUI_MAC.sh
```

### Linux

```bash
chmod +x START_AI_QA_GUI_LINUX.sh
./START_AI_QA_GUI_LINUX.sh
```

### Cross-platform direct command

```bash
python RUN_GUI_FIRST.py
```

or:

```bash
python3 RUN_GUI_FIRST.py
```

## What the launcher does

The launcher:

1. Creates `.venv` if missing.
2. Installs `requirements.txt` if dependencies are missing or stale.
3. Starts the FastAPI GUI on `127.0.0.1:8080`.
4. Opens the browser automatically.

It does **not** start Docker or run Codex automatically. Docker and Codex remain controlled from the GUI.

## First GUI workflow

1. Open `http://127.0.0.1:8080`.
2. Click **Verify prerequisites**.
3. Click **Start Docker stack**.
4. Click **Connect Codex/Ollama**.
5. Click **Refresh readiness**.
6. Choose either:
   - **Existing Framework Control** for an already-developed Playwright TypeScript framework.
   - **Full Pipeline Setup** for SRS/Jira/PDF to testcase and generated Playwright flow.

## Existing Framework Control workflow

Use this flow when the Playwright framework already exists.

1. Open **Existing Framework Control**.
2. Paste the framework root path.
3. Click **Understand Framework**.
4. Optionally click **Install Robust TS Harness**.
5. Click **Execute Existing - Headless** or **Execute Existing - Headed**.
6. If failures exist, click **Analyze Existing RCA**.
7. Click **Propose Existing Fix**.
8. Review the output.
9. Click **Apply Existing Patch** only if the confidence/policy gate allows it.
10. Click **Re-run Existing Failed Only**.
11. Click **Selector Health Report**.

## Full AI generation workflow

Use this flow when you want to generate scripts from Jira/SRS/PDF/DOCX.

1. Open **Project Setup**.
2. Save application URL, feature name, provider, and browser.
3. Open **Requirement Input**.
4. Upload/paste Jira/SRS/PDF/DOCX/manual steps.
5. Click **Generate functional testcases**.
6. Review and approve testcases.
7. Click **Generate reusable Playwright**.
8. Run review/static validation.
9. Execute headed/headless.
10. If failures exist, use **RCA & Self-Healing**.
11. Rerun failed only.
12. Open the final report.

## Important rule

Do not manually run scattered commands for normal usage. The intended user experience is:

```text
Run startup file → open GUI → control everything from GUI
```

Use terminal commands only for troubleshooting.
