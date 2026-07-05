# No-Docker Host Runtime Client-Server Runbook

## Goal

Run the full AI QA solution without Docker while preserving GUI, RCA, self-healing, RAG, reports, API/Web automation and VM/VDI communication.

## Simple architecture

VM:
- GUI
- RAG
- reports
- runtime logs
- job queue
- RCA/self-healing decision engine

VDI:
- small runner agent
- browser execution
- Codex patching in user workspace
- failed-only rerun

## Why this helps

This avoids Docker Desktop, nested virtualization, WSL2, Docker Business/registry restrictions and repeated Docker troubleshooting on client VDI machines.

## Minimum approved tools

VM:
- Python
- Git
- Node.js/npm/npx
- Java/Maven if Rest Assured runs on VM
- Codex/Ollama if central AI is approved

VDI:
- Browser access to AUT
- Node/npm/npx if Playwright runs on VDI
- Java/Maven if Rest Assured runs on VDI
- Git if user branch is cloned on VDI
- Codex CLI if user-specific patching happens on VDI

## Execution flow

1. User opens VM GUI from VDI.
2. User selects selected VDI Agent as execution target.
3. VM sends job to agent.
4. VDI agent runs test locally against AUT.
5. VDI uploads trace, screenshot, logs and reports to VM.
6. VM performs RCA and produces plain-English report.
7. VDI runs Codex patch if allowed by policy.
8. VDI reruns failed-only test.
9. VM merges final report.

## What to explain to client

The same system can run with or without Docker. In No-Docker mode, the required tools are installed directly on approved VMs/VDIs. The GUI and lifecycle remain the same. Docker is optional, not mandatory.
