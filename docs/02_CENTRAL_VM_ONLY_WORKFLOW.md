# Workflow 2: Single Central VM only

Use when everything runs on VM177 or one VM: GUI, AI provider, framework, browser execution, reports.

## Start on VM177

```powershell
cd C:\AstraHealAI
python scriptsalidate_vm_startup.py
START_GUI_CENTRAL_VM_WINDOWS.cmd
```

Open on VM177:

```text
http://127.0.0.1:8080/astraheal-ai
```

Open from another allowed machine:

```text
http://<VM177-IP>:8080/astraheal-ai
```

## Required on VM177

```powershell
python --version
node -v
npm -v
npx --version
git --version
```

For browser execution:

```powershell
cd D:\AI_QA_WORKSPACE\client-playwright-framework
npm install --registry=https://registry.npmjs.org/
npx playwright install
```

Worker-agent script is not needed in this mode.
