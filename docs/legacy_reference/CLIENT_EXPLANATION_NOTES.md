# Client Explanation Notes

Use these notes when explaining the solution to client stakeholders.

## One-line explanation

The solution is a GUI-first AI QA automation control plane that runs inside the client VDI and controls requirement ingestion, Playwright web automation, Playwright API automation, Rest Assured Java API automation, Docker runtimes, Codex/Ollama AI, RCA, self-healing, failed-only reruns, and reports from `http://127.0.0.1:8080`.

## Why VDI readiness exists

Client VDIs often restrict Docker, VPN routing, proxies, certificates, browser automation, Maven, npm, and cloud AI login. The VDI readiness tab checks those blockers before execution so failures are not incorrectly treated as script defects.

## Why Docker is preferred

Docker gives repeatable runtime environments for Playwright browsers, Rest Assured/Maven, API mock tools, observability, and dependency isolation. If Docker Desktop cannot run inside Horizon because nested virtualization is blocked, the same GUI can be used with remote Docker/CI or host-tool mode.

## Why RAG/indexing is used

When an existing framework is large, reading every file for every failure is expensive and inaccurate. The framework is indexed and chunked so RCA/self-healing retrieves only relevant specs, pages, pageObjects, utilities, fixtures, API clients, test data, and configuration.

## Why self-healing is guarded

The system does not blindly change code until tests pass. It:

1. Runs only failed-test RCA.
2. Collects evidence.
3. Classifies the failure.
4. Decides whether it is safe to heal.
5. Patches only allowed framework layers.
6. Blocks risky assertion/product/API/env changes.
7. Reruns only failed tests.
8. Merges retry results into original report.

## What to say about chain-of-thought

The AI follows a staged diagnostic approach internally: understand context, collect evidence, classify, decide, patch safely, validate, and rerun failed-only. The system stores auditable evidence summaries and decisions, not hidden private chain-of-thought.

## What client IT must know

Client IT should confirm:

- Docker/nested virtualization/remote Docker policy.
- Proxy/VPN/DNS/certificate setup.
- Application/API reachability from VDI and containers.
- Codex/Ollama/LLM provider policy.
- Approved workspace and artifact storage locations.
- Git and source-control approval workflow.
