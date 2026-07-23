# Client VDI / VMware Horizon VM Enterprise Runbook

This runbook is for running the AI QA Automation solution inside a client-hosted VDI, VMware Horizon desktop, Horizon VM, or locked-down enterprise Windows VM.

The target operating model is GUI-first:

1. Run one launcher file.
2. Open `http://127.0.0.1:8080`.
3. Control Docker, Codex/Ollama, Playwright Web, Playwright API, Rest Assured Java API, RCA, self-healing, failed-only rerun, and reports from the GUI.

---

## 1. What changed in this build

Added VDI/Horizon readiness support:

- New GUI tab: **VDI / Horizon Readiness**.
- New backend module: `qa_pipeline/core/vdi_readiness.py`.
- New endpoints:
  - `POST /api/vdi/profile/save`
  - `GET /api/vdi/profile`
  - `POST /api/vdi/readiness`
- New startup files:
  - `START_AI_QA_GUI_VDI_WINDOWS.cmd`
  - `START_AI_QA_GUI_VDI_WINDOWS.ps1`
  - `START_AI_QA_GUI_VDI_LINUX.sh`
- New generated reports:
  - `generated-playwright/reports/vdi-readiness-report.html`
  - `generated-playwright/reports/vdi-readiness-report.json`
  - `generated-playwright/reports/client-vdi-preflight-checklist.md`
- API Docker prereq button now writes runtime events, so the Runtime Logs tab will not simply stay at `No runtime events yet` after a Docker prereq check.

No existing web/API generation, existing-framework execution, RCA, self-healing, Docker, Codex/Ollama, or reporting behavior was removed.

---

## 2. Client IT preflight checklist

Before running the solution on a client VDI, collect answers for these items.

### 2.1 Desktop / VM

- Which desktop pool or Horizon image should be used?
- Is the desktop persistent or non-persistent?
- Does the user have local admin rights?
- Are Python, Node, Java, Maven, Git, Docker Desktop, or Codex preapproved?
- Is writing to `C:\AI_QA` or another non-OneDrive folder allowed?
- Are EDR/antivirus rules blocking browser automation, Docker, Node, Java, Maven, or Python?

### 2.2 Docker / container runtime

- Is Docker Desktop allowed inside the VDI?
- Is nested virtualization enabled on the underlying hypervisor?
- If Docker Desktop is not allowed, is a remote Docker context or CI runner available?
- Are required container images allowed directly from the internet or mirrored to an internal registry?
- Are Docker volumes allowed for Maven cache, npm cache, reports, and browser traces?

### 2.3 Network / VPN / proxy

- Is the application reachable only inside Horizon/VDI?
- Is an additional VPN needed inside the VDI?
- Does VPN need to start before Docker Desktop?
- What are the values for `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`?
- Is `host.docker.internal` reachable from containers?
- Are internal TLS certificates installed on the VDI and inside Docker images?
- Are target application and API URLs reachable from the VDI browser and from containers?

### 2.4 AI provider

- Is Codex CLI allowed?
- Can the VDI reach OpenAI/Codex authentication endpoints?
- Is device authentication allowed?
- If OpenAI/Codex is blocked, is Ollama or another approved local LLM runtime available?
- Are secrets allowed in local `.env`? The recommended answer is no: use local user auth, environment variables, or client vault.

### 2.5 Source and artifacts

- Where is the existing Playwright framework located?
- Where is the existing API framework located?
- Where should generated reports be stored?
- Is Git available for creating branches and reviewing AI patches?
- Is the repo allowed to store traces/videos/screenshots/HAR files?

---

## 3. Recommended folder layout

Use a short local path, not OneDrive/Desktop:

```powershell
C:\AI_QA\AdvancedAIAutomation
C:\AI_QA\client-web-playwright
C:\AI_QA\client-api-playwright
C:\AI_QA\client-api-restassured
```

Avoid:

```powershell
C:\Users\<user>\OneDrive\Desktop\...
```

Reason: npm, Maven, Playwright browser traces, Docker bind mounts, and RCA artifacts create many files and can be slowed or locked by OneDrive sync.

---

## 4. Install / run from zero

### 4.1 Extract the ZIP

```powershell
mkdir C:\AI_QA
cd C:\AI_QA
Expand-Archive .\AdvancedAIAutomation_GUI_First_Web_API_VDI_Enterprise_Build.zip -DestinationPath .\AdvancedAIAutomation -Force
cd .\AdvancedAIAutomation
```

### 4.2 Start GUI in VDI mode

Preferred on Windows VDI:

```powershell
.\START_AI_QA_GUI_VDI_WINDOWS.cmd
```

PowerShell alternative:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_AI_QA_GUI_VDI_WINDOWS.ps1
```

Open:

```text
http://127.0.0.1:8080
```

This starts only the local GUI. Do not run Docker, Maven, npm, or Codex manually unless client policy requires it.

---

## 5. First GUI actions inside VDI

### Step 1 — VDI / Horizon Readiness

Open tab:

```text
VDI / Horizon Readiness
```

Fill:

- **VDI type / desktop pool**: choose Horizon, Windows VM, Linux VM, physical, or unknown.
- **Docker runtime mode**:
  - `Local Docker Desktop inside VDI` if Docker Desktop is allowed inside the VM.
  - `Remote Docker context / CI runner` if nested virtualization is not allowed.
  - `No Docker - host tools only` if client permits local Java/Node/Maven but not Docker.
- **Application URL reachable from VDI**: web AUT URL.
- **API base URL reachable from VDI**: API base URL.
- **Remote Docker host/context**: only if Docker is remote.
- **Proxy URL**: corporate proxy, if required.
- **NO_PROXY**: internal domains that should bypass proxy.
- **Client VDI/VPN notes**: desktop pool, VPN, cert, proxy, registry, and app network notes.

Click:

1. **Save VDI Profile**
2. **Check VDI Readiness**
3. **Open VDI Report**
4. **Open Client Checklist**

Interpretation:

- `READY`: continue.
- `ACTION REQUIRED`: fix blockers first.
- Warnings are not always blockers, but review them with client IT.

### Step 2 — Dashboard

Click:

- **Verify prerequisites**
- **VDI readiness** if not done already
- **Refresh readiness**

### Step 3 — Enterprise Stack

If local Docker is approved:

1. Click **Check enterprise stack**.
2. Click **Pull images + start from GUI**.
3. Open Runtime Logs to confirm service startup.

If local Docker is not approved:

1. Configure remote Docker context on the VDI.
2. Save remote Docker info in VDI profile.
3. Use host/remote mode as approved by client.

### Step 4 — Codex / Ollama

Click:

- **Check Codex/Ollama session**.
- **Connect AI provider**.

If Codex login opens a browser and browser redirect is blocked, use device authentication as per client policy.

### Step 5 — Project Setup

Fill and save:

- Project name
- Application name
- Feature name
- Input source
- Website/application URL
- Execution browser
- Test id attribute
- AI provider
- Ollama model if using Ollama
- MCP enabled if using Playwright MCP
- Skip npm build during static review only when dependency install is restricted

Click:

- **Save project config**
- **Load/check website**

### Step 6 — Existing Web Playwright Framework Control

Use when the framework already exists.

1. Paste existing framework root path.
2. Click **Understand Framework**.
3. Click **Deep Index + RAG**.
4. Click **Open Intelligence**.
5. Execute headless/headed.
6. If failed: Analyze RCA → Propose Fix → Apply Patch if safe → Re-run Failed Only.

### Step 7 — API Automation

Use for Playwright API TS/JS or Rest Assured Java.

1. Select API flavor.
2. Paste existing API framework path, or generate a new API framework.
3. Keep **Run API tests inside Docker runtime** checked if host tools are restricted.
4. Click **Check API Docker Prereqs**.
5. Click **Pull API Docker Images**.
6. Optional: **Start API Mock/Contract Tools**.
7. Execute API framework.
8. If failed: Analyze API RCA → Propose API Fix → Apply API Patch if safe → Re-run API Failed/Targeted.

---

## 6. VDI/Horizon runtime modes

### Mode A — Local Docker Desktop inside VDI

Use this when client IT enables nested virtualization and Docker Desktop is approved.

Host prerequisites:

- Docker Desktop running.
- Docker daemon reachable by `docker info`.
- Corporate proxy/certificates configured.
- Docker image pull allowed or internal registry configured.

Recommended for:

- Playwright Web browser execution.
- Playwright API execution.
- Rest Assured Java Maven execution.
- WireMock/MockServer contract/mocking.
- Prometheus/Grafana observability.

### Mode B — Remote Docker / CI runner

Use this when Docker Desktop cannot run inside Horizon/VDI.

Client IT must provide one of:

- Remote Linux Docker host.
- Secure Docker context.
- GitHub Actions/Azure DevOps/GitLab runner.
- Internal execution server.

Recommended when:

- Nested virtualization is disabled.
- Docker Desktop is blocked.
- VDI has limited CPU/RAM.
- Browser automation must run in a controlled execution worker.

### Mode C — Host tools only

Use this only when Docker is not allowed but Java/Node/Maven are installed locally.

Host prerequisites:

- Python 3.11/3.12.
- Node 20/22.
- Java 17/21.
- Maven 3.9+.
- Git.
- Codex/Ollama access.

Limitations:

- More client-specific setup.
- Browser dependencies may be harder to manage.
- Less repeatable than Docker.

---

## 7. Common VDI issues and fixes

### Docker Desktop does not start

Likely causes:

- Nested virtualization disabled.
- Hypervisor not launched.
- Docker Desktop not licensed/approved for client VDI.
- EDR/AV blocks virtualization services.

Actions:

- Run **VDI Readiness**.
- Ask client IT to enable nested virtualization or provide remote Docker.
- Use remote Docker/CI mode if local Docker is not allowed.

### Application opens in VDI browser but not from Docker container

Likely causes:

- Container DNS/proxy missing.
- Internal certificate not trusted in container.
- VPN traffic not routed to Docker network.
- `NO_PROXY` missing internal domains.

Actions:

- Add proxy and NO_PROXY in `.env` and Docker Desktop settings.
- Use `host.docker.internal` when app runs on VDI host.
- Mirror internal certificates into custom Docker images if needed.
- Use host mode only for diagnosis if client allows.

### Codex login fails

Likely causes:

- Browser SSO redirect blocked.
- Device auth blocked.
- OpenAI/Codex endpoint blocked.
- TLS inspection/cert issue.

Actions:

- Use Codex / Ollama tab.
- Try device auth where policy allows.
- Ask client IT to approve provider endpoints.
- Use Ollama/local provider if cloud AI is blocked.

### API tests fail with 401/403

Treat as auth/session/environment, not script issue, unless evidence proves the test client is wrong.

Actions:

- Validate token/session fixture.
- Validate role/permission.
- Validate VPN/environment.
- Do not self-heal by weakening assertions or expected status codes.

### RCA says product/env issue

This is expected behavior. The healer must not patch tests when the evidence points to real product bug, environment issue, API outage, schema drift, or authorization failure.

---

## 8. Security notes

- Do not store passwords, tokens, client certificates, or API keys in committed files.
- Do not paste secrets into RCA prompts or reports.
- Review generated patches before committing.
- Keep self-healing failed-only.
- Do not allow AI to skip tests, weaken assertions, or force-click disabled controls.
- Use a feature branch for all self-healed patches.

---

## 9. Client explanation summary

Use this simple explanation:

> The tool runs as a GUI-first QA automation control plane inside the client VDI. The user starts one local GUI, then all Docker, Codex/Ollama, web/API framework execution, RCA, self-healing, and reports are controlled from the browser. In VDI mode, the tool first checks whether Docker, proxy, VPN, application URLs, API URLs, Java/Maven/Node, and Codex are reachable. It never blindly patches code: failures are classified, evidence is collected, only failed tests are repaired, risky assertion/API/product/environment issues are blocked for human review, and failed tests only are rerun after healing.
