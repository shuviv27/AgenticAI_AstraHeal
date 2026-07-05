from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.vdi_agent_control import list_agents

CENTRAL_REPORT_DIR = REPORTS_DIR / "existing-framework"
HEAVY_CACHE_DIR = QA_CACHE_DIR / "ai-heavy-lifting"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(text or "framework")).strip("-._")
    return cleaned[:80] or "framework"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _framework_history_dir(framework_path: str) -> Path:
    return Path(framework_path).expanduser().resolve() / ".aiqa-history"


def _framework_reports_dir(framework_path: str) -> Path:
    return _framework_history_dir(framework_path) / "reports"


def _parse_list(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n;]+", text or "") if x.strip()]


def _provider_role_matrix(primary_provider: str = "codex", reasoning_provider: str = "openai", fallback_provider: str = "deepseek") -> dict[str, Any]:
    primary = (primary_provider or "codex").strip().lower()
    reasoning = (reasoning_provider or "openai").strip().lower()
    fallback = (fallback_provider or "deepseek").strip().lower()
    return {
        "primary_code_heavy_lifting": primary,
        "reasoning_provider": reasoning,
        "fallback_reasoning_provider": fallback,
        "recommended_runtime_roles": {
            "codex": [
                "framework-aware code edits",
                "new spec/page/pageObject creation",
                "locator and method reuse refactor",
                "self-healing patch application with backup and rollback",
            ],
            "openai": [
                "RCA reasoning",
                "generation planning",
                "test design critique",
                "fallback proposal when Codex is unavailable",
            ],
            "deepseek": [
                "trial/alternate reasoning provider",
                "RCA summarization",
                "candidate fix proposal when budget or routing requires it",
            ],
            "perplexity": [
                "web-grounded RCA and fix-plan guidance",
                "current documentation/search-backed recommendations",
                "proposal-only support while Codex/human approval handles direct file patching",
            ],
            "ollama": [
                "local/offline fallback for non-sensitive summarization",
                "deterministic helper prompt expansion where local GPU/CPU is available",
            ],
            "playwright_mcp": [
                "browser evidence collection",
                "DOM/accessibility snapshot style element diagnosis",
                "actionability checks on the same VM where AUT is reachable",
            ],
        },
        "important_rule": "Only the central source-of-truth workspace should be patched. Worker VMs should collect browser/MCP evidence and execute tests, not permanently change framework source.",
    }


def _resolve_workers(agent_ids: str, execution_target_mode: str, include_master_worker: bool) -> list[dict[str, Any]]:
    requested = {x.lower() for x in _parse_list(agent_ids)}
    agents = list_agents().get("agents") or []
    online = [a for a in agents if str(a.get("status") or "").lower() == "online"]
    if requested:
        def matches(agent: dict[str, Any]) -> bool:
            values = {
                str(agent.get("agent_id") or "").lower(),
                str(agent.get("agent_name") or "").lower(),
                str(agent.get("hostname") or "").lower(),
                str(agent.get("ip_address") or "").lower(),
                str(agent.get("host") or "").lower(),
            }
            return bool(values & requested)
        online = [a for a in online if matches(a)]
    mode = (execution_target_mode or "central_and_workers").strip().lower()
    workers: list[dict[str, Any]] = []
    if mode in {"central_only", "central_and_workers", "hybrid", "all"} and include_master_worker:
        workers.append({
            "agent_id": "__MASTER_VM__",
            "agent_name": "Central-VM-Worker",
            "ip_address": "127.0.0.1",
            "role": "central_control_plane_and_worker",
            "ai_heavy_lifting_role": "Full local execution + optional MCP evidence + central RCA/fix",
        })
    if mode in {"workers_only", "central_and_workers", "hybrid", "all"}:
        for a in online:
            workers.append({
                "agent_id": a.get("agent_id"),
                "agent_name": a.get("agent_name") or a.get("hostname") or a.get("ip_address"),
                "ip_address": a.get("ip_address") or a.get("host"),
                "role": "worker_browser_execution",
                "ai_heavy_lifting_role": "Playwright/MCP browser evidence + test execution; no permanent source patching",
            })
    return workers


def _build_phase_plan(worker_workspace_mode: str, dom_crawl_mode: str, execution_target_mode: str, central_shared_framework_path: str) -> list[dict[str, Any]]:
    worker_source = "central_shared_framework_path" if worker_workspace_mode == "central_shared_workspace" else worker_workspace_mode
    return [
        {
            "phase": "framework_understanding",
            "runs_on": "central_vm",
            "engine": "RAG + deterministic framework scanner + Codex optional review",
            "output": "framework architecture, dependency graph, locator/method inventory, reusable component map",
            "reason": "Framework source of truth is centralized; this avoids each worker learning different copies.",
        },
        {
            "phase": "aut_understanding_and_webscraping",
            "runs_on": "central_vm_first_then_worker_if_aut_only_reachable_there",
            "engine": "Playwright crawl + page-source analyzer + optional Playwright MCP evidence",
            "output": "route map, page object candidates, business flow hints, DOM/accessibility evidence",
            "dom_crawl_mode": dom_crawl_mode,
        },
        {
            "phase": "new_test_generation",
            "runs_on": "central_vm",
            "engine": "Codex CLI primary + RAG context + reuse-law planner",
            "output": "spec.ts plus page methods/pageObjects/fixtures/testData updated only where required",
            "reuse_law": "spec.ts must call page methods; page methods must call existing locators/methods where available; new locators/methods are added to the most suitable existing files.",
        },
        {
            "phase": "distributed_execution",
            "runs_on": execution_target_mode,
            "engine": "central queue + central worker and/or remote worker agents",
            "workspace_source": worker_source,
            "central_shared_framework_path": central_shared_framework_path,
            "output": "per-worker artifacts returned to central report/history",
        },
        {
            "phase": "parallel_rca",
            "runs_on": "central_vm",
            "engine": "RAG + failure logs + worker MCP/DOM artifacts + provider reasoning",
            "output": "RCA events begin as soon as a test becomes a stable failure on any worker",
        },
        {
            "phase": "self_healing_and_fix_apply",
            "runs_on": "central_vm_source_of_truth",
            "engine": "Codex CLI default patcher with backup, approval policy and rollback",
            "output": "changed file list, backup folder, rollback metadata, final rerun queue",
            "guardrail": "Patch only central framework source, never node_modules/reports/generated artifacts, and never hide failures using skip/only/fixme.",
        },
    ]


def _render_html(plan: dict[str, Any]) -> str:
    body = json.dumps(plan, indent=2, ensure_ascii=False)
    phases = plan.get("phase_plan") or []
    rows = "\n".join(
        f"<tr><td>{p.get('phase')}</td><td>{p.get('runs_on')}</td><td>{p.get('engine')}</td><td>{p.get('output')}</td></tr>"
        for p in phases
    )
    workers = "\n".join(
        f"<li><b>{w.get('agent_name') or w.get('agent_id')}</b> ({w.get('ip_address') or 'n/a'}) — {w.get('ai_heavy_lifting_role')}</li>"
        for w in plan.get("workers") or []
    ) or "<li>No remote workers online/selected. Central-only execution remains valid.</li>"
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"/><title>AstraHeal AI Heavy Lifting Plan</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:24px;background:#f8fafc;color:#111827}}
.card{{background:#fff;border:1px solid #dbe3ef;border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 1px 3px #0001}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top}}th{{background:#e5e7eb}}pre{{white-space:pre-wrap;background:#111827;color:#d1fae5;padding:16px;border-radius:10px;overflow:auto}}
.badge{{display:inline-block;background:#dbeafe;color:#1e40af;border-radius:999px;padding:4px 10px;font-weight:700}}
</style></head><body>
<h1>AstraHeal AI Heavy Lifting Plan</h1>
<div class=\"card\"><span class=\"badge\">Central-source, worker-execution safe model</span><p>{plan.get('message')}</p></div>
<div class=\"card\"><h2>Provider Balance</h2><pre>{json.dumps(plan.get('provider_roles'), indent=2, ensure_ascii=False)}</pre></div>
<div class=\"card\"><h2>Workers / Execution Roles</h2><ul>{workers}</ul></div>
<div class=\"card\"><h2>Agentic Phase Plan</h2><table><tr><th>Phase</th><th>Runs on</th><th>Engine</th><th>Output</th></tr>{rows}</table></div>
<div class=\"card\"><h2>Full JSON</h2><pre>{body}</pre></div>
</body></html>"""


def build_ai_heavy_lifting_plan(
    framework_path: str,
    base_url: str = "",
    primary_provider: str = "codex",
    reasoning_provider: str = "openai",
    fallback_provider: str = "deepseek",
    execution_target_mode: str = "central_and_workers",
    include_master_worker: bool = True,
    distributed_agent_ids: str = "",
    worker_workspace_mode: str = "central_shared_workspace",
    central_shared_framework_path: str = "",
    dom_crawl_mode: str = "worker_mcp_when_aut_access_requires_worker",
    mcp_evidence_mode: str = "collect_on_execution_worker_send_to_central",
    ai_patch_location: str = "central_only",
) -> dict[str, Any]:
    root = Path(framework_path or ".").expanduser().resolve()
    workers = _resolve_workers(distributed_agent_ids, execution_target_mode, include_master_worker)
    provider_roles = _provider_role_matrix(primary_provider, reasoning_provider, fallback_provider)
    phase_plan = _build_phase_plan(worker_workspace_mode, dom_crawl_mode, execution_target_mode, central_shared_framework_path)
    plan = {
        "ok": bool(framework_path),
        "stage": "ai_heavy_lifting_plan_created",
        "generated_at": _now(),
        "framework_path": str(root),
        "base_url": base_url,
        "execution_target_mode": execution_target_mode,
        "worker_workspace_mode": worker_workspace_mode,
        "central_shared_framework_path": central_shared_framework_path,
        "dom_crawl_mode": dom_crawl_mode,
        "mcp_evidence_mode": mcp_evidence_mode,
        "ai_patch_location": ai_patch_location,
        "workers": workers,
        "provider_roles": provider_roles,
        "phase_plan": phase_plan,
        "message": (
            "Heavy lifting is balanced by keeping framework understanding, code generation, RCA, self-healing and source patching on the Central VM, "
            "while worker VMs perform browser execution and MCP/DOM evidence collection from the environment where AUT is reachable."
        ),
        "best_practice": [
            "Use Codex CLI as the primary code heavy-lifting provider on Central VM.",
            "Use OpenAI/DeepSeek/Perplexity as optional reasoning/fallback providers, not as uncontrolled file patchers.",
            "Run Playwright/MCP evidence capture on the same VM/worker where the AUT can be opened.",
            "Patch only the central source-of-truth framework; workers should not permanently modify the framework.",
            "Store all RCA/self-healing/history reports in the central framework .aiqa-history folder and central AI cache.",
        ],
    }
    central_json = CENTRAL_REPORT_DIR / "ai-heavy-lifting-plan.json"
    central_html = CENTRAL_REPORT_DIR / "ai-heavy-lifting-plan.html"
    _write_json(central_json, plan)
    central_html.parent.mkdir(parents=True, exist_ok=True)
    central_html.write_text(_render_html(plan), encoding="utf-8")
    if framework_path:
        local = _framework_reports_dir(str(root))
        _write_json(local / "ai-heavy-lifting-plan.json", plan)
        (local / "ai-heavy-lifting-plan.html").write_text(_render_html(plan), encoding="utf-8")
        plan["framework_html_report"] = str(local / "ai-heavy-lifting-plan.html")
        plan["framework_json_report"] = str(local / "ai-heavy-lifting-plan.json")
    log_event("ai_heavy_lifting", "AI heavy lifting plan generated", status="ok", progress=100, details={"framework_path": str(root), "execution_target_mode": execution_target_mode})
    return plan


def get_ai_heavy_lifting_report_path(framework_path: str) -> Path:
    if framework_path:
        return _framework_reports_dir(framework_path) / "ai-heavy-lifting-plan.html"
    return CENTRAL_REPORT_DIR / "ai-heavy-lifting-plan.html"
