# GUI Tab, Button, and Input Reference

This document explains each GUI tab, input box, and button in plain English so the solution can be explained to QA engineers, architects, client IT, and managers.

## Dashboard

Purpose: entry point and overall readiness.

Buttons:

- **Verify prerequisites**: checks Python, Node/npm/npx, Docker summary, Codex/Ollama availability.
- **VDI readiness**: opens VDI/Horizon tab and runs the VDI readiness check.
- **Start Docker stack**: starts the mandatory enterprise Docker stack from GUI.
- **Connect Codex/Ollama**: prepares selected AI provider session.
- **Refresh readiness**: refreshes Docker + AI readiness gate.
- **Existing Framework Control**: jumps to existing Playwright framework execution/control.
- **Full Pipeline Setup**: jumps to project setup for requirements-to-tests flow.
- **Refresh HTML report**: regenerates/refreshes enterprise report links.

## VDI / Horizon Readiness

Purpose: validate client-hosted VDI/Horizon VM environment before running Docker, Codex, Playwright, Rest Assured, RCA, or self-healing.

Inputs:

- **VDI type / desktop pool**: tells the system whether it is Horizon, Windows VM, Linux VM, physical machine, or unknown.
- **Docker runtime mode**: choose local Docker, remote Docker/CI, or host-tools-only.
- **Application URL reachable from VDI**: the web application URL as reachable inside the VDI.
- **API base URL reachable from VDI**: the API base URL as reachable inside the VDI.
- **Remote Docker host/context**: remote Docker connection info if Docker cannot run locally.
- **Proxy URL**: client proxy URL if needed.
- **NO_PROXY list**: domains/hosts that should bypass proxy.
- **Client VDI/VPN notes**: human-readable notes for desktop pool, VPN, certs, internal registries, app access, and client restrictions.

Buttons:

- **Save VDI Profile**: saves these VDI settings under `.qa-cache/vdi/vdi-runtime-profile.json`.
- **Check VDI Readiness**: checks host OS, Docker, tools, app/API reachability, proxy hints, VDI hints, and generates a report.
- **Load Saved Profile**: loads previously saved VDI settings into the GUI.
- **Open VDI Report**: opens the generated HTML readiness report.
- **Open Client Checklist**: opens a client IT preflight checklist.

## Project Setup

Purpose: stores the application and AI context used by generation, execution, RCA, and self-healing.

Inputs:

- **Project name**: friendly project/report name.
- **Application name**: application under test.
- **Feature name**: default feature name used for generated testcase/script names.
- **Input source**: source type such as Jira, SRS, PDF, DOCX, text, existing cases.
- **Website/application URL to launch**: `BASE_URL` for web tests.
- **Execution browser**: Playwright browser/project such as Chromium.
- **Test id attribute**: stable attribute to prefer for locators, for example `data-testid` or `data-test`.
- **AI provider**: Codex, Ollama, or deterministic fallback.
- **Ollama model**: model name when Ollama is selected.
- **Use Playwright MCP readiness/context**: includes MCP readiness/context when available.
- **Skip npm build during static review**: avoids npm build during review when dependency install is blocked.

Buttons:

- **Save project config**: writes `.project-config.json`.
- **Load project config**: reloads saved config.
- **Load/check website**: checks whether the application URL is reachable.
- **Start mandatory Docker from GUI**: starts enterprise Docker services.
- **Connect selected AI provider**: initiates Codex/Ollama readiness.
- **Check Codex/Ollama**: shows current AI provider status.
- **Check Playwright MCP**: checks MCP config and npx availability.
- **Check Docker readiness**: checks Docker stack status.
- **Pull images + start mandatory stack**: pulls and starts mandatory Docker services.
- **Pull/refresh mandatory images**: pulls Docker images only.
- **Stop Docker stack**: stops Docker services.

## Requirement Input

Purpose: provides requirements for testcase generation.

Inputs:

- **Upload PDF/DOCX/JSON/TXT/SRS**: uploads requirement documents or testcase source.
- **Optional website page source / saved DOM HTML/TXT**: adds UI context for better locators.
- **Paste Jira/SRS/manual test steps**: manual text input.

Buttons:

- **Load generic template**: loads a generic sample requirement template.
- **Load Acima sample**: loads the bundled sample.
- **Generate functional testcases**: creates functional testcase JSON from the source.

## Functional Testcases

Purpose: mandatory review gate before script generation.

Buttons:

- **Generate / regenerate functional testcases**: creates or refreshes testcase JSON.
- **Approve functional testcases and unlock Playwright**: marks testcases approved.
- **Next: Generate Playwright**: moves to script generation tab.
- **View runtime logs**: opens runtime progress logs.

## Generated Playwright

Purpose: generate and execute reusable Playwright Web scripts from approved testcases.

Inputs:

- **Execution mode**: sequential, parallel, or similar execution mode.
- **Distributed shards**: number of shards for distributed execution.
- **Playwright MCP readiness/context enabled**: use MCP context if available.
- **Prefer headed demo mode**: runs with visible browser.

Buttons:

- **Generate Reusable Playwright**: creates specs/pages/pageObjects with reuse rules.
- **Static Review**: validates generated code structure and quality.
- **Execute Generated Test - Headless**: runs generated tests without visible browser.
- **Execute Generated Test - Headed**: runs generated tests with visible browser.
- **Open/refresh HTML report**: opens or refreshes reports.

## Existing Framework Control

Purpose: run, understand, RCA, and heal an already-developed Playwright framework without regenerating tests.

Inputs:

- **Existing framework root folder**: path to existing Playwright framework.
- **Optional spec targets / patterns**: specific specs or patterns to run.
- **Optional custom test command**: custom npm/npx command.
- **Optional RAG / framework search query**: search indexed framework context.
- **Existing framework execution mode**: sequential/parallel mode.
- **Existing framework shards**: shard count.

Buttons:

- **Understand Framework**: scans architecture, package, config, specs, pages, pageObjects, fixtures, utilities.
- **Deep Index + RAG**: chunks/indexes framework for context-aware RCA/healing.
- **Open Intelligence**: opens framework intelligence report.
- **Search RAG Context**: retrieves relevant framework chunks.
- **Execute Existing - Headless**: runs existing framework headless.
- **Execute Existing - Headed**: runs existing framework with visible browser.
- **Show Failed Inventory**: shows failed-only scope.
- **Install Robust TS Harness**: adds optional SmartLocator/TestTelemetry helper folder.
- **Selector Health Report**: generates selector stability and healing trend report.
- **Analyze Existing RCA**: runs multi-signal RCA on failed tests.
- **Propose Existing Fix**: generates a guarded patch proposal without changing files.
- **Apply Existing Patch**: applies safe patch only if confidence and policy gates pass.
- **Re-run Existing Failed Only - Headed**: reruns only failed tests with visible browser.
- **Re-run Existing Failed Only - Headless**: reruns only failed tests headless.

## API Automation

Purpose: generate, execute, analyze, and heal Playwright API TS/JS or Rest Assured Java API frameworks.

Inputs:

- **API flavor**: Playwright API, Rest Assured Java, or auto-detect.
- **Existing API framework root folder**: path to API framework.
- **Optional API spec/test targets**: specific tests to run.
- **Optional custom API test command**: custom npm/maven command.
- **Run API tests inside Docker runtime**: recommended for restricted VDI laptops and Rest Assured Java.
- **Optional API RAG search query**: search indexed API context.

Buttons:

- **Check API Docker Prereqs**: checks API Docker runtime, Java/Maven/Node fallback, images, proxy guidance.
- **Pull API Docker Images**: pulls Playwright, Maven/Temurin, WireMock, MockServer, Newman images.
- **Start API Mock/Contract Tools**: starts WireMock/MockServer services.
- **Generate API Framework**: generates Playwright API or Rest Assured Java framework.
- **Analyze / Index Existing API Framework**: indexes existing API framework.
- **Search API RAG**: searches API framework chunks.
- **Execute API Framework**: runs API tests locally or inside Docker.
- **Show API Failed Inventory**: displays failed API tests.
- **Analyze API RCA**: classifies API failures: auth, endpoint, schema, payload, server/env, DB/VPN, assertion.
- **Propose API Fix**: creates safe API patch proposal.
- **Apply API Patch**: applies safe patch only if policy allows.
- **Re-run API Failed/Targeted**: reruns failed or targeted API tests.

## Codex / Ollama

Purpose: manage AI provider readiness.

Buttons:

- **Check Codex/Ollama session**: verifies Codex CLI and Ollama availability.
- **Connect AI provider**: starts login/device auth or prepares Ollama.
- **Ensure Ollama Docker model**: pulls configured Ollama model.
- **Refresh readiness gate**: refreshes enterprise readiness.

## Playwright MCP

Purpose: validate MCP availability for Playwright context.

Buttons:

- **Check Playwright MCP**: checks MCP config and command.
- **Execute headless with MCP context**: executes generated Playwright with MCP context.
- **Execute headed with MCP context**: executes generated Playwright headed with MCP context.

## JIRA

Purpose: fetch Jira Epic/Story/Task/Bug source and generate testcases.

Inputs:

- **Jira URL**: client Jira base URL.
- **Jira email / username**: Jira user.
- **Jira API token**: Jira token.
- **Jira Epic key**: fetches child work items.
- **Jira single issue/story key**: fetches one issue.
- **Parallel workers**: controls parallel testcase generation workers.

Buttons:

- **Check Jira connection**: verifies Jira credentials and URL.
- **Epic: Fetch Children + Generate Testcases**: fetches epic children and generates testcases.
- **Story/Task/Bug: Generate Testcase**: generates testcase for one item.
- **Show active source context**: shows source-scoped context.
- **Generate parallel testcase files**: generates multiple testcase files concurrently.

## App Intelligence

Purpose: profile application behavior before generation/healing.

Buttons:

- **Profile application/website**: crawls/profiles app URL for dynamic web hints.
- **Check Playwright MCP**: validates MCP.
- **Load failure-learning matrix**: shows stored failure pattern learning.

## Enterprise Stack

Purpose: manage Docker services and distributed execution.

Inputs:

- **Shards**: number of distributed execution shards.

Buttons:

- **Check enterprise stack**: checks Docker services.
- **Pull images + start from GUI**: starts mandatory services.
- **Pull/refresh images only**: pulls images.
- **Stop stack**: stops stack.
- **Execute distributed/headless**: runs distributed headless.
- **Execute distributed/headed**: runs distributed headed.

## RCA & Self-Healing

Purpose: failed-only RCA and guarded self-healing for generated Playwright tests.

Buttons:

- **Analyze Root Cause**: classifies failed generated tests.
- **Propose Self-Healing Fix**: generates patch proposal.
- **Apply Self-Healing Patch**: applies safe patch.
- **Re-run Failed Only - Headed**: reruns only failed tests headed.
- **Re-run Failed Only - Headless**: reruns only failed tests headless.
- **Show Failed Inventory**: shows failed-only scope.
- **Refresh HTML Report**: refreshes report.

## Agents & Phases

Purpose: show implementation coverage across pipeline agents.

Buttons:

- **Check all agents and phases**: reports phase coverage.
- **Show agent matrix in report preview**: displays coverage matrix.

## Runtime Logs

Purpose: live progress, runtime events, metrics, Grafana/Prometheus links.

Buttons:

- **Start live logs**: starts polling runtime logs.
- **Refresh once**: loads logs once.
- **Open local live console**: opens local HTML live console.
- **Open Grafana**: opens Grafana dashboard.
- **Open Prometheus targets**: opens Prometheus target status.
- **Open pipeline metrics**: opens `/metrics`.
- **Grafana help**: shows Grafana URL/login/reset help.
- **Reset runtime logs**: clears local runtime events.

## Reports

Purpose: view report previews and generated artifacts.

Buttons:

- **Refresh enterprise HTML report**: rebuilds report links.
- **Open enterprise HTML report**: opens enterprise report.
- **Open native Playwright report**: opens Playwright native report.
- **Summary/Testcases/Spec/Page/PageObjects/Reuse/Page-source/Static review/Execution/RCA/Self-Healing/AI messages/Agents**: switches preview content.
- **Copy current output**: copies visible output JSON/text.
