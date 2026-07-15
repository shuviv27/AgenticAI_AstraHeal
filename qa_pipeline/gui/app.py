from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from qa_pipeline.agents.phase1_foundation.doctor import run_doctor
from qa_pipeline.agents.phase2_source_intake_rag.ai_testcase_planner import maybe_enhance_testcases_with_ai
from qa_pipeline.agents.phase2_source_intake_rag.ingest import ingest_source
from qa_pipeline.agents.phase3_reuse_aware_codegen.codex_prompt import build_codex_prompt
from qa_pipeline.agents.phase3_reuse_aware_codegen.reuse_generator import ReuseAwarePlaywrightGenerator
from qa_pipeline.agents.phase3_reuse_aware_codegen.dynamic_crawler import crawl_dynamic_page
from qa_pipeline.agents.phase3_reuse_aware_codegen.page_source_analyzer import analyze_page_source, save_uploaded_page_source
from qa_pipeline.agents.phase3_reuse_aware_codegen.app_intelligence_profiler import profile_application
from qa_pipeline.agents.phase4_review_execution.executor import execute_feature, execute_feature_distributed, execute_feature_sequential, execute_failed_only_after_healing, read_failed_test_inventory
from qa_pipeline.agents.phase5_failure_healing.root_cause_agent import analyze_latest_failure, analyze_failed_scripts_one_by_one
from qa_pipeline.agents.phase5_failure_healing.self_healing_agent import run_self_healing
from qa_pipeline.agents.phase4_review_execution.reviewer import run_review
from qa_pipeline.agents.phase6_reporting_governance.reporter import generate_summary, generate_enterprise_html_report
from qa_pipeline.agents.existing_framework_control.controller import (
    analyze_existing_framework,
    execute_existing_framework,
    preview_existing_framework_tests,
    preview_existing_framework_tests_for_selection,
    execute_selected_existing_framework_tests,
    analyze_existing_failure,
    self_heal_existing_framework,
    create_runtime_patch_approval_request,
    rollback_last_existing_fix,
    execute_existing_failed_only,
    read_existing_failed_inventory,
    generate_existing_selector_health_report,
    install_existing_framework_robust_harness,
    read_existing_framework_intelligence_v2,
    search_existing_framework_rag,
    existing_framework_artifact_locations,
)
from qa_pipeline.agents.existing_framework_control.mcp_locator_rca import build_mcp_assisted_locator_rca
from qa_pipeline.agents.api_framework_control.controller import (
    generate_api_framework,
    analyze_api_framework,
    execute_api_framework,
    analyze_api_failure,
    self_heal_api_framework,
    read_api_failed_inventory,
    search_api_framework_rag,
)
from qa_pipeline.agents.phase6_reporting_governance.failure_learning_agent import record_failure, summarize_failure_learning
from qa_pipeline.core.app_probe import check_application_url
from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.docker_stack import docker_start, docker_status, docker_stop, docker_pull, docker_logs, ollama_ensure_model
from qa_pipeline.core.api_docker_runtime import api_docker_runtime_status, api_docker_pull_images, api_docker_start_tools
from qa_pipeline.core.vdi_readiness import check_vdi_readiness, save_vdi_profile, read_vdi_profile
from qa_pipeline.core.vdi_agent_control import (create_agent_token, list_agents as list_vdi_runner_agents, build_agent_package, register_agent, heartbeat_agent, poll_agent_job, create_agent_job, complete_agent_job)
from qa_pipeline.core.runtime_mode import read_runtime_profile, save_runtime_profile, local_machine_readiness
from qa_pipeline.core.host_runtime import host_runtime_readiness, start_host_services, stop_host_services, host_runtime_status, install_plan as host_install_plan
from qa_pipeline.core.io import read_json
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, QA_CACHE_DIR, REPO_ROOT, feature_testcase_path, ensure_dirs
from qa_pipeline.core.project_config import load_project_config, save_project_config
from qa_pipeline.core.url_guard import normalize_base_url, sanitize_testcase_urls
from qa_pipeline.core.agent_registry import get_agent_coverage_report
from qa_pipeline.core.text import pascal_case
from qa_pipeline.core.active_context import write_active_context, read_active_context, active_features_for_request, matches_active_context, safe_feature as context_safe_feature
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.llm.openai_compatible import OpenAICompatibleProvider
from qa_pipeline.llm.agentic_cli import AgenticCliProvider
from qa_pipeline.mcp.playwright_mcp import mcp_status, write_playwright_mcp_configs
from qa_pipeline.parsers.source_parser import normalize_source_to_json
from qa_pipeline.rag.framework_inventory import scan_framework
from qa_pipeline.integrations.jira_client import JiraCredentials, JiraClient, epic_to_source_text, issue_to_testcase_text, jira_status
from qa_pipeline.integrations.observability import enterprise_stack_status, langsmith_status
from qa_pipeline.agents.phase2_source_intake_rag.parallel_testcase_generation import generate_parallel
from qa_pipeline.core.runtime_logger import log_event, read_events, current_status, write_runtime_summary, prometheus_metrics, reset_runtime_logs, write_runtime_live_html
from qa_pipeline.core.action_history import record_action, read_action_history, write_action_memory_summary
from qa_pipeline.core.human_intervention import create_human_intervention_request, save_human_intervention_update, read_human_intervention_memory
from qa_pipeline.core.ai_heavy_lifting import build_ai_heavy_lifting_plan, get_ai_heavy_lifting_report_path
from qa_pipeline.mcp.mcp_readiness_preflight import run_mcp_readiness_preflight, fix_mcp_preflight_build_errors_with_ai
from qa_pipeline.mcp.framework_full_control_fix import ai_full_control_fix_framework_issues

app = FastAPI(title="AstraHeal AI - Multi-Agent Playwright Automation Studio")


@app.middleware("http")
async def astraheal_api_alias_middleware(request: Request, call_next):
    """Backward-compatible product URL alias.

    Existing backend routes remain under /api/module2/... to avoid breaking older
    automations, docs, and scripts. The branded GUI uses /api/astraheal/...; this
    middleware rewrites that branded path internally to the existing route table.
    """
    path = request.scope.get("path", "")
    original_path = path
    if path == "/api/astraheal":
        request.scope["path"] = "/api/module2"
    elif path.startswith("/api/astraheal/"):
        request.scope["path"] = path.replace("/api/astraheal/", "/api/module2/", 1)
    response = await call_next(request)
    # Reports are regenerated frequently during demo/debug cycles.  Do not let
    # the browser or enterprise proxy cache stale HTML/JSON artifacts.
    effective_path = request.scope.get("path", original_path) or original_path
    if str(original_path).startswith("/artifacts/reports/") or str(effective_path).startswith("/api/module2/framework-artifact/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

RCA_FAILED_ONLY_PENDING = QA_CACHE_DIR / "rca_failed_only_pending.json"

def _read_rca_failed_only_pending() -> dict:
    if not RCA_FAILED_ONLY_PENDING.exists():
        return {"active": False}
    try:
        data = json.loads(RCA_FAILED_ONLY_PENDING.read_text(encoding="utf-8", errors="replace"))
        data["active"] = bool(data.get("active", True))
        return data
    except Exception as exc:
        return {"active": False, "error": f"{type(exc).__name__}: {exc}"}

def _write_rca_failed_only_pending(reason: str = "self_healing_patch_applied") -> dict:
    inventory = read_failed_test_inventory()
    failed_specs = inventory.get("failed_specs") or []
    data = {
        "active": bool(failed_specs),
        "reason": reason,
        "failed_specs": failed_specs,
        "failed_features": inventory.get("failed_features") or [],
        "created_at_epoch_ms": int(__import__("time").time() * 1000),
        "message": "After RCA/self-healing, the next Execute Generated Test action should rerun failed specs only unless the user explicitly starts a full regression.",
    }
    RCA_FAILED_ONLY_PENDING.parent.mkdir(parents=True, exist_ok=True)
    RCA_FAILED_ONLY_PENDING.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data

def _clear_rca_failed_only_pending() -> None:
    try:
        RCA_FAILED_ONLY_PENDING.unlink(missing_ok=True)
    except Exception:
        pass

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if GENERATED_PLAYWRIGHT_DIR.exists():
    app.mount("/artifacts", StaticFiles(directory=str(GENERATED_PLAYWRIGHT_DIR)), name="artifacts")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def _safe_feature(feature: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in (feature or "feature").strip().lower())
    return cleaned.strip("_") or "feature"


def _effective_base_url(base_url: str = "") -> str:
    return normalize_base_url(base_url or load_project_config().get("base_url", ""))


def _require_project_base_url(base_url: str = "") -> str:
    effective = _effective_base_url(base_url)
    if not effective:
        log_event("project_setup", "Blocked pipeline action because Application URL is missing. Project Setup is mandatory before JIRA/SRS generation.", status="warning", progress=0)
        raise HTTPException(status_code=409, detail="Project Setup is mandatory before Requirement/JIRA generation. Please open Project Setup, enter the application URL and save project config. For secured apps, add login/credential notes or storage state details in App Intelligence/Requirement Input.")
    return effective


def _ai_session_path() -> Path:
    QA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return QA_CACHE_DIR / "ai_provider_session.json"


def _write_ai_session(data: dict) -> dict:
    data = {**(data or {}), "updated_from_gui": True}
    _ai_session_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _ollama_quick_status() -> dict:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
        return {"host": host, "model": model, "api_ok": True, "models": models, "chat_ok": any(x.startswith(model) for x in models), "error": ""}
    except Exception as exc:
        return {"host": host, "model": model, "api_ok": False, "models": [], "chat_ok": False, "error": str(exc)}


def _provider_readiness() -> dict:
    """Fast AI readiness check for GUI.

    Codex is the default patching provider because it can write to the local
    framework workspace through the authenticated CLI.  Ollama/OpenAI/DeepSeek
    can be used for RCA and fix-proposal guidance. API keys are read from
    environment variables or from the current in-process GUI provider config.
    """
    selected = load_project_config().get("provider", "codex")
    codex = CodexCliProvider(REPO_ROOT)
    codex_status = codex.login_status() if selected in {"codex", "deterministic"} or codex.is_available() else None
    ollama_probe = _ollama_quick_status() if selected == "ollama" else {"host": os.getenv("OLLAMA_HOST", "http://localhost:11434"), "model": os.getenv("OLLAMA_MODEL", "llama3"), "api_ok": None, "chat_ok": False, "error": "not selected; quick probe skipped"}
    openai_cfg = OpenAICompatibleProvider(provider="openai")
    deepseek_cfg = OpenAICompatibleProvider(provider="deepseek")
    perplexity_cfg = OpenAICompatibleProvider(provider="perplexity")
    claude_status = AgenticCliProvider("claude", REPO_ROOT).status() if selected in {"claude", "claude_cli", "claude_code"} else None
    copilot_status = AgenticCliProvider("github_copilot", REPO_ROOT).status() if selected in {"github_copilot", "copilot", "copilot_cli"} else None
    codex_ok = bool(codex_status and codex_status.ok)
    if selected == "codex":
        ready = codex_ok
    elif selected == "ollama":
        ready = bool(ollama_probe.get("chat_ok"))
    elif selected == "openai":
        ready = openai_cfg.is_configured()
    elif selected == "deepseek":
        ready = deepseek_cfg.is_configured()
    elif selected == "perplexity":
        ready = perplexity_cfg.is_configured()
    elif selected in {"claude", "claude_cli", "claude_code"}:
        ready = bool(claude_status and claude_status.ok)
    elif selected in {"github_copilot", "copilot", "copilot_cli"}:
        ready = bool(copilot_status and copilot_status.ok)
    else:
        ready = True
    data = {
        "ok": True,
        "selected_provider": selected,
        "provider_ready": ready,
        "codex": {"available": codex.is_available(), "login_status_ok": codex_ok, "stdout": (codex_status.stdout[-1500:] if codex_status else ""), "stderr": ((codex_status.stderr or "")[-1500:] if codex_status else "")},
        "ollama": ollama_probe,
        "openai": {"configured": openai_cfg.is_configured(), "base_url": openai_cfg.base_url, "model": openai_cfg.model, "key_present": bool(openai_cfg.api_key)},
        "deepseek": {"configured": deepseek_cfg.is_configured(), "base_url": deepseek_cfg.base_url, "model": deepseek_cfg.model, "key_present": bool(deepseek_cfg.api_key)},
        "perplexity": {"configured": perplexity_cfg.is_configured(), "base_url": perplexity_cfg.base_url, "model": perplexity_cfg.model, "key_present": bool(perplexity_cfg.api_key)},
        "claude_cli": (claude_status.__dict__ if claude_status else {"available": False, "message": "not selected; quick probe skipped"}),
        "github_copilot_cli": (copilot_status.__dict__ if copilot_status else {"available": False, "message": "not selected; quick probe skipped"}),
        "provider_notes": [
            "Codex CLI is the recommended provider for direct framework-wide file modifications.",
            "OpenAI/DeepSeek/Perplexity use API keys and support RCA/proposal plus MCP readiness guidance; AstraHeal applies only guarded known TypeScript readiness fixes locally for MCP preflight.",
            "Perplexity can be used for web-grounded RCA/fix-plan guidance while Codex CLI remains the safest direct file patcher.",
            "Claude Code CLI and GitHub Copilot CLI are optional second-opinion coding assistants; enable them only when approved by enterprise policy.",
            "The backend confirms the selected provider before MCP readiness fix actions and does not silently switch to Codex.",
        ],
    }
    return _write_ai_session(data)

def _confirmed_provider_connection(provider: str = "", model: str = "", live_probe: bool = True) -> dict:
    """Backend-confirm which AI provider is actually usable for the current action.

    This is stronger than checking that an API key exists.  For OpenAI/DeepSeek
    it performs a tiny live chat/completions call when live_probe=True.  For
    Codex it checks CLI availability and login status.  For Ollama it confirms
    the local model exists.  No secret values are returned.
    """
    selected = (provider or load_project_config().get("provider") or "codex").strip().lower()
    if selected == "deterministic":
        selected = "rule_based"
    confirmation = {
        "ok": False,
        "selected_provider": selected,
        "confirmed_provider": selected,
        "backend_validated": False,
        "connection_status": "not_checked",
        "requires_codex_login": False,
        "uses_api_key": False,
        "mode": "unknown",
        "model": model or "",
        "message": "Provider validation has not run yet.",
        "safe_for_mcp_readiness_fix": False,
        "safe_for_rca_guidance": False,
        "safe_for_direct_file_patch": False,
        "next_actions": [],
    }
    try:
        if selected == "codex":
            codex = CodexCliProvider(REPO_ROOT)
            status = codex.login_status() if codex.is_available() else None
            ready = bool(codex.is_available() and status and status.ok)
            confirmation.update({
                "ok": ready,
                "backend_validated": True,
                "connection_status": "connected" if ready else "not_connected",
                "requires_codex_login": True,
                "uses_api_key": False,
                "mode": "cli_login_required",
                "message": "Backend confirmed Codex CLI is available and authenticated." if ready else "Codex is selected, but backend could not confirm an authenticated Codex CLI session on this machine.",
                "safe_for_mcp_readiness_fix": ready,
                "safe_for_rca_guidance": ready,
                "safe_for_direct_file_patch": ready,
                "next_actions": [] if ready else ["Run Fresh AI login for Codex from the GUI or run codex login in terminal.", "Then click Save & validate AI provider again."],
                "codex": {"available": codex.is_available(), "login_status_ok": bool(status and status.ok), "stderr_tail": ((status.stderr or "")[-1200:] if status else "")},
            })
        elif selected in {"claude", "claude_cli", "claude_code", "github_copilot", "copilot", "copilot_cli"}:
            cli_name = "claude" if selected in {"claude", "claude_cli", "claude_code"} else "github_copilot"
            status = AgenticCliProvider(cli_name, REPO_ROOT).status()
            confirmation.update({
                "ok": bool(status.ok),
                "backend_validated": True,
                "connection_status": "connected" if status.ok else "not_connected",
                "requires_codex_login": False,
                "uses_api_key": False,
                "mode": "optional_agentic_cli",
                "message": status.message if status.ok else (status.message or f"{cli_name} CLI is not ready on this machine."),
                "safe_for_mcp_readiness_fix": bool(status.ok),
                "safe_for_rca_guidance": bool(status.ok),
                "safe_for_direct_file_patch": False,
                "cli": status.__dict__,
                "next_actions": [] if status.ok else ["Install/authenticate the selected CLI on the Central VM/GUI backend machine.", "Confirm enterprise approval before enabling external agentic CLI patching.", "Use Codex or deterministic fallback for direct file patching until this provider is approved."],
            })
        elif selected in {"openai", "deepseek", "perplexity"}:
            client = OpenAICompatibleProvider(provider=selected, model=model or "")
            configured = client.is_configured()
            confirmation.update({
                "uses_api_key": True,
                "requires_codex_login": False,
                "mode": "api_key_no_login",
                "model": client.model,
                "base_url": client.base_url,
                "key_present": bool(client.api_key),
            })
            if not configured:
                confirmation.update({
                    "ok": False,
                    "backend_validated": True,
                    "connection_status": "missing_configuration",
                    "message": f"{selected} is selected, but backend found missing API key/base URL/model. API providers do not need Codex login.",
                    "next_actions": [f"Enter {selected} API key, base URL and model in AI connection.", "Click Save & validate AI provider.", "For permanent VM use, copy the same values into .env on the Central VM."],
                })
            elif live_probe:
                probe = client.validate_connection(timeout_seconds=45)
                confirmation.update({
                    "ok": bool(probe.ok),
                    "backend_validated": True,
                    "connection_status": "connected" if probe.ok else "failed_live_probe",
                    "message": f"Backend confirmed {selected} connection using API key/base URL/model. No Codex login is required." if probe.ok else f"{selected} is configured, but backend live validation failed: {probe.error}",
                    "safe_for_mcp_readiness_fix": bool(probe.ok),
                    "safe_for_rca_guidance": bool(probe.ok),
                    "safe_for_direct_file_patch": False,
                    "validation_response_tail": (probe.text or "")[-300:] if probe.ok else "",
                    "error": probe.error if not probe.ok else "",
                    "next_actions": [] if probe.ok else ["Check corporate proxy/firewall access to the provider base URL.", "Verify API key/model/base URL.", "Retry Save & validate AI provider."],
                })
            else:
                confirmation.update({
                    "ok": True,
                    "backend_validated": True,
                    "connection_status": "configured_not_live_probed",
                    "message": f"Backend confirmed {selected} configuration exists. Live API probe was skipped.",
                    "safe_for_mcp_readiness_fix": True,
                    "safe_for_rca_guidance": True,
                    "safe_for_direct_file_patch": False,
                })
        elif selected == "ollama":
            probe = _ollama_quick_status()
            ready = bool(probe.get("chat_ok"))
            confirmation.update({
                "ok": ready,
                "backend_validated": True,
                "connection_status": "connected" if ready else "not_connected",
                "requires_codex_login": False,
                "uses_api_key": False,
                "mode": "local_model",
                "model": probe.get("model") or os.getenv("OLLAMA_MODEL", "llama3"),
                "host": probe.get("host"),
                "message": "Backend confirmed Ollama is reachable and the selected model is available." if ready else "Ollama is selected, but backend could not confirm the selected local model.",
                "safe_for_mcp_readiness_fix": ready,
                "safe_for_rca_guidance": ready,
                "safe_for_direct_file_patch": False,
                "ollama": probe,
                "next_actions": [] if ready else ["Start Ollama on this machine.", "Pull the selected model, for example: ollama pull llama3.", "Retry Save & validate AI provider."],
            })
        elif selected in {"rule_based", "deterministic"}:
            confirmation.update({
                "ok": True,
                "confirmed_provider": "rule_based",
                "backend_validated": True,
                "connection_status": "ready_no_external_ai",
                "requires_codex_login": False,
                "uses_api_key": False,
                "mode": "no_ai",
                "message": "Rule-based mode is active. No Codex login or API key is used.",
                "safe_for_mcp_readiness_fix": True,
                "safe_for_rca_guidance": False,
                "safe_for_direct_file_patch": False,
            })
        else:
            confirmation.update({
                "ok": False,
                "backend_validated": True,
                "connection_status": "unsupported_provider",
                "message": f"Unsupported AI provider selected: {selected}.",
                "next_actions": ["Select Codex, OpenAI, DeepSeek, Ollama, or Rule-based only."],
            })
    except Exception as exc:
        confirmation.update({
            "ok": False,
            "backend_validated": True,
            "connection_status": "validation_error",
            "message": f"Provider validation failed safely: {type(exc).__name__}: {exc}",
            "error": f"{type(exc).__name__}: {exc}",
        })
    return confirmation


def _apply_base_url(normalized_path: Path, base_url: str) -> None:
    base_url = (base_url or "").strip()
    if not base_url:
        return
    try:
        data = json.loads(normalized_path.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    data.setdefault("start_url", base_url)
    for scenario in data.get("scenarios", []):
        if not scenario.get("start_url"):
            scenario["start_url"] = base_url
            changed = True
        steps = scenario.get("steps", [])
        has_goto = any(str(step.get("action", "")).lower() in {"goto", "launch", "open", "navigate"} for step in steps)
        if not has_goto:
            steps.insert(0, {"action": "goto", "target": "application", "value": base_url, "page": scenario.get("page") or data.get("page")})
            scenario["steps"] = steps
            changed = True
    if changed:
        normalized_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _source_to_normalized(source_type: str, feature: str, pasted_text: str, source_file: Optional[UploadFile], base_url: str = "") -> tuple[Path, Path]:
    ensure_dirs()
    feature = _safe_feature(feature)
    uploads_dir = QA_CACHE_DIR / "gui_uploads" / feature
    uploads_dir.mkdir(parents=True, exist_ok=True)
    if not source_file and not pasted_text.strip():
        raise HTTPException(status_code=400, detail="Upload a PDF/DOCX/JSON/TXT file or paste Jira/SRS/test steps.")
    if source_file and source_file.filename:
        original_name = Path(source_file.filename).name
        saved = uploads_dir / original_name
        with saved.open("wb") as f:
            shutil.copyfileobj(source_file.file, f)
        normalized = normalize_source_to_json(saved, source_type, feature, base_url=base_url)
        _apply_base_url(normalized, base_url)
        return saved, normalized
    saved = uploads_dir / f"{feature}_{source_type}_pasted.txt"
    saved.write_text(pasted_text, encoding="utf-8")
    normalized = normalize_source_to_json(saved, source_type, feature, pasted_text=pasted_text, base_url=base_url)
    _apply_base_url(normalized, base_url)
    return saved, normalized


def _save_optional_page_source(feature: str, page_source_file: Optional[UploadFile]) -> dict:
    if not page_source_file or not page_source_file.filename:
        # Auto-use bundled Acima page source for the Acima sample/application if available.
        report = analyze_page_source(feature, _effective_base_url())
        return {"uploaded": False, "auto_analyzed": bool(report.get("ok")), "report": report}
    uploads_dir = QA_CACHE_DIR / "gui_uploads" / _safe_feature(feature)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved = uploads_dir / Path(page_source_file.filename).name
    with saved.open("wb") as f:
        shutil.copyfileobj(page_source_file.file, f)
    cached = save_uploaded_page_source(_safe_feature(feature), saved)
    report = analyze_page_source(_safe_feature(feature), _effective_base_url(), source_path=cached)
    return {"uploaded": True, "source_uploaded": _relative(saved), "cached": _relative(cached), "report": report}


def _page_name_for_feature(feature: str, source_type: str = "jira") -> str:
    testcase_path = feature_testcase_path(source_type, feature)
    if testcase_path.exists():
        try:
            tc = read_json(testcase_path)
            scenarios = tc.get("scenarios", [])
            if scenarios and scenarios[0].get("page"):
                return pascal_case(scenarios[0]["page"])
        except Exception:
            pass
    return pascal_case(feature)


def _playwright_preview(feature: str, source_type: str = "jira") -> dict[str, str]:
    page_name = _page_name_for_feature(feature, source_type)
    spec_path = GENERATED_PLAYWRIGHT_DIR / "tests" / "generated" / f"{feature}.spec.ts"
    page_path = GENERATED_PLAYWRIGHT_DIR / "pages" / f"{page_name}Page.ts"
    objects_path = GENERATED_PLAYWRIGHT_DIR / "pageObjects" / f"{page_name}Page.objects.ts"
    inventory_path = GENERATED_PLAYWRIGHT_DIR / "reports" / "framework-inventory.json"
    reuse_report = GENERATED_PLAYWRIGHT_DIR / "reports" / "reuse-decision-report.md"
    quality_report = GENERATED_PLAYWRIGHT_DIR / "reports" / "quality-review.json"
    page_source_map = GENERATED_PLAYWRIGHT_DIR / "reports" / "page-source-map.json"
    return {
        "page_name": page_name,
        "generated_spec_preview": spec_path.read_text(encoding="utf-8")[-12000:] if spec_path.exists() else "",
        "generated_page_preview": page_path.read_text(encoding="utf-8")[-12000:] if page_path.exists() else "",
        "generated_objects_preview": objects_path.read_text(encoding="utf-8")[-12000:] if objects_path.exists() else "",
        "framework_inventory_preview": inventory_path.read_text(encoding="utf-8")[-12000:] if inventory_path.exists() else "",
        "reuse_report_preview": reuse_report.read_text(encoding="utf-8")[-12000:] if reuse_report.exists() else "",
        "quality_report_preview": quality_report.read_text(encoding="utf-8")[-12000:] if quality_report.exists() else "",
        "page_source_map_preview": page_source_map.read_text(encoding="utf-8")[-12000:] if page_source_map.exists() else "",
    }



def _generated_spec_path(feature: str) -> Path:
    return GENERATED_PLAYWRIGHT_DIR / "tests" / "generated" / f"{_safe_feature(feature)}.spec.ts"


def _available_generated_specs() -> list[str]:
    spec_dir = GENERATED_PLAYWRIGHT_DIR / "tests" / "generated"
    if not spec_dir.exists():
        return []
    return sorted(str(p.relative_to(REPO_ROOT)) for p in spec_dir.glob("*.spec.ts"))


def _latest_run_path() -> Path:
    return QA_CACHE_DIR / "latest_playwright_generation.json"


def _remember_latest_generation(feature: str, source_type: str, spec_path: Path, testcase_path: Path) -> None:
    QA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "feature": _safe_feature(feature),
        "source_type": source_type,
        "spec_path": _relative(spec_path),
        "testcase_path": _relative(testcase_path),
        "available_specs": _available_generated_specs(),
    }
    _latest_run_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _active_features(feature: str, source_type: str) -> list[str]:
    return active_features_for_request(_safe_feature(feature), source_type)


def _is_active_batch_request(feature: str, source_type: str) -> bool:
    return bool(_active_features(feature, source_type))


def _batch_manifest(features: list[str], source_type: str, parent_feature: str = "") -> dict:
    features = [_safe_feature(f) for f in features if str(f).strip()]
    return {
        "active": True,
        "source_type": source_type,
        "parent_feature": _safe_feature(parent_feature or (features[0] if features else "feature")),
        "features": features,
        "spec_paths": [_relative(_generated_spec_path(f)) for f in features],
        "testcase_paths": [_relative(feature_testcase_path(source_type, f)) for f in features],
    }


def _generate_one_playwright_feature(feature: str, source_type: str, provider: str, model: str, base_url: str, run_ai: bool = True) -> dict:
    feature = _safe_feature(feature)
    testcase_path = feature_testcase_path(source_type, feature)
    if not testcase_path.exists():
        return {"ok": False, "feature": feature, "error": f"Functional testcase file not found for active source: {testcase_path}"}
    sanitize_testcase_urls(testcase_path, base_url)
    testcase_json = read_json(testcase_path)
    if run_ai:
        try:
            ai_meta = _ai_codegen_message(provider, model, feature, source_type, testcase_json)
        except Exception as exc:
            ai_meta = {"provider": provider, "ai_ok": False, "message": f"AI codegen assistance failed safely: {type(exc).__name__}: {exc}"}
    else:
        ai_meta = {"provider": provider, "ai_ok": True, "message": "AI guidance was executed once at batch level. This feature used deterministic guarded file generation under the shared write lock.", "batch_scoped": True}
    log_event("playwright_generation", f"Generating reusable Playwright files for {feature}", progress=45, feature=feature, source_type=source_type, details={"run_ai_per_feature": run_ai})
    generation = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
    log_event("playwright_generation", f"Generated spec/page/pageObjects for {feature}", status="done", progress=65, feature=feature, source_type=source_type)
    spec_path = _generated_spec_path(feature)
    if spec_path.exists():
        _remember_latest_generation(feature, source_type, spec_path, testcase_path)
    return {
        "ok": spec_path.exists(),
        "feature": feature,
        "source_type": source_type,
        "testcase_file": _relative(testcase_path),
        "spec_path": _relative(spec_path),
        "spec_exists": spec_path.exists(),
        "created": [d.__dict__ for d in generation.created],
        "reused": [d.__dict__ for d in generation.reused],
        "files": generation.files,
        "ai": ai_meta,
    }


def _generate_playwright_batch(features: list[str], source_type: str, provider: str, model: str, base_url: str, parent_feature: str = "") -> dict:
    features = [_safe_feature(f) for f in features if str(f).strip()]
    log_event("playwright_generation", f"Starting Playwright generation batch for {len(features)} feature(s)", progress=5, source_type=source_type, details={"features": features})
    page_source_report = analyze_page_source(feature=parent_feature or (features[0] if features else "feature"), base_url=base_url)
    log_event("app_profile", "Page-source analyzer completed before Playwright generation", progress=10, source_type=source_type)
    crawl_report = crawl_dynamic_page(base_url=base_url, feature=parent_feature or (features[0] if features else "feature"), headed=False)
    log_event("app_profile", "Dynamic DOM crawler completed before Playwright generation", progress=18, source_type=source_type)
    app_profile = profile_application(feature=parent_feature or (features[0] if features else "feature"), base_url=base_url, use_mcp=True)
    log_event("app_profile", "App Intelligence profile completed", progress=24, source_type=source_type)

    testcase_sets: list[dict] = []
    missing_testcases: list[str] = []
    for f in features:
        path = feature_testcase_path(source_type, f)
        if not path.exists():
            missing_testcases.append(f)
        else:
            testcase_sets.append(read_json(path))
    if missing_testcases:
        log_event("playwright_generation", f"Cannot generate Playwright; missing testcase files: {missing_testcases}", status="error", progress=25, source_type=source_type)
        return {"ok": False, "error": "Functional testcase file(s) missing for active source", "missing_features": missing_testcases, "features": features}

    # Important design decision: code writes are guarded by a shared framework write-lock.
    # Jira/SRS testcase normalization can run in parallel, but Playwright generation may edit the
    # same pageObjects/page class for multiple stories. Parallel writes can corrupt files or break
    # reusability. Therefore, the default enterprise mode is correctness-first sequential file
    # generation with one AI batch preflight, explicit logs, and progress visibility.
    shared_pages: dict[str, list[str]] = {}
    for f, tc in zip(features, testcase_sets):
        scenarios = tc.get("scenarios", []) if isinstance(tc, dict) else []
        page = str(tc.get("page") or (scenarios[0].get("page") if scenarios else parent_feature or f))
        shared_pages.setdefault(page, []).append(f)
    has_shared_page = any(len(v) > 1 for v in shared_pages.values())
    generation_strategy = "controlled_sequential_write_lock" if has_shared_page else "parallel_safe_but_sequential_for_auditability"
    log_event("playwright_generation", "Using correctness-first controlled generation. Functional testcases are parallel; Playwright file writes are serialized to protect shared pageObjects/page classes.", progress=28, source_type=source_type, details={"strategy": generation_strategy, "shared_pages": shared_pages})

    ai_batch = _ai_batch_codegen_message(provider, model, features, source_type, testcase_sets)
    results = []
    total = max(len(features), 1)
    for idx, f in enumerate(features, start=1):
        pct = 30 + int((idx - 1) / total * 45)
        log_event("playwright_generation", f"Generating feature {idx}/{total}: {f}", progress=pct, feature=f, source_type=source_type, details={"strategy": generation_strategy})
        results.append(_generate_one_playwright_feature(f, source_type, provider, model, base_url, run_ai=False))
    review = run_review(skip_npm=True)
    log_event("playwright_generation", "Static review completed after batch generation", progress=85, source_type=source_type, details={"review_ok": review.get("ok")})
    summary_path = generate_summary()
    html_report_path = generate_enterprise_html_report()
    ok = all(r.get("ok") for r in results) and bool(review.get("ok", True))
    ctx = _batch_manifest(features, source_type, parent_feature=parent_feature)
    ctx.update({"playwright_generated": ok, "channel": "active_batch", "functional_testcases_reviewed": True, "generation_strategy": generation_strategy})
    write_active_context(ctx)
    log_event("playwright_generation", f"Playwright batch generation {'completed' if ok else 'completed with issues'}", status="done" if ok else "warning", progress=100, source_type=source_type, details={"features": features, "ok": ok})
    return {
        "ok": ok,
        "stage": "playwright_batch_generated",
        "active_context": ctx,
        "generation_scope": "active_source_batch_only",
        "features": features,
        "results": results,
        "available_specs": _available_generated_specs(),
        "review": review,
        "summary": _relative(summary_path),
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "page_source": page_source_report,
        "crawl_report": crawl_report,
        "app_intelligence_profile": app_profile,
        "ai_batch_preflight": ai_batch,
        "generation_strategy": generation_strategy,
        "strategy_explanation": "Functional testcase generation is parallel. Playwright script generation is serialized when features share page/pageObjects files because correctness and reusable-framework integrity are more important than speed. The runtime logger and Grafana metrics show each queued feature/stage.",
        "runtime_log_summary": write_runtime_summary(),
        "message": "Generated Playwright only for the active source context. Old specs from prior sessions are not selected for execution.",
    }

def _ensure_specs_for_features(features: list[str], source_type: str, provider: str, model: str, base_url: str, parent_feature: str = "") -> dict:
    missing = [f for f in features if not _generated_spec_path(f).exists()]
    if not missing:
        return {"ok": True, "generated_now": False, "features": features, "missing_before": [], "available_specs": _available_generated_specs()}
    generated = _generate_playwright_batch(missing, source_type, provider, model, base_url, parent_feature=parent_feature)
    still_missing = [f for f in features if not _generated_spec_path(f).exists()]
    return {"ok": not still_missing, "generated_now": True, "features": features, "missing_before": missing, "still_missing": still_missing, "generation": generated}


def _ensure_spec_exists_for_execution(feature: str, source_type: str, base_url: str) -> dict:
    """Make Execute deterministic in the same GUI session.

    Users often upload testcase1, generate/run it, then upload testcase2 and press Execute.
    The runner should not fail with a low-level "spec not found" message when the testcase JSON
    exists but the matching spec has not yet been materialized.  This helper regenerates only the
    requested feature's reusable Playwright files when safe, and otherwise returns a friendly reason.
    """
    feature = _safe_feature(feature)
    source_type = (source_type or load_project_config().get("source_type") or "srs").strip() or "srs"
    spec_path = _generated_spec_path(feature)
    if spec_path.exists():
        return {
            "ok": True,
            "generated_now": False,
            "feature": feature,
            "source_type": source_type,
            "spec_path": _relative(spec_path),
            "available_specs": _available_generated_specs(),
        }

    testcase_path = feature_testcase_path(source_type, feature)
    if not testcase_path.exists():
        # If the form source_type is stale, try all supported source folders for the same feature.
        fallback_match = None
        for candidate_source in ["srs", "jira", "jira_epics", "pdf", "pdf_docs", "confluence", "test_management"]:
            candidate = feature_testcase_path(candidate_source, feature)
            if candidate.exists():
                fallback_match = (candidate_source, candidate)
                break
        if fallback_match:
            source_type, testcase_path = fallback_match
        else:
            return {
                "ok": False,
                "generated_now": False,
                "feature": feature,
                "source_type": source_type,
                "spec_path": _relative(spec_path),
                "available_specs": _available_generated_specs(),
                "message": (
                    f"No generated Playwright spec exists for feature '{feature}', and no functional testcase JSON was found. "
                    "Generate functional testcases first, then Generate Reusable Playwright, then Execute."
                ),
            }

    sanitize_testcase_urls(testcase_path, base_url)
    generation = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
    review = run_review(skip_npm=True)
    exists_after = spec_path.exists()
    if exists_after:
        _remember_latest_generation(feature, source_type, spec_path, testcase_path)
    return {
        "ok": exists_after,
        "generated_now": exists_after,
        "feature": feature,
        "source_type": source_type,
        "spec_path": _relative(spec_path),
        "testcase_path": _relative(testcase_path),
        "available_specs": _available_generated_specs(),
        "generation_files": generation.files,
        "review": review,
        "message": "Spec was generated automatically from the current functional testcase before execution." if exists_after else f"Spec could not be generated for feature '{feature}'.",
    }

def _ai_codegen_message(provider: str, model: str, feature: str, source_type: str, testcase_json: dict) -> dict:
    inv = scan_framework()
    log_event("ai_codegen", f"Preparing AI codegen guidance for feature {feature}", progress=15, feature=feature, source_type=source_type)
    if provider == "codex":
        prompt = build_codex_prompt(feature, testcase_json, inv)
        log_event("ai_codegen", f"Calling Codex CLI once for feature {feature}", progress=35, feature=feature, source_type=source_type)
        result = CodexCliProvider(REPO_ROOT).run(prompt)
        log_event("ai_codegen", f"Codex CLI finished for {feature}: {'ok' if result.ok else 'failed safely'}", status="done" if result.ok else "warning", progress=80, feature=feature, source_type=source_type)
        return {"provider": "codex", "ai_ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-6000:]}
    if provider == "ollama":
        prompt = build_codex_prompt(feature, testcase_json, inv)
        log_event("ai_codegen", f"Calling Ollama model {model} for feature {feature}", progress=35, feature=feature, source_type=source_type)
        result = OllamaProvider(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"), model=model).chat(prompt)
        log_event("ai_codegen", f"Ollama finished for {feature}: {'ok' if result.ok else 'failed safely'}", status="done" if result.ok else "warning", progress=80, feature=feature, source_type=source_type)
        return {"provider": "ollama", "ai_ok": result.ok, "message": (result.text if result.ok else result.error)[-6000:]}
    return {"provider": "deterministic", "ai_ok": True, "message": "Deterministic generator used. AI provider was not selected for this run."}


def _ai_batch_codegen_message(provider: str, model: str, features: list[str], source_type: str, testcase_sets: list[dict]) -> dict:
    """Run one AI preflight for a Jira/SRS batch instead of one slow Codex call per child story.

    The actual file writes stay deterministic and guarded. This gives LLM context while avoiding
    30+ minute generation for small Jira batches.
    """
    features = [_safe_feature(f) for f in features]
    if provider not in {"codex", "ollama"}:
        return {"provider": "deterministic", "ai_ok": True, "message": "Batch deterministic mode. No AI preflight selected."}
    compact = []
    for f, tc in zip(features, testcase_sets):
        compact.append({
            "feature": f,
            "page": tc.get("page"),
            "scenario_count": len(tc.get("scenarios", []) or []),
            "titles": [s.get("title") for s in (tc.get("scenarios", []) or [])[:5]],
        })
    prompt = """
You are validating an enterprise Playwright generation batch.
Return concise guidance only; do not edit files in this step.
Check for risks: missing base_url, generic assertions, duplicate scenarios, shared pageObject write conflicts, locator strategy, and whether generation should be sequential or parallel.
Batch manifest:
""" + json.dumps(compact, indent=2, ensure_ascii=False)
    log_event("playwright_generation", f"Running one {provider} batch preflight for {len(features)} feature(s)", progress=20, details={"features": features})
    try:
        if provider == "codex":
            result = CodexCliProvider(REPO_ROOT).run(prompt)
            return {"provider": "codex", "ai_ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-6000:], "batch_preflight": True}
        result = OllamaProvider(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"), model=model).chat(prompt)
        return {"provider": "ollama", "ai_ok": result.ok, "message": (result.text if result.ok else result.error)[-6000:], "batch_preflight": True}
    except Exception as exc:
        return {"provider": provider, "ai_ok": False, "batch_preflight": True, "message": f"AI batch preflight failed safely: {type(exc).__name__}: {exc}"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html_file = STATIC_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@app.get("/astraheal-ai", response_class=HTMLResponse)
def astraheal_ai_index() -> str:
    return index()


@app.get("/agentic-automation-studio", response_class=HTMLResponse)
def agentic_automation_studio_index() -> str:
    return index()


@app.get("/api/agents")
def api_agents() -> dict:
    return get_agent_coverage_report()


@app.get("/api/agents/coverage")
def api_agents_coverage() -> dict:
    return get_agent_coverage_report()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "repo_root": str(REPO_ROOT)}


@app.get("/api/runtime/logs")
def api_runtime_logs(limit: int = 250) -> dict:
    summary = write_runtime_summary()
    return {
        "ok": True,
        "current": current_status(),
        "events": read_events(limit),
        "summary": summary,
        "live_console_url": "/artifacts/reports/runtime-live-console.html",
        "grafana_url": "http://localhost:3001",
        "prometheus_url": "http://localhost:9090",
        "prometheus_targets_url": "http://localhost:9090/targets",
        "metrics_url": "/metrics",
        "plain_english_hint": "Use Live Pipeline Console first for real-time progress. Use Grafana when Prometheus/Grafana containers are running and logged in.",
    }


@app.get("/api/runtime/status")
def api_runtime_status() -> dict:
    return {"ok": True, "current": current_status(), "summary": write_runtime_summary(), "events_tail": read_events(20)}


@app.post("/api/existing-framework/artifact-locations")
async def api_existing_framework_artifact_locations(framework_path: str = Form("")) -> JSONResponse:
    """Show absolute local report/log/cache paths for explainability."""
    report = await run_in_threadpool(existing_framework_artifact_locations, framework_path=framework_path)
    return JSONResponse(report)


@app.post("/api/runtime/reset")
def api_runtime_reset() -> dict:
    event = reset_runtime_logs()
    return {"ok": True, "event": event, "summary": write_runtime_summary()}


@app.get("/runtime-console", response_class=HTMLResponse)
def runtime_console() -> HTMLResponse:
    path = write_runtime_live_html()
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/api/grafana/help")
def api_grafana_help() -> dict:
    return {
        "ok": True,
        "grafana_url": "http://localhost:3001",
        "default_username": "admin",
        "default_password": "admin",
        "important_note": "If admin/admin fails, Grafana has probably stored a changed password in its Docker volume.",
        "reset_password_command": "docker compose -f infra/docker/docker-compose.yml exec grafana grafana cli admin reset-admin-password admin",
        "prometheus_targets_url": "http://localhost:9090/targets",
        "pipeline_metrics_url": "http://127.0.0.1:8080/metrics",
        "recommended_easy_option": "Use the GUI Runtime Logs tab or /runtime-console for live progress; Grafana is the enterprise dashboard and needs the Grafana container plus login.",
    }


@app.get("/metrics", response_class=PlainTextResponse)
def api_prometheus_metrics() -> str:
    return prometheus_metrics()



@app.get("/api/sample/acima")
def sample_acima() -> dict:
    sample = REPO_ROOT / "samples" / "srs" / "acima_requirements.txt"
    return {"ok": sample.exists(), "feature": "acima", "source_type": "srs", "base_url": "https://www.acima.com/en", "text": sample.read_text(encoding="utf-8") if sample.exists() else "", "page_source_sample_available": (REPO_ROOT / "samples" / "page_sources" / "acima_home_source.txt").exists()}


@app.get("/api/doctor")
def doctor() -> dict:
    log_event("doctor", "Prerequisite verification started", status="running", progress=10)
    data = run_doctor()
    data["project_config"] = load_project_config()
    data["docker_summary"] = docker_status()
    data["runtime_profile"] = read_runtime_profile()
    log_event("doctor", "Prerequisite verification completed", status="ok" if data.get("ok", True) else "warning", progress=100)
    return data


@app.get("/api/project")
def project() -> dict:
    config = load_project_config()
    return {
        "repo_root": str(REPO_ROOT),
        "generated_playwright_dir": _relative(GENERATED_PLAYWRIGHT_DIR),
        "testcases_dir": "testcases",
        "project_config": config,
        "base_url_env": os.getenv("BASE_URL", ""),
        "codegen_provider_env": os.getenv("CODEGEN_PROVIDER", "deterministic"),
        "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        "ollama_model_env": os.getenv("OLLAMA_MODEL", "llama3"),
        "playwright_mcp_enabled": os.getenv("PLAYWRIGHT_MCP_ENABLED", "true"),
        "important_rule": "All Playwright files are generated only under generated-playwright/.",
        "active_source_context": read_active_context(),
    }


@app.post("/api/project/save")
async def save_project(
    project_name: str = Form("AI QA Automation Project"),
    application_name: str = Form("Application Under Test"),
    base_url: str = Form(""),
    source_type: str = Form("jira"),
    feature: str = Form("login"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    project: str = Form("auto"),
    use_mcp: bool = Form(True),
    skip_npm: bool = Form(False),
    test_id_attribute: str = Form("data-test"),
) -> JSONResponse:
    config = save_project_config({
        "project_name": project_name,
        "application_name": application_name,
        "base_url": base_url,
        "source_type": source_type,
        "feature": _safe_feature(feature),
        "provider": provider,
        "ollama_model": model,
        "execution_project": project,
        "use_mcp": use_mcp,
        "skip_npm": skip_npm,
        "test_id_attribute": test_id_attribute,
    })
    log_event("project_setup", "Project Setup saved. Application URL and feature context are available for crawling and generation.", status="done", progress=100, feature=_safe_feature(feature), source_type=source_type, details={"base_url": base_url, "provider": provider})
    return JSONResponse({"ok": True, "message": "Project config saved for this repo. Next mandatory step: JIRA/Requirement Input, then Functional Testcases review.", "project_config": config})


@app.post("/api/app/check")
async def app_check(base_url: str = Form("")) -> JSONResponse:
    return JSONResponse(check_application_url(base_url))





@app.post("/api/runner-agents/token/create")
def api_runner_agent_create_token(agent_name: str = Form(""), workspace_root: str = Form("D:\\AI_QA_WORKSPACE")):
    data = create_agent_token(agent_name=agent_name, workspace_root=workspace_root, created_by="gui")
    return JSONResponse(data)


@app.get("/api/runner-agents/list")
def api_runner_agents_list():
    return JSONResponse(list_vdi_runner_agents())


@app.get("/api/runner-agents/package")
def api_runner_agent_package(token: str, control_plane_url: str = "", agent_name: str = "", workspace_root: str = "D:\\AI_QA_WORKSPACE"):
    control_url = control_plane_url or "http://127.0.0.1:8080"
    data = build_agent_package(control_url, token, agent_name=agent_name, workspace_root=workspace_root)
    if not data.get("ok"):
        raise HTTPException(status_code=400, detail=data)
    return FileResponse(data["zip_path"], filename=Path(data["zip_path"]).name, media_type="application/zip")


@app.post("/api/runner-agents/job/create")
def api_runner_agent_job_create(agent_id: str = Form(""), command: str = Form(""), working_dir: str = Form(""), job_type: str = Form("command")):
    return JSONResponse(create_agent_job(agent_id=agent_id, command=command, working_dir=working_dir, job_type=job_type, created_by="gui"))


@app.post("/api/runner-agents/register")
async def api_runner_agent_register(request: Request):
    payload = await request.json()
    return JSONResponse(register_agent(payload))


@app.post("/api/runner-agents/heartbeat")
async def api_runner_agent_heartbeat(request: Request):
    payload = await request.json()
    return JSONResponse(heartbeat_agent(payload))


@app.get("/api/runner-agents/poll")
def api_runner_agent_poll(agent_id: str, token: str):
    return JSONResponse(poll_agent_job(agent_id=agent_id, token=token))


@app.post("/api/runner-agents/job/complete")
async def api_runner_agent_job_complete(request: Request):
    payload = await request.json()
    return JSONResponse(complete_agent_job(payload))

@app.post("/api/vdi/profile/save")
async def api_vdi_profile_save(
    vdi_type: str = Form("horizon"),
    client_environment: str = Form("client-hosted VDI"),
    docker_mode: str = Form("local"),
    docker_host: str = Form(""),
    app_base_url: str = Form(""),
    api_base_url: str = Form(""),
    proxy_url: str = Form(""),
    no_proxy: str = Form("localhost,127.0.0.1,host.docker.internal"),
    notes: str = Form(""),
) -> JSONResponse:
    payload = {
        "vdi_type": vdi_type,
        "client_environment": client_environment,
        "docker_mode": docker_mode,
        "docker_host": docker_host,
        "app_base_url": app_base_url,
        "api_base_url": api_base_url,
        "proxy_url": proxy_url,
        "no_proxy": no_proxy,
        "notes": notes,
    }
    return JSONResponse(save_vdi_profile(payload))


@app.get("/api/vdi/profile")
def api_vdi_profile() -> dict:
    return read_vdi_profile()


@app.post("/api/vdi/readiness")
async def api_vdi_readiness(
    app_base_url: str = Form(""),
    api_base_url: str = Form(""),
    docker_mode: str = Form("local"),
    docker_host: str = Form(""),
) -> JSONResponse:
    data = check_vdi_readiness(base_url=app_base_url, api_base_url=api_base_url, docker_mode=docker_mode, docker_host=docker_host)
    return JSONResponse(data)




@app.get("/api/runtime-mode/profile")
def api_runtime_mode_profile() -> dict:
    return read_runtime_profile()


@app.post("/api/runtime-mode/profile")
async def api_runtime_mode_profile_save(
    runtime_mode: str = Form("local"),
    runtime_engine: str = Form("docker"),
    control_plane_url: str = Form("http://127.0.0.1:8080"),
    vm_public_url: str = Form(""),
    default_execution_target: str = Form("local"),
    docker_runtime: str = Form("local"),
    workspace_root: str = Form(""),
    reports_root: str = Form(""),
    use_vdi_agents: bool = Form(False),
    notes: str = Form(""),
) -> JSONResponse:
    data = save_runtime_profile({
        "runtime_mode": runtime_mode,
        "runtime_engine": runtime_engine if runtime_engine in {"docker", "host", "auto"} else "docker",
        "control_plane_url": control_plane_url,
        "vm_public_url": vm_public_url,
        "default_execution_target": default_execution_target,
        "docker_runtime": docker_runtime,
        "workspace_root": workspace_root or str(REPO_ROOT),
        "reports_root": reports_root or str(GENERATED_PLAYWRIGHT_DIR / "reports"),
        "use_vdi_agents": use_vdi_agents,
        "notes": notes,
    })
    log_event("runtime_mode", f"Runtime mode saved: {data.get('runtime_mode')}", status="ok", progress=100)
    return JSONResponse(data)


@app.get("/api/runtime-mode/local-readiness")
def api_runtime_mode_local_readiness() -> dict:
    log_event("local_readiness", "Local machine readiness check started", status="running", progress=10)
    data = local_machine_readiness()
    log_event("local_readiness", "Local machine readiness check completed", status="ok", progress=100)
    return data




@app.get("/api/host-runtime/readiness")
def api_host_runtime_readiness() -> dict:
    log_event("host_runtime", "No-Docker Host Runtime readiness check started", status="running", progress=10)
    data = host_runtime_readiness()
    log_event("host_runtime", "No-Docker Host Runtime readiness check completed", status="ok" if data.get("ok") else "warning", progress=100)
    return data


@app.post("/api/host-runtime/start")
async def api_host_runtime_start() -> JSONResponse:
    log_event("host_runtime", "No-Docker Host Services start requested", status="running", progress=10)
    data = start_host_services()
    log_event("host_runtime", "No-Docker Host Services start completed", status="ok" if data.get("ok") else "warning", progress=100)
    return JSONResponse(data)


@app.post("/api/host-runtime/stop")
async def api_host_runtime_stop() -> JSONResponse:
    data = stop_host_services()
    return JSONResponse(data)


@app.get("/api/host-runtime/status")
def api_host_runtime_status() -> dict:
    return host_runtime_status()


@app.get("/api/host-runtime/install-plan")
def api_host_runtime_install_plan() -> dict:
    return host_install_plan()


@app.get("/api/llm/status")
def llm_status() -> dict:
    log_event("ai_provider", "AI provider readiness check started", status="running", progress=10)
    data = _provider_readiness()
    confirmation = _confirmed_provider_connection(data.get("selected_provider", "codex"), live_probe=True)
    data["confirmed_provider_connection"] = confirmation
    data["provider_ready"] = bool(confirmation.get("ok"))
    data["backend_confirmed_message"] = confirmation.get("message")
    data["codex"].update({
        "how_to_connect": ["Use GUI: Codex / Ollama -> Codex login/device auth", "or run codex login --device-auth in terminal", "Use Fresh Codex Login when you want an explicit new user session. The GUI never auto-connects by default."],
        "security_note": "Do not store ChatGPT username/password or OpenAI keys in .env. Codex manages your local login session.",
    })
    data["ollama"].update({
        "how_to_connect": ["Use GUI: Codex / Ollama -> Ensure Ollama model", "or run docker compose up -d ollama and ollama pull llama3", "The Docker Ollama model is reused by the pipeline."],
    })
    log_event("ai_provider", confirmation.get("message", "AI provider readiness check completed"), status="ok" if confirmation.get("ok") else "warning", progress=100, details={"confirmed_provider": confirmation.get("confirmed_provider"), "connection_status": confirmation.get("connection_status")})
    return data


def _apply_ai_provider_env_from_values(
    openai_api_key: str = "",
    openai_base_url: str = "",
    openai_model: str = "",
    deepseek_api_key: str = "",
    deepseek_base_url: str = "",
    deepseek_model: str = "",
    perplexity_api_key: str = "",
    perplexity_base_url: str = "",
    perplexity_model: str = "",
    ollama_host: str = "",
    ollama_model: str = "",
) -> None:
    """Apply GUI-provided provider values to this backend process only.

    Secrets are not written to reports or docs. For permanent Central VM setup,
    the same values should still be placed in .env or machine environment vars.
    """
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key.strip()
    if openai_base_url:
        os.environ["OPENAI_BASE_URL"] = openai_base_url.strip().rstrip("/")
    if openai_model:
        os.environ["OPENAI_MODEL"] = openai_model.strip()
    if deepseek_api_key:
        os.environ["DEEPSEEK_API_KEY"] = deepseek_api_key.strip()
    if deepseek_base_url:
        os.environ["DEEPSEEK_BASE_URL"] = deepseek_base_url.strip().rstrip("/")
    if deepseek_model:
        os.environ["DEEPSEEK_MODEL"] = deepseek_model.strip()
    if perplexity_api_key:
        os.environ["PERPLEXITY_API_KEY"] = perplexity_api_key.strip()
    if perplexity_base_url:
        os.environ["PERPLEXITY_BASE_URL"] = perplexity_base_url.strip().rstrip("/")
    if perplexity_model:
        os.environ["PERPLEXITY_MODEL"] = perplexity_model.strip()
    if ollama_host:
        os.environ["OLLAMA_HOST"] = ollama_host.strip().rstrip("/")
    if ollama_model:
        os.environ["OLLAMA_MODEL"] = ollama_model.strip()


def _model_for_selected_provider(provider: str, model: str = "", openai_model: str = "", deepseek_model: str = "", ollama_model: str = "", perplexity_model: str = "") -> str:
    selected = (provider or "codex").strip().lower()
    if selected == "openai":
        return openai_model or model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if selected == "deepseek":
        return deepseek_model or model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    if selected == "perplexity":
        return perplexity_model or model or os.getenv("PERPLEXITY_MODEL", "sonar")
    if selected == "ollama":
        return ollama_model or model or os.getenv("OLLAMA_MODEL", "llama3")
    return model or ""


@app.post("/api/llm/provider-confirmation")
async def api_llm_provider_confirmation(
    provider: str = Form("codex"),
    model: str = Form(""),
    openai_api_key: str = Form(""),
    openai_base_url: str = Form(""),
    openai_model: str = Form(""),
    deepseek_api_key: str = Form(""),
    deepseek_base_url: str = Form(""),
    deepseek_model: str = Form(""),
    perplexity_api_key: str = Form(""),
    perplexity_base_url: str = Form(""),
    perplexity_model: str = Form(""),
    ollama_host: str = Form(""),
    ollama_model: str = Form(""),
) -> JSONResponse:
    """Validate and confirm which backend AI provider will actually be used.

    This endpoint is used by the GUI before AI-backed fix actions so users see
    whether Codex login, OpenAI key, DeepSeek key, Perplexity key, Ollama, or rule-based mode is
    the active support path.
    """
    _apply_ai_provider_env_from_values(
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
        deepseek_model=deepseek_model,
        perplexity_api_key=perplexity_api_key,
        perplexity_base_url=perplexity_base_url,
        perplexity_model=perplexity_model,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
    )
    selected_provider = (provider or "codex").strip().lower()
    selected_model = _model_for_selected_provider(selected_provider, model, openai_model, deepseek_model, ollama_model, perplexity_model)
    cfg = load_project_config()
    cfg["provider"] = selected_provider
    if selected_model:
        cfg["ollama_model"] = selected_model
    save_project_config(cfg)
    confirmation = _confirmed_provider_connection(provider=selected_provider, model=selected_model, live_probe=True)
    log_event("ai_provider", confirmation.get("message", "AI provider backend confirmation completed"), status="ok" if confirmation.get("ok") else "warning", progress=100, details={"provider": selected_provider, "connection_status": confirmation.get("connection_status")})
    return JSONResponse({"ok": bool(confirmation.get("ok")), "message": confirmation.get("message"), "selected_provider": selected_provider, "confirmed_provider_connection": confirmation})


@app.post("/api/llm/provider-config/save")
async def api_llm_provider_config_save(
    provider: str = Form("codex"),
    openai_api_key: str = Form(""),
    openai_base_url: str = Form(""),
    openai_model: str = Form(""),
    deepseek_api_key: str = Form(""),
    deepseek_base_url: str = Form(""),
    deepseek_model: str = Form(""),
    perplexity_api_key: str = Form(""),
    perplexity_base_url: str = Form(""),
    perplexity_model: str = Form(""),
    ollama_host: str = Form(""),
    ollama_model: str = Form(""),
) -> JSONResponse:
    """Save current-process AI provider settings for the GUI session.

    For enterprise safety, API keys are not written into README files or reports.
    This endpoint updates the current process environment and the lightweight
    provider session cache so the user can verify readiness.  For permanent use,
    put the same values in .env on each VM/worker.
    """
    _apply_ai_provider_env_from_values(
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
        deepseek_model=deepseek_model,
        perplexity_api_key=perplexity_api_key,
        perplexity_base_url=perplexity_base_url,
        perplexity_model=perplexity_model,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
    )
    selected_provider = (provider or "codex").strip().lower()
    selected_model = _model_for_selected_provider(selected_provider, "", openai_model, deepseek_model, ollama_model, perplexity_model)
    cfg = load_project_config()
    cfg["provider"] = selected_provider
    if selected_model:
        cfg["ollama_model"] = selected_model
    save_project_config(cfg)
    readiness = _provider_readiness()
    confirmation = _confirmed_provider_connection(provider=selected_provider, model=selected_model, live_probe=True)
    readiness["confirmed_provider_connection"] = confirmation
    return JSONResponse({
        "ok": bool(confirmation.get("ok")),
        "message": confirmation.get("message") or "AI provider configuration saved and backend validation completed.",
        "selected_provider": selected_provider,
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "deepseek_key_present": bool(os.getenv("DEEPSEEK_API_KEY")),
        "perplexity_key_present": bool(os.getenv("PERPLEXITY_API_KEY")),
        "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        "readiness": readiness,
        "confirmed_provider_connection": confirmation,
        "note": "API providers including OpenAI, DeepSeek and Perplexity use API keys and do not need Codex login. Codex uses CLI login and no API key is required.",
    })


@app.post("/api/llm/codex/login")
async def api_codex_login(mode: str = Form("device")) -> dict:
    """Launch or explain Codex CLI login.

    The web app never asks for or stores ChatGPT/OpenAI credentials. Codex login is
    intentionally delegated to the local Codex CLI session. On Windows local/VDI
    machines this endpoint opens a separate terminal so the user can complete the
    secure OAuth/device-auth flow. On locked-down servers it returns the exact
    command to run manually.
    """
    mode = (mode or "device").strip().lower()
    codex_path = resolve_command("codex")
    log_event("ai_provider", f"Codex login requested ({mode})", status="running", progress=10)
    if codex_path is None:
        log_event("ai_provider", "Codex CLI not found", status="warning", progress=100)
        return {
            "ok": False,
            "message": "Codex CLI is not installed or not found in PATH.",
            "next_steps": [
                "Install Codex CLI using the client-approved method.",
                "Restart this GUI after installation so PATH is refreshed.",
                "Then click Launch Codex Login or run codex login manually."
            ],
            "commands": {
                "interactive": "codex login",
                "device": "codex login --device-auth",
                "status": "codex login status",
                "doctor": "codex doctor --json"
            }
        }

    fresh = True
    login_command = ["codex", "login"]
    if mode in {"device", "device-auth", "device_auth"}:
        login_command.append("--device-auth")
    command_text = "codex logout && " + " ".join(login_command)

    launched = False
    launch_error = ""
    # Fresh-login rule: always disconnect any existing Codex session first.
    # The GUI never collects credentials and never auto-connects on startup.
    try:
        if os.name == "nt":
            script = "CODEX_FRESH_DEVICE_AUTH_WINDOWS.cmd" if mode in {"device", "device-auth", "device_auth"} else "CODEX_FRESH_LOGIN_WINDOWS.cmd"
            script_path = REPO_ROOT / "scripts" / "ai" / script
            if script_path.exists():
                subprocess.Popen(f'start "AIQA Fresh Codex Login" cmd /k "{script_path}"', shell=True, cwd=str(REPO_ROOT))
            else:
                subprocess.Popen(f'start "AIQA Fresh Codex Login" cmd /k "codex logout && {" ".join(login_command)}"', shell=True, cwd=str(REPO_ROOT))
            launched = True
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"

    status = _provider_readiness()
    log_event("ai_provider", "Fresh Codex login flow prepared; previous Codex credentials will be removed before login.", status="ok" if launched else "warning", progress=100)
    record_action("codex_fresh_login", "started" if launched else "manual_required", "Fresh Codex login requested. Existing Codex session is disconnected first.", {"mode": mode, "command": command_text, "launched_terminal": launched, "launch_error": launch_error})
    return {
        "ok": True,
        "launched_terminal": launched,
        "fresh_login": fresh,
        "message": "Fresh Codex login was requested. Existing Codex credentials are disconnected first; then Codex opens its secure browser/device-auth flow.",
        "command": command_text,
        "launch_error": launch_error,
        "codex_status_after_request": status.get("codex", {}),
        "what_to_expect": [
            "A terminal should open and run: codex logout, then codex login/device-auth.",
            "Complete the Codex sign-in in the terminal/browser/device-auth flow.",
            "Return to this GUI and click Run Codex Doctor or Check Codex/Ollama status.",
            "In Hybrid VM+VDI mode, run fresh Codex login inside the VDI where Codex will patch files."
        ],
        "security_note": "The GUI never stores ChatGPT username/password or OpenAI API keys for Codex login."
    }


@app.post("/api/llm/codex/doctor")
async def api_codex_doctor() -> dict:
    log_event("ai_provider", "Codex doctor check started", status="running", progress=10)
    codex_path = resolve_command("codex")
    if codex_path is None:
        log_event("ai_provider", "Codex doctor failed: CLI not found", status="warning", progress=100)
        return {"ok": False, "message": "Codex CLI not found in PATH.", "command": "codex doctor --json"}
    result = run_command(["codex", "doctor", "--json"], cwd=REPO_ROOT, timeout=60)
    log_event("ai_provider", "Codex doctor check completed", status="ok" if result.ok else "warning", progress=100)
    return {
        "ok": result.ok,
        "message": "Codex doctor completed." if result.ok else "Codex doctor found issues.",
        "command": "codex doctor --json",
        "stdout": result.stdout,
        "stderr": result.stderr or result.error,
        "returncode": result.returncode,
    }


@app.get("/api/progress/events")
def api_progress_events(request: Request) -> dict:
    events = read_events(250)
    since_ms_raw = request.query_params.get("since_ms") or ""
    stage = request.query_params.get("stage") or ""
    try:
        since_ms = int(since_ms_raw) if since_ms_raw else 0
    except Exception:
        since_ms = 0
    if since_ms:
        events = [e for e in events if int(e.get("epoch_ms") or 0) >= since_ms]
    if stage:
        events = [e for e in events if str(e.get("stage") or "") == stage]
    # Return only recent events for this action when since_ms is provided. This prevents
    # old unrelated messages, such as previous Playwright execution, from appearing after
    # Check This Machine or Start Required Services.
    return {"ok": True, "events": events[-50:], "events_tail": events[-50:], "current": current_status(), "summary": write_runtime_summary()}


@app.get("/api/mcp/status")
def api_mcp_status() -> dict:
    return mcp_status(probe_server=False)


@app.post("/api/mcp/live-probe")
def api_mcp_live_probe(timeout_seconds: int = Form(60)) -> dict:
    """Explicitly run the slower live MCP package probe.

    The normal Prepare MCP action intentionally skips this probe so the GUI does
    not look stuck on slow VMs or corporate npm/proxy networks.
    """
    safe_timeout = max(10, min(int(timeout_seconds or 60), 180))
    log_event("existing_framework_mcp", "Running explicit Playwright MCP live probe. This can take time on first npm download or proxy networks.", progress=10, details={"timeout_seconds": safe_timeout})
    status = mcp_status(headless=False, probe_server=True, probe_timeout=safe_timeout)
    ok = bool(status.get("npx_available") and (status.get("mcp_probe_ok") is not False))
    log_event("existing_framework_mcp", status.get("probe_message") or "Explicit MCP live probe completed.", status="done" if ok else "warning", progress=100, details={"mcp_probe_ok": status.get("mcp_probe_ok")})
    return {"ok": ok, "stage": "mcp_live_probe_completed", "message": status.get("probe_message") or ("MCP live probe completed." if ok else "MCP live probe failed or timed out. Check npm/proxy/network output."), "mcp_status": status}


@app.post("/api/existing-framework/mcp/preflight")
async def api_existing_framework_mcp_preflight(
    framework_path: str = Form(""),
    project: str = Form("auto"),
    browser: str = Form("chromium"),
) -> JSONResponse:
    """Run MCP readiness preflight before starting Playwright MCP assist."""
    try:
        record_action("existing_framework_mcp_preflight", "running", "MCP readiness preflight started.", {"framework_path": framework_path, "project": project, "browser": browser})
        log_event("existing_framework_mcp", "MCP readiness preflight: checking package.json, build, test list and browser readiness.", progress=10, details={"framework_path": framework_path})
        report = run_mcp_readiness_preflight(framework_path=framework_path, project=project, browser=browser)
        log_event("existing_framework_mcp", report.get("message", "MCP readiness preflight completed."), status="ok" if report.get("ok") else "warning", progress=100, details={"stage": report.get("stage")})
        record_action("existing_framework_mcp_preflight", "done" if report.get("ok") else "warning", report.get("message", "MCP readiness preflight completed."), {"framework_path": framework_path, "report": report})
        return JSONResponse({"ok": bool(report.get("ok")), "stage": report.get("stage") or "mcp_readiness_preflight_completed", "mcp_preflight": report, "action_required": bool(report.get("action_required")), "message": report.get("recommended_user_message") or report.get("message") or "MCP readiness preflight completed.", "report_url": "/artifacts/reports/existing-framework/mcp-readiness-preflight.html"})
    except Exception as exc:
        msg = f"MCP readiness preflight failed safely: {type(exc).__name__}: {exc}"
        log_event("existing_framework_mcp", msg, status="error", progress=100)
        record_action("existing_framework_mcp_preflight", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "mcp_readiness_preflight_failed", "message": msg, "error": msg}, status_code=200)


@app.post("/api/existing-framework/mcp/fix-build-with-ai")
async def api_existing_framework_mcp_fix_build_with_ai(
    framework_path: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    project: str = Form("auto"),
    browser: str = Form("chromium"),
    human_instruction: str = Form(""),
) -> JSONResponse:
    """Use the selected AI provider to fix build/list blockers found by MCP readiness preflight. Codex is used only when selected; OpenAI/DeepSeek use API keys, not Codex login."""
    try:
        provider_confirmation = _confirmed_provider_connection(provider=provider, model=model, live_probe=True)
        if not provider_confirmation.get("ok"):
            msg = provider_confirmation.get("message") or "Selected AI provider is not backend-confirmed. Fix action was not started."
            log_event("existing_framework_mcp", msg, status="warning", progress=100, details={"provider": provider, "connection_status": provider_confirmation.get("connection_status")})
            return JSONResponse({
                "ok": False,
                "stage": "mcp_readiness_provider_not_confirmed",
                "message": msg,
                "confirmed_provider_connection": provider_confirmation,
                "next_actions": provider_confirmation.get("next_actions") or ["Validate the selected AI provider from Start Here > AI connection, then retry."],
            }, status_code=200)
        record_action("existing_framework_mcp_fix_build", "running", "AI fix for MCP readiness/build errors started with backend-confirmed provider.", {"framework_path": framework_path, "provider": provider, "provider_confirmation": provider_confirmation})
        log_event("existing_framework_mcp", "AI is fixing MCP readiness blockers before MCP assist using backend-confirmed provider.", progress=15, details={"framework_path": framework_path, "provider": provider, "connection_status": provider_confirmation.get("connection_status")})
        report = await run_in_threadpool(
            fix_mcp_preflight_build_errors_with_ai,
            framework_path=framework_path,
            provider=provider,
            model=model,
            project=project,
            browser=browser,
            human_instruction=human_instruction,
        )
        report["confirmed_provider_connection"] = provider_confirmation
        log_event("existing_framework_mcp", report.get("message", "AI MCP readiness fix completed."), status="ok" if report.get("ok") else "warning", progress=100)
        record_action("existing_framework_mcp_fix_build", "done" if report.get("ok") else "warning", report.get("message", "AI MCP readiness fix completed."), {"framework_path": framework_path, "report": report})
        return JSONResponse({"ok": bool(report.get("ok")), "stage": report.get("stage") or "mcp_readiness_ai_fix_completed", "mcp_ai_fix": report, "confirmed_provider_connection": provider_confirmation, "changed_files": report.get("changed_files") or [], "message": report.get("message", "AI MCP readiness fix completed."), "report_url": "/artifacts/reports/existing-framework/mcp-readiness-preflight.html"})
    except Exception as exc:
        msg = f"AI MCP readiness fix failed safely: {type(exc).__name__}: {exc}"
        log_event("existing_framework_mcp", msg, status="error", progress=100)
        record_action("existing_framework_mcp_fix_build", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "mcp_readiness_ai_fix_failed", "message": msg, "error": msg}, status_code=200)


@app.post("/api/existing-framework/mcp/full-control-fix")
async def api_existing_framework_mcp_full_control_fix(
    framework_path: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form(""),
    project: str = Form("auto"),
    browser: str = Form("chromium"),
    human_instruction: str = Form(""),
    max_rounds: int = Form(3),
    full_control_scope: str = Form("impacted_files_only"),
) -> JSONResponse:
    """Let the selected backend-confirmed AI provider take guarded full control of framework-level build fixes.

    The action creates backups, applies scope-limited patches, blocks skip/only/fixme, reruns build/list checks,
    and writes an auditable framework-local report.
    """
    try:
        provider_confirmation = _confirmed_provider_connection(provider=provider, model=model, live_probe=True)
        if not provider_confirmation.get("ok"):
            msg = provider_confirmation.get("message") or "Selected AI provider is not backend-confirmed. Full-control fix was not started."
            log_event("existing_framework_full_control_fix", msg, status="warning", progress=100, details={"provider": provider, "connection_status": provider_confirmation.get("connection_status")})
            return JSONResponse({
                "ok": False,
                "stage": "full_control_provider_not_confirmed",
                "message": msg,
                "confirmed_provider_connection": provider_confirmation,
                "next_actions": provider_confirmation.get("next_actions") or ["Validate the selected AI provider from Start Here > AI connection, then retry."],
            }, status_code=200)
        record_action("existing_framework_full_control_fix", "running", "AI full-control framework fix started with backend-confirmed provider.", {"framework_path": framework_path, "provider": provider, "scope": full_control_scope})
        log_event("existing_framework_full_control_fix", "AI full-control framework fix started: backup, patch, build, and validation loop.", progress=10, details={"framework_path": framework_path, "provider": provider, "scope": full_control_scope})
        report = await run_in_threadpool(
            ai_full_control_fix_framework_issues,
            framework_path=framework_path,
            provider=provider,
            model=model,
            project=project,
            browser=browser,
            human_instruction=human_instruction,
            max_rounds=max_rounds,
            full_control_scope=full_control_scope,
        )
        report["confirmed_provider_connection"] = provider_confirmation
        log_event("existing_framework_full_control_fix", report.get("message", "AI full-control framework fix completed."), status="ok" if report.get("ok") else "warning", progress=100, details={"changed_files": report.get("changed_files") or []})
        record_action("existing_framework_full_control_fix", "done" if report.get("ok") else "warning", report.get("message", "AI full-control framework fix completed."), {"framework_path": framework_path, "report": report})
        return JSONResponse({
            "ok": bool(report.get("ok")),
            "stage": report.get("stage") or "ai_full_control_framework_fix_completed",
            "full_control_fix": report,
            "confirmed_provider_connection": provider_confirmation,
            "changed_files": report.get("changed_files") or [],
            "message": report.get("message", "AI full-control framework fix completed."),
            "report_url": "/artifacts/reports/existing-framework/ai-full-control-framework-fix.html",
        })
    except Exception as exc:
        msg = f"AI full-control framework fix failed safely: {type(exc).__name__}: {exc}"
        log_event("existing_framework_full_control_fix", msg, status="error", progress=100)
        record_action("existing_framework_full_control_fix", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "ai_full_control_framework_fix_failed", "message": msg, "error": msg}, status_code=200)


@app.post("/api/existing-framework/mcp/prepare")
async def api_existing_framework_mcp_prepare(
    framework_path: str = Form(""),
    headed: bool = Form(True),
    project: str = Form("auto"),
    browser: str = Form("chromium"),
    mcp_preflight_decision: str = Form(""),
    mcp_prepare_mode: str = Form(""),
    mcp_live_probe: bool = Form(False),
) -> JSONResponse:
    """Prepare Microsoft Playwright MCP after a framework readiness preflight.

The preflight prevents a long/stuck MCP spinner when npm build/test-list/browser
readiness fails. If preflight fails, GUI can ask the user to fix with the selected AI provider,
continue MCP without build, or cancel.
    """
    try:
        prepare_mode = (mcp_prepare_mode or "").strip().lower()
        decision = (mcp_preflight_decision or "").strip().lower()
        fast_prepare_modes = {
            "fast_after_preflight",
            "fast_after_ai_fix",
            "fast_continue_without_build",
            "config_only",
        }
        record_action("existing_framework_mcp_prepare", "running", "Preparing Microsoft Playwright MCP assist for existing framework.", {"framework_path": framework_path, "headed": True, "decision": decision, "prepare_mode": prepare_mode})
        if prepare_mode in fast_prepare_modes:
            log_event("existing_framework_mcp", "Fast MCP prepare: validating framework path/package/npm/npx only and skipping duplicate build/list/browser checks.", progress=10, details={"framework_path": framework_path, "prepare_mode": prepare_mode})
            preflight = await run_in_threadpool(run_mcp_readiness_preflight, framework_path=framework_path, project=project, browser=browser, run_build=False, run_test_list=False, check_browser=False)
            preflight["fast_prepare_mode"] = prepare_mode
            preflight["duplicate_heavy_checks_skipped"] = True
            preflight["recommended_user_message"] = preflight.get("recommended_user_message") or "Fast MCP prepare mode is active. Heavy build/test-list/browser checks were already handled by the previous preflight/AI-fix step or intentionally skipped by user choice."
        else:
            log_event("existing_framework_mcp", "MCP readiness preflight started before MCP assist.", progress=5, details={"framework_path": framework_path})
            preflight = await run_in_threadpool(run_mcp_readiness_preflight, framework_path=framework_path, project=project, browser=browser)
        if not preflight.get("ok") and decision not in {"continue_without_build", "continue", "override"}:
            msg = preflight.get("recommended_user_message") or preflight.get("message") or "MCP readiness preflight requires action."
            log_event("existing_framework_mcp", msg, status="warning", progress=100, details={"stage": preflight.get("stage")})
            record_action("existing_framework_mcp_prepare", "warning", msg, {"framework_path": framework_path, "preflight": preflight})
            return JSONResponse({
                "ok": False,
                "stage": "mcp_preflight_action_required",
                "action_required": True,
                "mcp_preflight": preflight,
                "choices": ["fix_with_codex", "continue_without_build", "cancel"],
                "message": msg,
                "report_url": "/artifacts/reports/existing-framework/mcp-readiness-preflight.html",
            }, status_code=200)
        if decision in {"cancel", "deny"}:
            msg = "MCP assist was cancelled by user after readiness preflight. No file changes were made."
            record_action("existing_framework_mcp_prepare", "cancelled", msg, {"framework_path": framework_path, "preflight": preflight})
            return JSONResponse({"ok": False, "stage": "mcp_prepare_cancelled", "message": msg, "mcp_preflight": preflight}, status_code=200)

        log_event("existing_framework_mcp", "Preparing Playwright MCP visible-browser configuration.", progress=55, details={"framework_path": framework_path, "override": decision})
        files = write_playwright_mcp_configs(headless=False)
        log_event("existing_framework_mcp", "Writing MCP config and checking npm/npx. Live MCP package probe is skipped by default to avoid VM hangs.", progress=70, details={"live_probe_requested": bool(mcp_live_probe)})
        status = mcp_status(headless=False, probe_server=bool(mcp_live_probe))
        final_ok = bool(status.get("npx_available"))
        suffix = "" if preflight.get("ok") else " MCP was continued with user override even though readiness preflight still has warnings."
        if status.get("probe_skipped"):
            suffix += " Live MCP package probe was skipped to keep the VM GUI responsive."
        action_status = "done" if final_ok else "warning"
        record_action("existing_framework_mcp_prepare", action_status, "Microsoft Playwright MCP assist configuration prepared." + suffix, {"framework_path": framework_path, "status": status, "preflight": preflight, "prepare_mode": prepare_mode})
        log_event("existing_framework_mcp", "Playwright MCP assist configuration is ready." + suffix, status=action_status, progress=100)
        message = "Playwright MCP assist configuration is prepared quickly. Execution still uses Playwright Test for deterministic reports; MCP-style browser/accessibility evidence can be used by RCA/self-healing." + suffix
        return JSONResponse({"ok": final_ok, "stage": "existing_framework_mcp_ready", "config_files": files, "mcp_status": status, "mcp_preflight": preflight, "continued_with_preflight_override": bool(not preflight.get("ok")), "mcp_prepare_mode": prepare_mode or "standard", "message": message, "report_url": "/artifacts/reports/existing-framework/mcp-readiness-preflight.html", "next_actions": ["If you need to verify @playwright/mcp package download from this VM, run explicit MCP live probe.", "If npm/proxy is slow, keep live probe disabled and proceed with Playwright Test execution + MCP-style evidence collection."]})
    except Exception as exc:
        msg = f"Playwright MCP preparation failed safely: {type(exc).__name__}: {exc}"
        log_event("existing_framework_mcp", msg, status="error", progress=100)
        record_action("existing_framework_mcp_prepare", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "existing_framework_mcp_prepare_failed", "message": msg, "error": msg}, status_code=200)


@app.post("/api/existing-framework/mcp/locator-rca")
async def api_existing_framework_mcp_locator_rca(
    framework_path: str = Form(""),
    base_url: str = Form(""),
) -> JSONResponse:
    """Create an auditable MCP-assisted locator/actionability RCA chain.

The report follows the user's requested staged diagnosis: identify failed
locator, compare visible GUI/accessibility text, verify DOM/accessibility
presence, check actionability, and map the fix to POM/reuse files.
    """
    try:
        from qa_pipeline.agents.existing_framework_control.controller import _resolve_framework_path, _failure_text
        inventory = read_existing_failed_inventory()
        effective_framework_path = framework_path or inventory.get("framework_path", "")
        root = _resolve_framework_path(effective_framework_path)
        failure_text = _failure_text(inventory)
        payload = build_mcp_assisted_locator_rca(root, inventory, failure_text, base_url=_effective_base_url(base_url))
        element = payload.get("element_level_failure_identification") or {}
        msg = f"MCP element check completed: {element.get('failure_type', payload.get('category'))}. {element.get('plain_english', '')}".strip()
        record_action("existing_framework_mcp_locator_rca", "done", msg, {"framework_path": framework_path, "payload": payload})
        return JSONResponse({"ok": True, "stage": "existing_framework_mcp_locator_rca_completed", "mcp_assisted_locator_rca": payload, "mcp_assisted_locator_rca_url": "/artifacts/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html", "element_level_failure_identification": element, "significance": payload.get("significance"), "message": msg})
    except Exception as exc:
        msg = f"MCP-assisted locator RCA failed safely: {type(exc).__name__}: {exc}"
        log_event("existing_framework_mcp", msg, status="error", progress=100)
        record_action("existing_framework_mcp_locator_rca", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "existing_framework_mcp_locator_rca_failed", "message": msg, "error": msg}, status_code=200)


@app.get("/api/docker/status")
def api_docker_status() -> dict:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        log_event("host_runtime", "Host runtime status check started from Enterprise Stack", status="running", progress=10)
        data = host_runtime_status()
        log_event("host_runtime", "Host runtime status check completed", status="ok" if data.get("ok") else "warning", progress=100)
        return data
    log_event("docker", "Docker status check started", status="running", progress=10)
    data = docker_status()
    log_event("docker", "Docker status check completed", status="ok" if data.get("docker_available") else "warning", progress=100)
    return data


@app.post("/api/docker/start")
async def api_docker_start(
    include_ollama: bool = Form(False),
    include_gui: bool = Form(False),
    include_observability: bool = Form(False),
    include_mcp: bool = Form(False),
) -> JSONResponse:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        log_event("host_runtime", "Start Host Services requested from Enterprise Stack button", status="running", progress=10)
        data = start_host_services()
        log_event("host_runtime", "Start Host Services completed", status="ok" if data.get("ok", True) else "warning", progress=100)
        return JSONResponse(data)
    log_event("docker", "Docker stack start requested from GUI", status="running", progress=10)
    data = docker_start(include_ollama=include_ollama, include_gui=include_gui, include_observability=include_observability, include_mcp=include_mcp)
    log_event("docker", "Docker stack start completed", status="ok" if data.get("ok", True) else "warning", progress=100)
    return JSONResponse(data)


@app.post("/api/docker/stop")
async def api_docker_stop() -> JSONResponse:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        return JSONResponse(stop_host_services())
    return JSONResponse(docker_stop())


@app.post("/api/docker/pull")
async def api_docker_pull() -> JSONResponse:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        data = {"ok": True, "host_runtime_mode": True, "message": "No-Docker Host Runtime selected. No Docker images are required. Use Check No-Docker Readiness or Install Host Runtime instead.", "install_plan": host_install_plan()}
        log_event("host_runtime", "Docker image pull skipped because No-Docker Host Runtime is selected", status="ok", progress=100, details=data)
        return JSONResponse(data)
    log_event("docker", "Docker image pull requested from GUI", status="running", progress=10)
    data = docker_pull()
    log_event("docker", "Docker image pull completed", status="ok" if data.get("ok", True) else "warning", progress=100)
    return JSONResponse(data)


@app.get("/api/docker/readiness")
def api_docker_readiness() -> dict:
    return docker_status()


@app.post("/api/docker/logs")
async def api_docker_logs(service: str = Form(""), tail: int = Form(120)) -> JSONResponse:
    return JSONResponse(docker_logs(service=service, tail=tail))


@app.get("/api/prereq/readiness")
def api_prereq_readiness() -> dict:
    profile = read_runtime_profile()
    use_host = profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none"
    infra = host_runtime_status() if use_host else docker_status()
    ai = _provider_readiness()
    infra_ready = bool(infra.get("enterprise_ready") or infra.get("host_services_ready") or infra.get("ok"))
    return {
        "ok": infra_ready and bool(ai.get("provider_ready")),
        "runtime_engine": "host" if use_host else "docker",
        "docker_ready": False if use_host else bool(infra.get("enterprise_ready")),
        "host_ready": infra_ready if use_host else False,
        "ai_ready": bool(ai.get("provider_ready")),
        "blocking_reason": None if (infra_ready and ai.get("provider_ready")) else ("Start Host Services and connect AI provider." if use_host else "Start Docker stack and connect selected AI provider."),
        "docker": infra,
        "infra": infra,
        "ai": ai,
    }


@app.post("/api/ollama/ensure-model")
async def api_ollama_ensure_model(model: str = Form("llama3")) -> JSONResponse:
    result = ollama_ensure_model(model)
    # Recheck provider session after pulling.
    result["ai_session"] = _provider_readiness()
    return JSONResponse(result)


@app.get("/api/inventory")
def inventory() -> dict:
    return scan_framework().to_dict()


@app.post("/api/testcases/generate")
async def generate_functional_testcases(
    source_type: str = Form("jira"),
    feature: str = Form("login"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    pasted_text: str = Form(""),
    base_url: str = Form(""),
    source_file: Optional[UploadFile] = File(None),
    page_source_file: Optional[UploadFile] = File(None),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _require_project_base_url(base_url)
    log_event("testcase_generation", f"Starting functional testcase generation for {feature} from {source_type}", progress=5, feature=feature, source_type=source_type)
    # Keep GUI session state aligned when users upload testcase1, then testcase2 in the same session.
    save_project_config({**load_project_config(), "feature": feature, "source_type": source_type, "base_url": base_url, "provider": provider, "ollama_model": model})
    page_source_info = _save_optional_page_source(feature, page_source_file)
    source_path, normalized_path = _source_to_normalized(source_type, feature, pasted_text, source_file, base_url)
    deterministic_url_guard = sanitize_testcase_urls(normalized_path, base_url)
    try:
        ai_source_path, ai_meta = maybe_enhance_testcases_with_ai(normalized_path, provider, model, feature, base_url)
        ai_url_guard = sanitize_testcase_urls(ai_source_path, base_url)
        ai_meta["url_guard"] = {"deterministic": deterministic_url_guard, "ai": ai_url_guard}
    except Exception as exc:
        ai_source_path = normalized_path
        ai_meta = {
            "ai_used": False,
            "provider": provider,
            "ai_ok": False,
            "message": f"AI enhancement failed safely: {type(exc).__name__}: {exc}",
            "fallback": "Deterministic testcase JSON was used. Check Codex/Ollama status before retrying AI mode.",
            "url_guard": {"deterministic": deterministic_url_guard},
        }
    sanitize_testcase_urls(ai_source_path, base_url)
    testcase_path = ingest_source(ai_source_path, source_type, feature)
    testcase_json = read_json(testcase_path)
    testcase_md_path = testcase_path.with_name(testcase_path.name.replace('.scenarios.json', '.scenarios.md')) if testcase_path.name.endswith('.scenarios.json') else testcase_path.with_suffix('.md')
    testcase_md_preview = testcase_md_path.read_text(encoding='utf-8') if testcase_md_path.exists() else ''
    write_active_context({
        "channel": "uploaded_or_pasted_source",
        "source_type": source_type,
        "requested_feature": feature,
        "parent_feature": feature,
        "features": [feature],
        "testcase_paths": [_relative(testcase_path)],
        "source_file": _relative(source_path),
        "playwright_generated": False,
        "functional_testcases_reviewed": False,
        "review_gate": "waiting_for_user_review",
    })
    html_report_path = generate_enterprise_html_report()
    log_event("testcase_generation", f"Functional testcase generation completed for {feature}; waiting for user review", status="done", progress=100, feature=feature, source_type=source_type, details={"testcase_file": _relative(testcase_path)})
    return JSONResponse({
        "ok": True,
        "stage": "functional_testcases_generated",
        "source_uploaded": _relative(source_path),
        "deterministic_normalized_source": _relative(normalized_path),
        "testcase_generation_source": _relative(ai_source_path),
        "testcase_file": _relative(testcase_path),
        "testcase_markdown_file": _relative(testcase_md_path) if testcase_md_path.exists() else None,
        "functional_testcases_markdown_preview": testcase_md_preview,
        "functional_testcases": testcase_json,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "ai": ai_meta,
        "page_source": page_source_info,
        "next_step": "Review these generated functional testcases, then click Generate Playwright. Dynamic DOM crawling runs in the Generate Reusable Playwright step.",
    })


@app.post("/api/testcases/approve")
async def approve_functional_testcases() -> JSONResponse:
    ctx = read_active_context()
    if not ctx.get("active"):
        return JSONResponse({"ok": False, "error": "No active testcase source context found. Generate testcases from JIRA or Requirement Input first."})
    ctx["functional_testcases_reviewed"] = True
    ctx["review_gate"] = "approved_by_user_in_gui"
    write_active_context(ctx)
    log_event("testcase_review", "User approved functional testcases in GUI; Playwright generation is unlocked", status="done", progress=100, source_type=ctx.get("source_type", ""), details={"features": ctx.get("features", [])})
    return JSONResponse({"ok": True, "active_context": ctx, "next_step": "Go to Generated Playwright and click Generate Reusable Playwright."})


@app.post("/api/playwright/generate")
async def generate_playwright(
    source_type: str = Form("jira"),
    feature: str = Form("login"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _require_project_base_url(base_url)
    ctx_for_review = read_active_context()
    if ctx_for_review.get("active") and not ctx_for_review.get("functional_testcases_reviewed"):
        log_event("testcase_review", "Blocked Playwright generation because functional testcases are not approved yet", status="warning", progress=0, source_type=ctx_for_review.get("source_type", ""), details={"features": ctx_for_review.get("features", [])})
        raise HTTPException(status_code=409, detail="Please review and approve the Functional Testcases first. Open Functional Testcases and click 'Approve functional testcases and unlock Playwright'.")
    active_features = _active_features(feature, source_type)
    if active_features:
        payload = _generate_playwright_batch(active_features, read_active_context().get("source_type", source_type), provider, model, base_url, parent_feature=feature)
        return JSONResponse(payload)

    testcase_path = feature_testcase_path(source_type, feature)
    if not testcase_path.exists():
        raise HTTPException(status_code=400, detail=f"Functional testcase file not found for active source. Expected: {testcase_path}. If this came from Jira Epic, use JIRA -> Fetch Epic + Generate Testcases, then Generate Reusable Playwright.")
    sanitize_testcase_urls(testcase_path, base_url)
    testcase_json = read_json(testcase_path)
    page_source_report = analyze_page_source(feature=feature, base_url=base_url)
    crawl_report = crawl_dynamic_page(base_url=base_url, feature=feature, headed=False)
    app_profile = profile_application(feature=feature, base_url=base_url, use_mcp=True)
    try:
        ai_meta = _ai_codegen_message(provider, model, feature, source_type, testcase_json)
    except Exception as exc:
        ai_meta = {"provider": provider, "ai_ok": False, "message": f"AI codegen assistance failed safely: {type(exc).__name__}: {exc}"}
    generation = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
    spec_path = _generated_spec_path(feature)
    if spec_path.exists():
        _remember_latest_generation(feature, source_type, spec_path, testcase_path)
        write_active_context(_batch_manifest([feature], source_type, parent_feature=feature) | {"channel": "single_source", "playwright_generated": True})
    review = run_review(skip_npm=True)
    summary_path = generate_summary()
    html_report_path = generate_enterprise_html_report()
    payload = {
        "ok": review.get("ok", False),
        "stage": "playwright_generated",
        "generation_scope": "single_active_feature_only",
        "testcase_file": _relative(testcase_path),
        "generated_playwright_dir": _relative(GENERATED_PLAYWRIGHT_DIR),
        "created": [d.__dict__ for d in generation.created],
        "reused": [d.__dict__ for d in generation.reused],
        "files": generation.files,
        "spec_path": _relative(spec_path),
        "spec_exists": spec_path.exists(),
        "available_specs": _available_generated_specs(),
        "review": review,
        "summary": _relative(summary_path),
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "ai": ai_meta,
        "page_source": page_source_report,
        "crawl_report": crawl_report,
        "app_intelligence_profile": app_profile,
        "llm_message_preview": ai_meta.get("message", "")[-6000:],
        "active_context": read_active_context(),
    }
    payload.update(_playwright_preview(feature, source_type))
    return JSONResponse(payload)

@app.post("/api/review")
async def review_generated(skip_npm: bool = Form(True)) -> JSONResponse:
    review = run_review(skip_npm=skip_npm)
    html_report_path = generate_enterprise_html_report()
    return JSONResponse({
        "ok": review.get("ok", False),
        "stage": "static_review_completed",
        "review": review,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "message": "Static review checks folder structure, reusable framework rules, no inline locators in specs, and optionally TypeScript build.",
    })


@app.post("/api/execute")
async def execute_generated(
    feature: str = Form("login"),
    source_type: str = Form("srs"),
    project: str = Form("auto"),
    use_mcp: bool = Form(True),
    headed: bool = Form(True),
    base_url: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    execution_mode: str = Form("sequential"),
    shards: int = Form(4),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    log_event("playwright_execution", f"Starting Playwright execution for {feature}", progress=10, feature=feature, source_type=source_type, details={"headed": headed, "project": project})
    record_action("execute_generated_playwright", "running", f"Generated Playwright execution started in {'headed' if headed else 'headless'} mode for {feature}.", {"feature": feature, "headed": headed, "project": project})
    write_playwright_mcp_configs(headless=not headed)
    pending = _read_rca_failed_only_pending()
    if pending.get("active") and pending.get("failed_specs"):
        safe_shards = max(1, min(int(shards or 1), 20))
        requested_mode = (execution_mode or "sequential").strip().lower()
        log_event("playwright_execution", "RCA guard is active: Execute Generated Test was redirected to failed-only rerun, not full active-batch execution.", progress=12, status="warning", details=pending)
        result = execute_failed_only_after_healing(project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, execution_mode=requested_mode, shards=safe_shards)
        _clear_rca_failed_only_pending()
        html_report_path = generate_enterprise_html_report()
        return JSONResponse({
            "ok": result.get("ok", False),
            "stage": "rca_guard_failed_only_rerun_completed",
            "rerouted_from": "execute_generated_test",
            "reason": "self_healing_patch_pending_failed_only_validation",
            "failed_only": result,
            "failed_only_pending": pending,
            "html_report": _relative(html_report_path),
            "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
            "playwright_html_report_url": "/artifacts/reports/html/index.html",
            "failed_only_consolidated_report_url": result.get("failed_only_consolidated_report_url"),
            "archived_full_report_url": result.get("archived_full_report_url"),
            "message": "RCA guard prevented full rerun. Only the previously failed scripts were re-executed after the patch. Open the consolidated report for the complete original+rerun result matrix.",
        })
    active_features = _active_features(feature, source_type)
    if active_features:
        source_type = read_active_context().get("source_type", source_type)
        spec_precheck = _ensure_specs_for_features(active_features, source_type, provider, model, base_url, parent_feature=feature)
        if not spec_precheck.get("ok"):
            html_report_path = generate_enterprise_html_report()
            return JSONResponse({"ok": False, "stage": "active_batch_execution_precheck_failed", "error": "Could not generate every active batch spec.", "spec_precheck": spec_precheck, "html_report": _relative(html_report_path), "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html"})
        requested_mode = (execution_mode or "sequential").strip().lower()
        safe_shards = max(1, min(int(shards or 1), 20))
        if requested_mode == "distributed":
            execution = execute_feature_distributed(feature="active_batch", features=active_features, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, shards=safe_shards)
            execution_label = "Distributed"
        else:
            execution = execute_feature_sequential(feature="active_batch", features=active_features, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url)
            execution_label = "Sequential"
        log_event("playwright_execution", f"{execution_label} active-batch Playwright execution completed; report generation is finished", status="done" if execution.get("ok") else "warning", progress=100, details={"features": active_features, "ok": execution.get("ok"), "execution_mode": requested_mode, "shards": safe_shards})
        html_report_path = generate_enterprise_html_report()
        return JSONResponse({
            "ok": execution.get("ok", False),
            "stage": "active_batch_playwright_execution_completed",
            "generation_scope": "active_source_batch_only",
            "execution_mode_requested": requested_mode,
            "shards_requested": safe_shards,
            "active_context": read_active_context(),
            "spec_precheck": spec_precheck,
            "execution": execution,
            "mcp": execution.get("mcp"),
            "html_report": _relative(html_report_path),
            "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
            "playwright_html_report_url": "/artifacts/reports/html/index.html",
        })

    spec_precheck = _ensure_spec_exists_for_execution(feature, source_type, base_url)
    if not spec_precheck.get("ok"):
        html_report_path = generate_enterprise_html_report()
        return JSONResponse({
            "ok": False,
            "stage": "playwright_execution_precheck_failed",
            "error": spec_precheck.get("message"),
            "spec_precheck": spec_precheck,
            "html_report": _relative(html_report_path),
            "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
            "playwright_html_report_url": "/artifacts/reports/html/index.html",
        })
    requested_mode = (execution_mode or "sequential").strip().lower()
    safe_shards = max(1, min(int(shards or 1), 20))
    if requested_mode == "distributed":
        execution = execute_feature_distributed(feature=feature, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, shards=safe_shards)
    else:
        execution = execute_feature_sequential(feature=feature, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url)
    log_event("playwright_execution", f"Playwright execution completed for {feature}; report generation is finished", status="done" if execution.get("ok") else "warning", progress=100, feature=feature, source_type=source_type, details={"ok": execution.get("ok"), "execution_mode": requested_mode, "shards": safe_shards})
    failure_learning = None
    if not execution.get("ok"):
        failure_learning = record_failure(error=str(execution.get("stdout", "")) + "\n" + str(execution.get("stderr", "")) + "\n" + str(execution.get("error", "")), test_name=feature, category="execution_failure")
    html_report_path = generate_enterprise_html_report()
    payload = {
        "ok": execution.get("ok", False),
        "stage": "playwright_execution_completed",
        "execution_mode_requested": requested_mode,
        "shards_requested": safe_shards,
        "spec_precheck": spec_precheck,
        "active_context": read_active_context(),
        "execution": execution,
        "mcp": execution.get("mcp"),
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "failure_learning": failure_learning,
    }
    return JSONResponse(payload)


@app.post("/api/failure/analyze")
async def api_failure_analyze(
    feature: str = Form("login"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    report = analyze_failed_scripts_one_by_one(feature=feature, provider=provider, model=model, base_url=base_url)
    html_report_path = generate_enterprise_html_report()
    return JSONResponse({
        "ok": True,
        "stage": "root_cause_analysis_completed",
        "root_cause": report,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "message": "RCA completed one failed script at a time. Review the human-readable fix proposals before healing.",
    })


@app.post("/api/self-heal/propose")
async def api_self_heal_propose(
    feature: str = Form("login"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    report = run_self_healing(feature=feature, provider=provider, model=model, base_url=base_url, apply_patch=False)
    html_report_path = generate_enterprise_html_report()
    return JSONResponse({
        "ok": True,
        "stage": "self_healing_proposal_created",
        "self_healing": report,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "message": "Proposal created. No files were changed. Use Apply Self-Healing Patch only after reviewing the plan.",
    })


@app.post("/api/self-heal/apply")
async def api_self_heal_apply(
    feature: str = Form("login"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    report = run_self_healing(feature=feature, provider=provider, model=model, base_url=base_url, apply_patch=True)
    review = run_review(skip_npm=True)
    failed_only_pending = _write_rca_failed_only_pending("self_healing_patch_applied")
    html_report_path = generate_enterprise_html_report()
    payload = {
        "ok": bool(report.get("ok")) and bool(review.get("ok", True)),
        "stage": "self_healing_patch_applied",
        "self_healing": report,
        "review": review,
        "failed_only_pending": failed_only_pending,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "message": "Patch applied under strict rules. Next execution is guarded to run failed specs only. Use RCA & Self-Healing -> Re-run Failed Only to save time; run full regression only when explicitly needed.",
    }
    payload.update(_playwright_preview(feature, load_project_config().get("source_type", "jira")))
    return JSONResponse(payload)


@app.get("/api/failure/failed-inventory")
async def api_failed_inventory() -> JSONResponse:
    inventory = read_failed_test_inventory()
    return JSONResponse(inventory)




@app.get("/api/api-framework/docker/status")
def api_api_framework_docker_status() -> dict:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        data = host_runtime_readiness()
        data.update({"api_host_runtime": True, "message": "No-Docker Host Runtime selected. API execution will use local Node/npm or Java/Maven instead of Docker images."})
        log_event("api_host_runtime", "API host runtime check completed", status="ok" if data.get("ok") else "warning", progress=100, details=data)
        return data
    return api_docker_runtime_status()


@app.post("/api/api-framework/docker/pull")
async def api_api_framework_docker_pull() -> JSONResponse:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        return JSONResponse({"ok": True, "api_host_runtime": True, "message": "No Docker images required in Host Runtime. Use host install/readiness scripts for Node/Java/Maven."})
    return JSONResponse(api_docker_pull_images())


@app.post("/api/api-framework/docker/start-tools")
async def api_api_framework_docker_start_tools() -> JSONResponse:
    profile = read_runtime_profile()
    if profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none":
        return JSONResponse(start_host_services())
    return JSONResponse(api_docker_start_tools())



@app.post("/api/api-framework/generate")
async def api_api_framework_generate(
    feature: str = Form("api"),
    source_type: str = Form("srs"),
    flavor: str = Form("playwright"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    policy_mode: str = Form("approved_with_backup"),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = generate_api_framework(feature=feature, source_type=source_type, flavor=flavor, base_url=base_url, provider=provider, model=model)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_generated",
        "api_framework": report,
        "api_report_url": "/artifacts/reports/api-framework/api-framework-overview.html",
        "message": report.get("message", "API framework generated."),
    })


@app.post("/api/api-framework/analyze")
async def api_api_framework_analyze(
    framework_path: str = Form(""),
    flavor: str = Form("auto"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = analyze_api_framework(framework_path=framework_path, flavor=flavor, base_url=base_url)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_analyzed",
        "api_framework": report,
        "api_intelligence_url": "/artifacts/reports/api-framework/api-framework-intelligence.html",
        "message": report.get("message", "API framework analyzed and indexed."),
    })


@app.post("/api/api-framework/execute")
async def api_api_framework_execute(
    framework_path: str = Form(""),
    flavor: str = Form("auto"),
    base_url: str = Form(""),
    targets: str = Form(""),
    test_command: str = Form(""),
    use_docker: bool = Form(True),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    profile = read_runtime_profile()
    effective_use_docker = False if (profile.get("runtime_engine") == "host" or profile.get("docker_runtime") == "none") else use_docker
    report = execute_api_framework(framework_path=framework_path, flavor=flavor, base_url=base_url, targets=targets, test_command=test_command, auto_install=True, use_docker=effective_use_docker)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_execution_completed",
        "api_execution": report,
        "api_report_url": report.get("api_report_url") or "/artifacts/reports/api-framework/api-consolidated-report.html",
        "message": report.get("message", "API framework execution completed."),
    })


@app.post("/api/api-framework/failure/analyze")
async def api_api_framework_failure_analyze(
    framework_path: str = Form(""),
    flavor: str = Form("auto"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = analyze_api_failure(framework_path=framework_path, flavor=flavor, provider=provider, model=model, base_url=base_url)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_rca_completed",
        "api_root_cause": report,
        "api_rca_url": "/artifacts/reports/api-framework/api-root-cause-report.html",
        "message": report.get("message", "API RCA completed."),
    })


@app.post("/api/api-framework/self-heal/propose")
async def api_api_framework_self_heal_propose(
    framework_path: str = Form(""),
    flavor: str = Form("auto"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = self_heal_api_framework(framework_path=framework_path, flavor=flavor, provider=provider, model=model, base_url=base_url, apply_patch=False)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_self_healing_proposal_created",
        "api_self_healing": report,
        "api_healing_url": "/artifacts/reports/api-framework/api-self-healing-report.html",
        "message": report.get("message", "API self-healing proposal created."),
    })


@app.post("/api/api-framework/self-heal/apply")
async def api_api_framework_self_heal_apply(
    framework_path: str = Form(""),
    flavor: str = Form("auto"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = self_heal_api_framework(framework_path=framework_path, flavor=flavor, provider=provider, model=model, base_url=base_url, apply_patch=True)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "api_framework_self_healing_patch_step_completed",
        "api_self_healing": report,
        "api_healing_url": "/artifacts/reports/api-framework/api-self-healing-report.html",
        "message": report.get("message", "API self-healing patch step completed."),
    })


@app.post("/api/api-framework/rag-search")
async def api_api_framework_rag_search(
    query: str = Form("api request response schema auth endpoint payload testData"),
    top_k: int = Form(10),
) -> JSONResponse:
    report = search_api_framework_rag(query=query, top_k=top_k)
    return JSONResponse({"ok": bool(report.get("ok", True)), "stage": "api_framework_rag_search_completed", "api_rag_search": report, "message": "API RAG search completed."})


@app.get("/api/api-framework/failed-inventory")
def api_api_framework_failed_inventory() -> dict:
    return read_api_failed_inventory()

@app.post("/api/existing-framework/analyze")
async def api_existing_framework_analyze(
    framework_path: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = analyze_existing_framework(framework_path=framework_path, provider=provider, model=model, base_url=base_url)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "existing_framework_understood",
        "existing_framework": report,
        "playwright_html_report_url": "/artifacts/reports/existing-framework/html/index.html",
        "message": "Existing Playwright framework was analyzed. Requirement parsing, testcase generation and generated-script creation are bypassed for this flow.",
    })




@app.post("/api/existing-framework/deep-index")
async def api_existing_framework_deep_index(
    framework_path: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    report = analyze_existing_framework(framework_path=framework_path, provider=provider, model=model, base_url=base_url)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "existing_framework_deep_index_completed",
        "framework_intelligence": report,
        "framework_intelligence_v2_url": "/artifacts/reports/existing-framework/framework-intelligence-v2.html",
        "message": "Deep framework intelligence and local RAG index completed. Architecture, tech stack, trigger flows, backend/API/DB hints, test data, VDI/VPN hints, and reusable chunks are available to RCA/self-healing."
    })


@app.get("/api/existing-framework/intelligence-v2")
def api_existing_framework_intelligence_v2() -> dict:
    return read_existing_framework_intelligence_v2()


@app.post("/api/existing-framework/rag-search")
async def api_existing_framework_rag_search(
    query: str = Form(""),
    top_k: int = Form(10),
    framework_path: str = Form(""),
) -> JSONResponse:
    return JSONResponse({
        "stage": "existing_framework_rag_search_completed",
        "rag_search": search_existing_framework_rag(query=query, top_k=top_k, framework_path=framework_path),
        "message": "RAG search completed against the local framework chunk index."
    })


@app.post("/api/module2/existing/prepare-ai-rag")
async def module2_prepare_existing_ai_rag(
    framework_path: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    query: str = Form(""),
) -> JSONResponse:
    """User-friendly one-click framework learning for Module 2.

    This is intentionally safe/static: it understands the existing Playwright
    framework, writes RAG/intelligence artifacts, and stores the observable
    action in AI memory. It does not generate or modify scripts.
    """
    base_url = _effective_base_url(base_url)
    try:
        record_action("module2_prepare_existing_ai_rag", "running", "Advanced AI learning started for the existing Playwright framework.", {"framework_path": framework_path, "provider": provider})
        log_event("module2_existing_framework", "Step 1/3: Reading existing framework architecture.", progress=8, details={"framework_path": framework_path})
        intelligence = await run_in_threadpool(analyze_existing_framework, framework_path=framework_path, provider=provider, model=model, base_url=base_url)
        log_event("module2_existing_framework", "Step 2/3: Building Advanced RAG context for reuse, locators, pages and test flows.", progress=55, details={"ok": intelligence.get("ok")})
        rag = await run_in_threadpool(search_existing_framework_rag, query=query or "playwright pages pageObjects locators tests fixtures utilities", top_k=12, framework_path=framework_path)
        audit = intelligence.get("object_repository_locator_audit") or {}
        audit_summary = audit.get("human_summary") or "Object repository locator audit not available."
        log_event("module2_existing_framework", "Step 3/3: Framework learning completed and saved into AI memory. " + audit_summary, status="done" if intelligence.get("ok") else "warning", progress=100)
        record_action("module2_prepare_existing_ai_rag", "done" if intelligence.get("ok") else "warning", "Existing framework is understood and RAG context is ready for execution/RCA/self-healing. " + audit_summary, {"framework_path": framework_path, "intelligence": intelligence, "rag_preview": rag, "object_repository_locator_audit": audit})
        return JSONResponse({
            "ok": bool(intelligence.get("ok")),
            "stage": "module2_existing_framework_ai_rag_ready",
            "framework_intelligence": intelligence,
            "rag_search": rag,
            "object_repository_locator_audit": audit,
            "object_repository_locator_audit_url": audit.get("report_url") or "/artifacts/reports/existing-framework/object-repository-locator-audit.html",
            "message": "Framework learning completed. " + audit_summary + " You can now run all existing tests without generating a new script.",
        })
    except Exception as exc:
        msg = f"Framework learning failed: {type(exc).__name__}: {exc}"
        log_event("module2_existing_framework", msg, status="error", progress=100)
        record_action("module2_prepare_existing_ai_rag", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "module2_existing_framework_ai_rag_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/module2/existing/discover-tests")
async def module2_discover_existing_tests(
    framework_path: str = Form(""),
) -> JSONResponse:
    """Show exactly which existing Playwright tests will be executed."""
    try:
        payload = preview_existing_framework_tests(framework_path)
        record_action("module2_discover_existing_tests", "done" if payload.get("ok") else "warning", payload.get("message", "Existing test discovery completed."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Existing test discovery failed: {type(exc).__name__}: {exc}"
        log_event("module2_existing_framework", msg, status="error", progress=100, details={"framework_path": framework_path})
        record_action("module2_discover_existing_tests", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "module2_existing_test_discovery_failed", "error": msg, "message": msg}, status_code=200)




@app.post("/api/module2/existing/discover-selectable-tests")
async def module2_discover_selectable_existing_tests(
    framework_path: str = Form(""),
    module_folder: str = Form(""),
    include_text: str = Form(""),
    exclude_text: str = Form(""),
) -> JSONResponse:
    """Show all existing specs as selectable checkboxes with optional filters."""
    try:
        payload = preview_existing_framework_tests_for_selection(
            framework_path=framework_path,
            module_folder=module_folder,
            include_text=include_text,
            exclude_text=exclude_text,
        )
        record_action(
            "module2_discover_selectable_existing_tests",
            "done" if payload.get("ok") else "warning",
            payload.get("message", "Selectable existing test discovery completed."),
            {"framework_path": framework_path, "filters": payload.get("filters"), "selected_count": payload.get("selected_count")},
        )
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Selectable existing test discovery failed: {type(exc).__name__}: {exc}"
        log_event("module2_existing_framework", msg, status="error", progress=100, details={"framework_path": framework_path})
        record_action("module2_discover_selectable_existing_tests", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "module2_selectable_existing_test_discovery_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/module2/existing/run-selected")
async def module2_run_selected_existing_tests(
    framework_path: str = Form(""),
    selected_tests: str = Form(""),
    project: str = Form("auto"),
    headed: bool = Form(True),
    base_url: str = Form(""),
    execution_mode: str = Form("sequential"),
    test_command: str = Form(""),
    advanced_ai_mode: bool = Form(True),
) -> JSONResponse:
    """Run only user-selected existing Playwright spec files."""
    base_url = _effective_base_url(base_url)
    headed = bool(headed)
    try:
        selected_list = [x.strip() for x in re.split(r"[,\n]+", selected_tests or "") if x.strip()]
        record_action(
            "module2_run_selected_existing_tests",
            "running",
            f"Running {len(selected_list)} user-selected existing Playwright test script(s) in {'headed/visible-browser' if headed else 'headless'} mode.",
            {"framework_path": framework_path, "selected_tests": selected_list, "headed": headed},
        )
        result = execute_selected_existing_framework_tests(
            framework_path=framework_path,
            selected_tests=selected_tests,
            project=project,
            headed=headed,
            base_url=base_url,
            execution_mode=execution_mode,
            test_command=test_command,
            use_mcp_assist=advanced_ai_mode,
        )
        record_action(
            "module2_run_selected_existing_tests",
            "done" if result.get("ok") else "warning",
            result.get("message", "Selected existing Playwright tests completed."),
            {"framework_path": framework_path, "result": result},
        )
        return JSONResponse(result)
    except Exception as exc:
        msg = f"Run selected existing tests failed: {type(exc).__name__}: {exc}"
        log_event("module2_existing_framework", msg, status="error", progress=100, details={"framework_path": framework_path})
        record_action("module2_run_selected_existing_tests", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "module2_selected_existing_tests_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/module2/distributed/plan")
async def module2_distributed_plan(
    framework_path: str = Form(""),
    selected_tests: str = Form(""),
    distributed_browsers: str = Form("chromium,firefox,webkit,msedge,chrome"),
    distributed_shard_count: int = Form(5),
    distributed_tests_per_shard: int = Form(0),
    distributed_agent_ids: str = Form(""),
    execution_target_mode: str = Form("central_and_workers"),
    include_master_worker: bool = Form(True),
    master_worker_name: str = Form("Central-VM-Worker"),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    centralize_reports_and_ai_memory: bool = Form(True),
    execution_provider: str = Form('local_vm'),
    browserstack_local: str = Form('true'),
) -> JSONResponse:
    from qa_pipeline.core.distributed_history import create_distributed_plan
    try:
        if str(execution_provider).lower() == 'browserstack':
            execution_target_mode = 'browserstack_cloud'
            os.environ['ASTRAHEAL_BROWSERSTACK_LOCAL'] = str(browserstack_local or 'true')
        payload = create_distributed_plan(framework_path, selected_tests, distributed_browsers, distributed_shard_count, distributed_agent_ids, worker_workspace_mode, central_shared_framework_path, bool(centralize_reports_and_ai_memory), execution_target_mode, master_worker_name, tests_per_shard=distributed_tests_per_shard)
        record_action("module2_distributed_plan", "done" if payload.get("ok") else "warning", payload.get("message", "Distributed plan created."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Distributed plan failed: {type(exc).__name__}: {exc}"
        log_event("distributed_execution", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "distributed_plan_failed", "error": msg, "message": msg}, status_code=200)

@app.post("/api/module2/distributed/run")
async def module2_distributed_run(
    framework_path: str = Form(""),
    selected_tests: str = Form(""),
    distributed_browsers: str = Form("chromium,firefox,webkit,msedge,chrome"),
    distributed_shard_count: int = Form(5),
    distributed_tests_per_shard: int = Form(0),
    distributed_agent_ids: str = Form(""),
    execution_target_mode: str = Form("central_and_workers"),
    include_master_worker: bool = Form(True),
    master_worker_name: str = Form("Central-VM-Worker"),
    run_on_agents: str = Form("true"),
    headed: bool = Form(True),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    centralize_reports_and_ai_memory: bool = Form(True),
    execution_provider: str = Form('local_vm'),
    browserstack_local: str = Form('true'),
) -> JSONResponse:
    from qa_pipeline.core.distributed_history import run_distributed_plan
    try:
        if str(execution_provider).lower() == 'browserstack':
            execution_target_mode = 'browserstack_cloud'
            os.environ['ASTRAHEAL_BROWSERSTACK_LOCAL'] = str(browserstack_local or 'true')
        # Run the long Playwright/distributed execution in a worker thread so
        # the FastAPI event loop can still serve /distributed/status polling.
        # This is what makes the GUI runtime test-case counter update live
        # below the progress bar instead of only after the run finishes.
        payload = await run_in_threadpool(
            run_distributed_plan,
            framework_path,
            selected_tests,
            distributed_browsers,
            distributed_shard_count,
            distributed_agent_ids,
            headed=bool(headed),
            run_on_agents=str(run_on_agents).lower() not in {"false", "0", "no"},
            worker_workspace_mode=worker_workspace_mode,
            central_shared_framework_path=central_shared_framework_path,
            centralize_reports_and_ai_memory=bool(centralize_reports_and_ai_memory),
            execution_target_mode=execution_target_mode,
            master_worker_name=master_worker_name,
            tests_per_shard=distributed_tests_per_shard,
        )
        record_action("module2_distributed_run", "done" if payload.get("ok") else "warning", payload.get("message", "Distributed run launched."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Distributed run failed: {type(exc).__name__}: {exc}"
        log_event("distributed_execution", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "distributed_run_failed", "error": msg, "message": msg}, status_code=200)



@app.post("/api/browserstack/readiness")
async def browserstack_readiness(framework_path: str = Form("")) -> JSONResponse:
    from qa_pipeline.core.browserstack_adapter import check_browserstack_readiness
    try:
        payload = check_browserstack_readiness(framework_path)
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"BrowserStack readiness failed: {type(exc).__name__}: {exc}"
        log_event("browserstack_execution", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "browserstack_readiness_failed", "error": msg, "message": msg}, status_code=200)

@app.post("/api/module2/distributed/status")
async def module2_distributed_status(
    framework_path: str = Form(""),
    run_id: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.core.distributed_history import get_distributed_run_status
    try:
        payload = get_distributed_run_status(framework_path, run_id)
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Distributed status failed: {type(exc).__name__}: {exc}"
        log_event("distributed_execution", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "distributed_status_failed", "error": msg, "message": msg}, status_code=200)




@app.post("/api/module2/heavy-lifting/plan")
async def module2_ai_heavy_lifting_plan(
    framework_path: str = Form(""),
    base_url: str = Form(""),
    provider: str = Form("codex"),
    reasoning_provider: str = Form("openai"),
    fallback_provider: str = Form("deepseek"),
    execution_target_mode: str = Form("central_and_workers"),
    include_master_worker: bool = Form(True),
    distributed_agent_ids: str = Form(""),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    dom_crawl_mode: str = Form("worker_mcp_when_aut_access_requires_worker"),
    mcp_evidence_mode: str = Form("collect_on_execution_worker_send_to_central"),
    ai_patch_location: str = Form("central_only"),
) -> JSONResponse:
    try:
        payload = build_ai_heavy_lifting_plan(
            framework_path=framework_path,
            base_url=_effective_base_url(base_url),
            primary_provider=provider,
            reasoning_provider=reasoning_provider,
            fallback_provider=fallback_provider,
            execution_target_mode=execution_target_mode,
            include_master_worker=bool(include_master_worker),
            distributed_agent_ids=distributed_agent_ids,
            worker_workspace_mode=worker_workspace_mode,
            central_shared_framework_path=central_shared_framework_path,
            dom_crawl_mode=dom_crawl_mode,
            mcp_evidence_mode=mcp_evidence_mode,
            ai_patch_location=ai_patch_location,
        )
        record_action("module2_ai_heavy_lifting_plan", "done" if payload.get("ok") else "warning", payload.get("message", "AI heavy lifting plan created."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"AI heavy lifting plan failed: {type(exc).__name__}: {exc}"
        log_event("ai_heavy_lifting", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "ai_heavy_lifting_plan_failed", "error": msg, "message": msg}, status_code=200)


@app.get("/api/module2/framework-artifact/heavy-lifting-plan")
async def module2_framework_ai_heavy_lifting_plan_report(request: Request):
    framework_path = str(request.query_params.get("framework_path") or "").strip()
    try:
        report = get_ai_heavy_lifting_report_path(framework_path)
        if report.exists() and report.is_file():
            return FileResponse(str(report), media_type="text/html")
        return JSONResponse({"ok": False, "message": f"AI heavy lifting report not found at {report}. Generate the plan first.", "framework_report_path": str(report)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"Could not open AI heavy lifting report: {type(exc).__name__}: {exc}"}, status_code=500)

@app.post("/api/module2/agentic-nodehub/plan")
async def module2_agentic_nodehub_plan(
    framework_path: str = Form(""),
    selected_tests: str = Form(""),
    distributed_browsers: str = Form("chromium"),
    distributed_shard_count: int = Form(5),
    distributed_agent_ids: str = Form(""),
    execution_target_mode: str = Form("central_and_workers"),
    include_master_worker: bool = Form(True),
    master_worker_name: str = Form("Central-VM-Worker"),
    worker_test_allocation: str = Form(""),
    immediate_rerun_attempts: int = Form(1),
    auto_apply_fixes: bool = Form(True),
    provider: str = Form("codex"),
    policy_mode: str = Form("approved_with_backup"),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    centralize_reports_and_ai_memory: bool = Form(True),
    ai_heavy_lifting_mode: str = Form("central_brain_worker_evidence"),
    worker_ai_role: str = Form("browser_mcp_evidence_only"),
    codex_patch_location: str = Form("central_only"),
) -> JSONResponse:
    from qa_pipeline.core.agentic_nodehub import create_agentic_nodehub_plan
    try:
        payload = create_agentic_nodehub_plan(
            framework_path=framework_path,
            selected_tests=selected_tests,
            browsers=distributed_browsers,
            shard_count=distributed_shard_count,
            agent_ids=distributed_agent_ids,
            include_master_worker=bool(include_master_worker),
            master_worker_name=master_worker_name,
            worker_test_allocation=worker_test_allocation,
            execution_target_mode=execution_target_mode,
            immediate_rerun_attempts=immediate_rerun_attempts,
            auto_apply_fixes=bool(auto_apply_fixes),
            ai_provider=provider,
            policy_mode=policy_mode,
            worker_workspace_mode=worker_workspace_mode,
            central_shared_framework_path=central_shared_framework_path,
            centralize_reports_and_ai_memory=bool(centralize_reports_and_ai_memory),
            ai_heavy_lifting_mode=ai_heavy_lifting_mode,
            worker_ai_role=worker_ai_role,
            codex_patch_location=codex_patch_location,
        )
        record_action("module2_agentic_nodehub_plan", "done" if payload.get("ok") else "warning", payload.get("message", "Agentic node-hub plan created."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Agentic node-hub plan failed: {type(exc).__name__}: {exc}"
        log_event("agentic_nodehub", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "agentic_nodehub_plan_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/module2/agentic-nodehub/run")
async def module2_agentic_nodehub_run(
    framework_path: str = Form(""),
    selected_tests: str = Form(""),
    distributed_browsers: str = Form("chromium"),
    distributed_shard_count: int = Form(5),
    distributed_agent_ids: str = Form(""),
    execution_target_mode: str = Form("central_and_workers"),
    include_master_worker: bool = Form(True),
    master_worker_name: str = Form("Central-VM-Worker"),
    worker_test_allocation: str = Form(""),
    immediate_rerun_attempts: int = Form(1),
    auto_apply_fixes: bool = Form(True),
    run_on_agents: str = Form("true"),
    headed: bool = Form(True),
    provider: str = Form("codex"),
    policy_mode: str = Form("approved_with_backup"),
    base_url: str = Form(""),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    centralize_reports_and_ai_memory: bool = Form(True),
    ai_heavy_lifting_mode: str = Form("central_brain_worker_evidence"),
    worker_ai_role: str = Form("browser_mcp_evidence_only"),
    codex_patch_location: str = Form("central_only"),
) -> JSONResponse:
    from qa_pipeline.core.agentic_nodehub import run_agentic_nodehub
    try:
        payload = run_agentic_nodehub(
            framework_path=framework_path,
            selected_tests=selected_tests,
            browsers=distributed_browsers,
            shard_count=distributed_shard_count,
            agent_ids=distributed_agent_ids,
            include_master_worker=bool(include_master_worker),
            master_worker_name=master_worker_name,
            worker_test_allocation=worker_test_allocation,
            execution_target_mode=execution_target_mode,
            immediate_rerun_attempts=immediate_rerun_attempts,
            auto_apply_fixes=bool(auto_apply_fixes),
            ai_provider=provider,
            policy_mode=policy_mode,
            headed=bool(headed),
            run_on_agents=str(run_on_agents).lower() not in {"false", "0", "no"},
            base_url=_effective_base_url(base_url),
            worker_workspace_mode=worker_workspace_mode,
            central_shared_framework_path=central_shared_framework_path,
            centralize_reports_and_ai_memory=bool(centralize_reports_and_ai_memory),
            ai_heavy_lifting_mode=ai_heavy_lifting_mode,
            worker_ai_role=worker_ai_role,
            codex_patch_location=codex_patch_location,
        )
        record_action("module2_agentic_nodehub_run", "done" if payload.get("ok") else "warning", payload.get("message", "Agentic node-hub run launched."), {"framework_path": framework_path, "payload": payload})
        return JSONResponse(payload)
    except Exception as exc:
        msg = f"Agentic node-hub run failed: {type(exc).__name__}: {exc}"
        log_event("agentic_nodehub", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "agentic_nodehub_run_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/module2/agentic-nodehub/status")
async def module2_agentic_nodehub_status(
    framework_path: str = Form(""),
    run_id: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.core.agentic_nodehub import get_agentic_nodehub_status
    try:
        return JSONResponse(get_agentic_nodehub_status(framework_path, run_id))
    except Exception as exc:
        msg = f"Agentic node-hub status failed: {type(exc).__name__}: {exc}"
        log_event("agentic_nodehub", msg, status="error", progress=100)
        return JSONResponse({"ok": False, "stage": "agentic_nodehub_status_failed", "error": msg, "message": msg}, status_code=200)

@app.get("/api/module2/framework-artifact/distributed-report")
async def module2_framework_distributed_report(request: Request):
    """Serve the distributed report from the external Playwright framework.

    The framework path is provided by the user in the GUI. We only serve the known
    report file under <framework>/.aiqa-history/reports/ to avoid exposing arbitrary
    files from the machine.
    """
    framework_path = str(request.query_params.get("framework_path") or "").strip()
    if not framework_path:
        return JSONResponse({"ok": False, "message": "framework_path is required. Run distributed execution first or enter the existing framework path."}, status_code=404)
    try:
        from qa_pipeline.core.distributed_history import get_framework_distributed_report_path
        report = get_framework_distributed_report_path(framework_path)
        if report.exists() and report.is_file():
            return _safe_report_file_response(report, source="framework_distributed_report")
        return JSONResponse({"ok": False, "message": f"Framework-local distributed report not found at {report}. Run distributed execution first.", "framework_report_path": str(report)}, headers=_report_no_cache_headers(), status_code=404)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"Could not open framework-local distributed report: {type(exc).__name__}: {exc}"}, status_code=500)




def _report_no_cache_headers(extra: dict | None = None) -> dict:
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if extra:
        headers.update({str(k): str(v) for k, v in extra.items()})
    return headers


def _report_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.exists() and path.is_file() else 0.0
    except Exception:
        return 0.0


def _safe_report_file_response(path: Path, *, source: str = "") -> FileResponse:
    headers = _report_no_cache_headers({"X-AstraHeal-Report-Source": source or str(path), "X-AstraHeal-Report-MTime": str(_report_mtime(path))})
    return FileResponse(str(path), media_type="text/html", headers=headers)


def _read_json_file_safely(path: Path) -> dict:
    try:
        if path.exists() and path.is_file():
            import json as _json
            return _json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return {}


def _latest_existing_framework_report_candidates(framework_path: str) -> list[dict]:
    """Return Playwright-report candidates ordered by freshness, not by legacy path.

    A previous bug opened stale reports because the endpoint checked
    <framework>/reports/existing-framework/html/index.html before the freshly
    generated local/VM distributed landing page.  We now choose by latest modified
    time and mark the source in response headers.
    """
    candidates: list[dict] = []

    def add(path: Path, source: str, priority: int = 0) -> None:
        try:
            if path.exists() and path.is_file():
                candidates.append({"path": path, "source": source, "mtime": _report_mtime(path), "priority": priority})
        except Exception:
            pass

    central_dir = GENERATED_PLAYWRIGHT_DIR / "reports" / "existing-framework"
    # Current AstraHeal-controlled Playwright entry points.  Do not route the
    # Open Playwright Report button to the combined business matrix; that has a
    # separate button.  The router/first-run/failed-only pages point to the exact
    # native shard or rerun HTML reports for the latest execution stage.
    add(central_dir / "latest-playwright-report.html", "central_latest_playwright_router", 80)
    add(central_dir / "failed-only-latest-playwright-report.html", "central_latest_failed_only_playwright_report", 75)
    add(central_dir / "first-run-playwright-report.html", "central_exact_first_run_playwright_report", 70)
    add(central_dir / "html" / "index.html", "central_latest_native_playwright_html", 55)
    add(central_dir / "distributed-execution-report.html", "central_latest_distributed_report", 45)

    if framework_path:
        try:
            root = Path(framework_path).expanduser().resolve()
            local_reports = root / ".aiqa-history" / "reports"
            add(local_reports / "distributed-execution-report.html", "framework_latest_distributed_report", 48)
            # Native single-machine Playwright reports are valid, but they can be
            # stale after Local/VM parallel runs. They are included and sorted by
            # freshness instead of being opened first unconditionally.
            add(root / "reports" / "existing-framework" / "html" / "index.html", "framework_native_existing_report", 30)
            add(root / "playwright-report" / "index.html", "framework_default_playwright_report", 20)
        except Exception:
            pass

    # Prefer the newest file.  Priority is used only as a deterministic tie-breaker.
    candidates.sort(key=lambda x: (float(x.get("mtime") or 0), int(x.get("priority") or 0)), reverse=True)
    return candidates


@app.get("/api/module2/framework-artifact/playwright-report")
async def module2_framework_playwright_report(request: Request):
    """Open the latest available Playwright report without 404s or stale-cache reuse.

    Normal single-machine runs copy the native report into generated-playwright.
    Local/VM parallel and VM worker runs keep native reports per shard and create a
    central landing page at the legacy static location.  The endpoint now chooses
    the newest report artifact instead of always opening the first legacy path.
    """
    framework_path = str(request.query_params.get("framework_path") or "").strip()
    candidates = _latest_existing_framework_report_candidates(framework_path)
    if candidates:
        chosen = candidates[0]
        return _safe_report_file_response(Path(chosen["path"]), source=str(chosen.get("source") or "latest_report"))
    return JSONResponse(
        {
            "ok": False,
            "message": "No Playwright report is available yet. Run tests first, then open this report again.",
            "checked": [str(c.get("path")) for c in candidates],
        },
        headers=_report_no_cache_headers(),
        status_code=404,
    )


@app.get("/api/module2/framework-artifact/combined-report")
async def module2_framework_combined_report(request: Request):
    """Open only the first-run + failed-only rerun business matrix.

    This endpoint intentionally does not fall back to distributed-execution-report.html.
    The Logs & Reports button must never show a shard execution report when the
    user asked for the combined first-run + rerun matrix.
    """
    central_dir = GENERATED_PLAYWRIGHT_DIR / "reports" / "existing-framework"
    path = central_dir / "consolidated-report.html"
    if path.exists():
        return _safe_report_file_response(path, source="combined_first_run_rerun_report")
    return JSONResponse({"ok": False, "message": "Combined first-run + rerun report is not available yet. Run the first execution first, then rerun failed tests to append rerun columns.", "expected_path": str(path)}, headers=_report_no_cache_headers(), status_code=404)


@app.get("/api/module2/framework-artifact/report-manifest")
async def module2_framework_report_manifest(request: Request):
    central_dir = GENERATED_PLAYWRIGHT_DIR / "reports" / "existing-framework"
    path = central_dir / "report-link-manifest.json"
    data = _read_json_file_safely(path)
    if not data:
        data = {"ok": False, "message": "No report manifest exists yet. Run tests first.", "expected_path": str(path)}
    return JSONResponse(data, headers=_report_no_cache_headers())


@app.get("/api/module2/framework-artifact/distributed-shard-report")
async def module2_framework_distributed_shard_report(request: Request):
    framework_path = str(request.query_params.get("framework_path") or "").strip()
    run_id = str(request.query_params.get("run_id") or "").strip()
    shard_id = str(request.query_params.get("shard_id") or "").strip()
    if not framework_path or not run_id or not shard_id:
        return JSONResponse({"ok": False, "message": "framework_path, run_id and shard_id are required."}, status_code=404)
    try:
        root = Path(framework_path).expanduser().resolve()
        safe_run = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        safe_shard = "".join(ch for ch in shard_id if ch.isalnum() or ch in "-_")
        base = (root / "reports" / "existing-framework" / "distributed-runs").resolve()
        report = (base / safe_run / safe_shard / "html" / "index.html").resolve()
        if base not in report.parents:
            return JSONResponse({"ok": False, "message": "Invalid shard report path."}, status_code=400)
        if report.exists() and report.is_file():
            return _safe_report_file_response(report, source="distributed_shard_native_report")
        return JSONResponse({"ok": False, "message": f"Shard Playwright report not found at {report}. The shard may still be running or Playwright may not have generated HTML.", "shard_report_path": str(report)}, headers=_report_no_cache_headers(), status_code=404)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"Could not open shard Playwright report: {type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/api/module2/framework-artifact/agentic-nodehub-report")
async def module2_framework_agentic_nodehub_report(request: Request):
    framework_path = str(request.query_params.get("framework_path") or "").strip()
    if not framework_path:
        return JSONResponse({"ok": False, "message": "framework_path is required."}, status_code=404)
    try:
        report = Path(framework_path).expanduser().resolve() / ".aiqa-history" / "reports" / "agentic-nodehub-report.html"
        if report.exists() and report.is_file():
            return _safe_report_file_response(report, source="agentic_nodehub_report")
        return JSONResponse({"ok": False, "message": f"Framework-local agentic node-hub report not found at {report}. Run agentic node-hub execution first.", "framework_report_path": str(report)}, headers=_report_no_cache_headers(), status_code=404)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"Could not open framework-local agentic node-hub report: {type(exc).__name__}: {exc}"}, status_code=500)


@app.post("/api/module2/history/list")
async def module2_history_list(
    framework_path: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.core.distributed_history import list_framework_history
    return JSONResponse(list_framework_history(framework_path))

@app.post("/api/module2/existing/run-all")
async def module2_run_all_existing_tests(
    framework_path: str = Form(""),
    project: str = Form("auto"),
    headed: bool = Form(True),
    base_url: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    execution_mode: str = Form("sequential"),
    advanced_ai_mode: bool = Form(True),
) -> JSONResponse:
    """Run all tests from the existing framework without requiring new script generation.

    This endpoint is the main Module 2 workflow for already-generated/client-owned
    Playwright frameworks. It always clears target/spec filters and custom commands
    so Playwright executes the whole framework scope.
    """
    base_url = _effective_base_url(base_url)
    # Headed/headless is selected by the user in the GUI. Default is headed, but
    # headless is also available for CI-style runs.
    headed = bool(headed)
    try:
        record_action("module2_run_all_existing_tests", "running", f"Run All Existing Tests started in {'headed/visible-browser' if headed else 'headless'} mode.", {"framework_path": framework_path, "advanced_ai_mode": advanced_ai_mode, "headed": headed})
        log_event("module2_existing_framework", "Step 1/4: Preparing Advanced RAG and framework understanding before execution.", progress=5, details={"framework_path": framework_path})
        intelligence = analyze_existing_framework(framework_path=framework_path, provider=provider if advanced_ai_mode else "deterministic", model=model, base_url=base_url)
        log_event("module2_existing_framework", "Step 2/4: Running every Playwright test from the existing framework. No new script generation is required.", progress=22, details={"headed": headed, "project": project})
        result = execute_existing_framework(
            framework_path=framework_path,
            project=project,
            headed=headed,
            base_url=base_url,
            execution_mode=execution_mode,
            shards=1,
            targets="",
            test_command="",
            auto_install=True,
            use_mcp_assist=True,
        )
        failed_count = ((result.get("failed_test_inventory") or {}).get("failed_count") if isinstance(result, dict) else None) or 0
        status = "done" if result.get("ok") else "warning"
        log_event("module2_existing_framework", f"Step 3/4: Existing test run completed. Failed tests found: {failed_count}.", status=status, progress=92, details={"failed_count": failed_count})
        record_action("module2_run_all_existing_tests", status, result.get("message", "Existing framework run completed."), {"framework_path": framework_path, "execution": result, "framework_intelligence": intelligence})
        log_event("module2_existing_framework", "Step 4/4: Results and execution history saved for RCA/self-healing memory.", status="done" if result.get("ok") else "warning", progress=100)
        return JSONResponse({
            "ok": bool(result.get("ok")),
            "stage": "module2_existing_framework_all_tests_completed",
            "framework_intelligence": intelligence,
            "existing_framework_execution": result,
            "playwright_html_report_url": result.get("playwright_html_report_url") or "/artifacts/reports/existing-framework/html/index.html",
            "message": "All existing framework tests were executed. If failures exist, click 'Explain failed tests' and then 'Fix failed tests safely'.",
        })
    except Exception as exc:
        msg = f"Run All Existing Tests failed: {type(exc).__name__}: {exc}"
        log_event("module2_existing_framework", msg, status="error", progress=100, details={"framework_path": framework_path})
        record_action("module2_run_all_existing_tests", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "module2_existing_framework_all_tests_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/existing-framework/execute")
async def api_existing_framework_execute(
    framework_path: str = Form(""),
    project: str = Form("auto"),
    headed: bool = Form(True),
    base_url: str = Form(""),
    execution_mode: str = Form("sequential"),
    shards: int = Form(1),
    targets: str = Form(""),
    test_command: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    headed = bool(headed)
    try:
        record_action("execute_existing_framework", "running", f"Existing framework execution started in {'headed/visible-browser' if headed else 'headless'} mode.", {"framework_path": framework_path, "headed": headed, "targets": targets})
        result = execute_existing_framework(
            framework_path=framework_path,
            project=project,
            headed=headed,
            base_url=base_url,
            execution_mode=execution_mode,
            shards=shards,
            targets=targets,
            test_command=test_command,
            auto_install=True,
            use_mcp_assist=True,
        )
        record_action("execute_existing_framework", "done" if result.get("ok") else "warning", result.get("message", "Existing framework execution completed."), {"framework_path": framework_path, "result": result})
        return JSONResponse({
            "ok": bool(result.get("ok")),
            "stage": "existing_framework_execution_completed",
            "existing_framework_execution": result,
            "playwright_html_report_url": result.get("playwright_html_report_url") or "/artifacts/reports/existing-framework/html/index.html",
            "message": result.get("message", "Existing framework execution completed."),
        })
    except Exception as exc:
        msg = f"Existing framework execution failed before Playwright could run: {type(exc).__name__}: {exc}"
        log_event("existing_framework", msg, status="error", progress=100, details={"framework_path": framework_path})
        record_action("execute_existing_framework", "error", msg, {"framework_path": framework_path})
        return JSONResponse({"ok": False, "stage": "existing_framework_execution_failed", "error": msg, "message": msg}, status_code=200)


@app.post("/api/existing-framework/failure/analyze")
async def api_existing_framework_failure_analyze(
    framework_path: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    record_action("existing_framework_rca", "running", "Existing framework failed-only RCA analysis started.", {"framework_path": framework_path, "provider": provider})
    log_event("existing_framework_rca", "RCA is running in background thread so the GUI can keep showing progress.", progress=10, details={"provider": provider})
    report = await run_in_threadpool(analyze_existing_failure, framework_path=framework_path, provider=provider, model=model, base_url=base_url)
    record_action("existing_framework_rca", "done" if report.get("ok") else "warning", report.get("message", "Existing framework RCA completed."), {"framework_path": framework_path, "report": report})
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "existing_framework_root_cause_completed",
        "root_cause": report,
        "root_cause_report_url": report.get("root_cause_report_url") or "/artifacts/reports/existing-framework/root-cause-report.html",
        "external_research_report_url": report.get("external_research_report_url"),
        "message": report.get("message", "Existing framework RCA completed for failed specs only."),
    })


@app.post("/api/existing-framework/self-heal/propose")
async def api_existing_framework_self_heal_propose(
    framework_path: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    policy_mode: str = Form("approved_with_backup"),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    record_action("existing_framework_self_heal_propose", "running", "Existing framework self-healing proposal started.", {"framework_path": framework_path, "provider": provider})
    log_event("existing_framework_self_healing", "Creating safe fix plan in background thread so GUI remains responsive on slow VM/VDI.", progress=10, details={"provider": provider, "policy_mode": policy_mode})
    report = await run_in_threadpool(self_heal_existing_framework, framework_path=framework_path, provider=provider, model=model, base_url=base_url, apply_patch=False, policy_mode=policy_mode)
    record_action("existing_framework_self_heal_propose", "done" if report.get("ok") else "warning", report.get("message", "Self-healing proposal completed."), {"framework_path": framework_path, "report": report})
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": report.get("stage") or "existing_framework_self_healing_proposal_created",
        "self_healing": report,
        "self_healing_report_url": report.get("self_healing_report_url") or "/artifacts/reports/existing-framework/self-healing-report.html",
        "message": report.get("message") or "Safe fix plan created. No files were changed.",
    })


@app.post("/api/existing-framework/self-heal/approval-request")
async def api_existing_framework_self_heal_approval_request(
    framework_path: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    policy_mode: str = Form("approved_with_backup"),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    record_action("existing_framework_self_heal_approval_request", "running", "Runtime approval request for AI patch started.", {"framework_path": framework_path, "provider": provider, "policy_mode": policy_mode})
    log_event("existing_framework_self_healing", "Preparing safe runtime approval request in background thread.", progress=15, details={"provider": provider, "policy_mode": policy_mode})
    report = await run_in_threadpool(create_runtime_patch_approval_request, framework_path=framework_path, provider=provider, model=model, base_url=base_url, policy_mode=policy_mode)
    record_action("existing_framework_self_heal_approval_request", "done" if report.get("ok") else "warning", report.get("message", "Runtime approval request created."), {"framework_path": framework_path, "report": report})
    return JSONResponse(report)


@app.post("/api/existing-framework/self-heal/apply")
async def api_existing_framework_self_heal_apply(
    framework_path: str = Form(""),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    policy_mode: str = Form("approved_with_backup"),
    human_approval_decision: str = Form(""),
    human_approval_instruction: str = Form(""),
    human_approval_safe_files: str = Form(""),
    human_approval_request_id: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    record_action("existing_framework_self_heal_apply", "running", "Existing framework guarded self-healing patch started.", {"framework_path": framework_path, "provider": provider})
    log_event("existing_framework_self_healing", "Applying approved AI fix in background thread. Backup/guardrails/rollback remain active.", progress=15, details={"provider": provider, "policy_mode": policy_mode})
    report = await run_in_threadpool(self_heal_existing_framework, framework_path=framework_path, provider=provider, model=model, base_url=base_url, apply_patch=True, policy_mode=policy_mode, human_approval_decision=human_approval_decision, human_approval_instruction=human_approval_instruction, human_approval_safe_files=human_approval_safe_files, human_approval_request_id=human_approval_request_id)
    record_action("existing_framework_self_heal_apply", "done" if report.get("ok") else "warning", report.get("message", "Self-healing apply completed."), {"framework_path": framework_path, "report": report})
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": report.get("stage") or "existing_framework_self_healing_patch_finished",
        "self_healing": report,
        "changed_files": report.get("changed_files") or [],
        "applied": bool(report.get("applied")),
        "self_healing_report_url": report.get("self_healing_report_url") or "/artifacts/reports/existing-framework/self-healing-report.html",
        "message": report.get("message") or "Self-healing step finished. Review changed_files before rerun.",
    })




@app.post("/api/existing-framework/self-heal/rollback-last")
async def api_existing_framework_self_heal_rollback_last() -> JSONResponse:
    record_action("existing_framework_self_heal_rollback", "running", "Rollback of last AI fix started.", {})
    report = rollback_last_existing_fix()
    record_action("existing_framework_self_heal_rollback", "done" if report.get("ok") else "warning", report.get("message", "Rollback finished."), {"report": report})
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": report.get("stage") or "existing_framework_rollback_finished",
        "rollback": report,
        "message": report.get("message") or "Rollback finished.",
    })



@app.post("/api/existing-framework/execute/failed-only-distributed")
async def api_existing_framework_execute_failed_only_distributed(
    framework_path: str = Form(""),
    project: str = Form("auto"),
    headed: bool = Form(True),
    distributed_browsers: str = Form("chromium"),
    distributed_shard_count: int = Form(3),
    distributed_tests_per_shard: int = Form(10),
    distributed_agent_ids: str = Form(""),
    execution_target_mode: str = Form("central_only"),
    run_on_agents: str = Form("false"),
    worker_workspace_mode: str = Form("central_shared_workspace"),
    central_shared_framework_path: str = Form(""),
    master_worker_name: str = Form("Local-PC-or-Central-VM"),
    execution_provider: str = Form("local_vm"),
    browserstack_local: str = Form("true"),
) -> JSONResponse:
    """Rerun failed specs through the distributed/local parallel runner.

    This is a separate validation path. The existing sequential failed-only rerun
    endpoint remains unchanged for teams that want one browser/process.
    """
    from qa_pipeline.agents.existing_framework_control.controller import (
        _best_failed_inventory_for_followup,
        _failed_rerun_targets_from_inventory,
        _resolve_framework_path,
        _strip_playwright_line_selector,
        _spec_compare_key,
        _read_first_run_baseline,
        _append_failed_only_rerun_iteration,
        _write_failed_only_iteration_playwright_report,
        _write_existing_consolidated_report,
        _failed_only_iteration_limit_state,
        _manual_review_limit_payload,
        read_existing_failed_inventory,
    )
    from qa_pipeline.core.distributed_history import run_distributed_plan
    inventory = _best_failed_inventory_for_followup()
    framework_path = framework_path or inventory.get("framework_path") or ""
    root = _resolve_framework_path(framework_path) if framework_path else None
    failed_targets = _failed_rerun_targets_from_inventory(inventory, root=root) if root else []
    failed_specs = sorted(dict.fromkeys(_strip_playwright_line_selector(t) for t in failed_targets), key=_spec_compare_key)
    limit_state = _failed_only_iteration_limit_state(root) if root else {"blocked": False}
    if limit_state.get("blocked"):
        payload = _manual_review_limit_payload(root, inventory, "existing_framework_failed_only_distributed_blocked_after_two_iterations")
        payload["failed_targets_blocked"] = failed_targets
        return JSONResponse(payload, status_code=200)
    if not inventory.get("ok") or not failed_targets:
        return JSONResponse({
            "ok": False,
            "stage": "existing_framework_failed_only_distributed_blocked_no_inventory",
            "failed_inventory": inventory,
            "message": inventory.get("error") or "No failed test targets are available for distributed rerun.",
        }, status_code=200)
    browsers = (distributed_browsers or "").strip() or ((project if project and project != "auto" else "chromium"))
    mode = (execution_target_mode or "central_only").strip() or "central_only"
    if str(execution_provider).lower() == 'browserstack':
        mode = 'browserstack_cloud'
        os.environ['ASTRAHEAL_BROWSERSTACK_LOCAL'] = str(browserstack_local or 'true')
    # For the user's requested 1-10, 11-20, rest-on-next-browser pattern,
    # central_only + distributed_tests_per_shard drives local/central VM browser shards.
    record_action("existing_framework_failed_only_distributed_rerun", "running", f"Distributed failed-only rerun started for {len(failed_targets)} failed target(s).", {"framework_path": framework_path, "failed_targets": failed_targets, "failed_specs": failed_specs, "tests_per_shard": distributed_tests_per_shard, "execution_target_mode": mode})
    payload = run_distributed_plan(
        framework_path=framework_path,
        selected_tests="\n".join(failed_targets),
        browsers=browsers,
        shard_count=max(1, int(distributed_shard_count or 1)),
        agent_ids=distributed_agent_ids,
        headed=bool(headed),
        run_on_agents=str(run_on_agents).lower() not in {"false", "0", "no"},
        worker_workspace_mode=worker_workspace_mode,
        central_shared_framework_path=central_shared_framework_path,
        centralize_reports_and_ai_memory=True,
        execution_target_mode=mode,
        master_worker_name=master_worker_name or "Local-PC-or-Central-VM",
        tests_per_shard=max(1, int(distributed_tests_per_shard or 10)),
        run_role="failed_only_rerun",
    )
    payload["stage"] = "existing_framework_failed_only_distributed_rerun_completed"
    payload["scope"] = "failed_test_targets_only_distributed"
    payload["source_failed_inventory"] = inventory
    payload["submitted_failed_targets"] = failed_targets
    try:
        rerun_inventory = read_existing_failed_inventory()
        baseline_inventory = _read_first_run_baseline(inventory)
        iteration = _append_failed_only_rerun_iteration(root, inventory, rerun_inventory, payload, {}, failed_targets)
        latest_report = _write_failed_only_iteration_playwright_report(root, iteration, baseline_inventory)
        _write_existing_consolidated_report(baseline_inventory, rerun_inventory, payload, {})
        payload["rerun_iteration"] = iteration
        payload["playwright_html_report_url"] = f"/artifacts/reports/existing-framework/{latest_report.name}"
        payload["existing_framework_consolidated_report_url"] = "/artifacts/reports/existing-framework/consolidated-report.html"
    except Exception as exc:
        payload["combined_iteration_report_warning"] = f"{type(exc).__name__}: {exc}"
    payload["message"] = payload.get("message") or f"Failed-only distributed rerun completed/launched for {len(failed_targets)} failed target(s)."
    record_action("existing_framework_failed_only_distributed_rerun", "done" if payload.get("ok") else "warning", payload.get("message", "Distributed failed-only rerun finished."), {"framework_path": framework_path, "payload": payload})
    return JSONResponse(payload)


@app.post("/api/existing-framework/execute/failed-only")
async def api_existing_framework_execute_failed_only(
    framework_path: str = Form(""),
    project: str = Form("auto"),
    headed: bool = Form(True),
    base_url: str = Form(""),
    execution_mode: str = Form("sequential"),
    shards: int = Form(1),
    test_command: str = Form(""),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    # Failed-only validation after RCA/self-healing should also be visible by default.
    headed = bool(headed)
    record_action("existing_framework_failed_only_rerun", "running", f"Existing framework failed-only rerun started in {'headed/visible-browser' if headed else 'headless'} mode.", {"framework_path": framework_path, "headed": headed})
    result = await run_in_threadpool(execute_existing_failed_only, framework_path=framework_path, project=project, headed=headed, base_url=base_url, execution_mode=execution_mode, shards=shards, test_command=test_command, use_mcp_assist=True)
    record_action("existing_framework_failed_only_rerun", "done" if result.get("ok") else "warning", result.get("message", "Failed-only rerun completed."), {"framework_path": framework_path, "result": result})
    return JSONResponse({
        "ok": bool(result.get("ok")),
        "stage": "existing_framework_failed_only_rerun_completed",
        "failed_only": result,
        "rerun_scope_verification": result.get("rerun_scope_verification"),
        "timeout_policy": result.get("timeout_policy"),
        "playwright_html_report_url": result.get("playwright_html_report_url") or "/artifacts/reports/existing-framework/html/index.html",
        "existing_framework_consolidated_report_url": result.get("existing_framework_consolidated_report_url"),
        "archived_full_report_url": (result.get("archived_full_report") or {}).get("url"),
        "message": result.get("message", "Existing framework failed-only rerun completed."),
    })




@app.post("/api/existing-framework/robust-harness/install")
async def api_existing_framework_install_robust_harness(
    framework_path: str = Form(""),
) -> JSONResponse:
    report = install_existing_framework_robust_harness(framework_path=framework_path)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "existing_framework_robust_harness_installed",
        "robust_harness": report,
        "message": report.get("message", "Robust RCA harness installed."),
    })


@app.post("/api/existing-framework/selector-health")
async def api_existing_framework_selector_health(
    framework_path: str = Form(""),
) -> JSONResponse:
    report = generate_existing_selector_health_report(framework_path=framework_path)
    return JSONResponse({
        "ok": bool(report.get("ok")),
        "stage": "existing_framework_selector_health_report_generated",
        "selector_health": report,
        "selector_health_report_url": report.get("url") or "/artifacts/reports/existing-framework/selector-health-report.html",
        "message": "Selector Health Report generated from execution/healing history.",
    })

@app.post("/api/existing-framework/human-intervention/request")
async def api_existing_framework_human_intervention_request(
    framework_path: str = Form(""),
    reason: str = Form(""),
) -> JSONResponse:
    report = create_human_intervention_request(framework_path=framework_path, reason=reason, source="gui")
    record_action("human_intervention_request", "warning", report.get("reason", "Human intervention requested."), {"framework_path": framework_path, "request": report})
    return JSONResponse(report)


@app.post("/api/existing-framework/human-intervention/save")
async def api_existing_framework_human_intervention_save(
    framework_path: str = Form(""),
    intervention_type: str = Form("framework_code"),
    decision: str = Form("reviewed"),
    summary: str = Form(""),
    details: str = Form(""),
    affected_files: str = Form(""),
    environment_updates: str = Form(""),
    test_data_updates: str = Form(""),
    safe_files: str = Form(""),
    rerun_instruction: str = Form(""),
) -> JSONResponse:
    report = save_human_intervention_update(
        framework_path=framework_path,
        intervention_type=intervention_type,
        decision=decision,
        summary=summary,
        details=details,
        affected_files=affected_files,
        environment_updates=environment_updates,
        test_data_updates=test_data_updates,
        safe_files=safe_files,
        rerun_instruction=rerun_instruction,
    )
    record_action("human_intervention_update", "done", report.get("message", "Human intervention update saved."), {"framework_path": framework_path, "update": report})
    return JSONResponse(report)


@app.get("/api/existing-framework/human-intervention/memory")
def api_existing_framework_human_intervention_memory() -> dict:
    return read_human_intervention_memory(limit=50)

@app.get("/api/existing-framework/failed-inventory")
def api_existing_framework_failed_inventory() -> dict:
    return read_existing_failed_inventory()


@app.post("/api/execute/failed-only")
async def api_execute_failed_only(
    project: str = Form("auto"),
    use_mcp: bool = Form(True),
    headed: bool = Form(True),
    base_url: str = Form(""),
    execution_mode: str = Form("sequential"),
    shards: int = Form(2),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    write_playwright_mcp_configs(headless=not headed)
    log_event("playwright_execution", "Starting failed-only rerun after RCA/self-healing. Only previously failed spec files will be executed.", progress=8, details={"headed": headed, "execution_mode": execution_mode, "shards": shards})
    result = execute_failed_only_after_healing(project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, execution_mode=execution_mode, shards=shards)
    _clear_rca_failed_only_pending()
    html_report_path = generate_enterprise_html_report()
    return JSONResponse({
        "ok": result.get("ok", False),
        "stage": "failed_only_rerun_completed",
        "failed_only": result,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "failed_only_consolidated_report_url": result.get("failed_only_consolidated_report_url"),
        "archived_full_report_url": result.get("archived_full_report_url"),
        "message": result.get("message", "Failed-only rerun completed."),
    })




@app.get("/api/enterprise-stack/status")
def api_enterprise_stack_status() -> dict:
    data = enterprise_stack_status()
    data["langsmith"] = langsmith_status()
    return data


@app.post("/api/enterprise-stack/start")
async def api_enterprise_stack_start(
    include_observability: bool = Form(True),
    include_mcp: bool = Form(True),
    include_ollama: bool = Form(False),
) -> JSONResponse:
    status = docker_start(include_ollama=include_ollama, include_observability=include_observability, include_mcp=include_mcp)
    status["enterprise_stack"] = enterprise_stack_status()
    return JSONResponse(status)


@app.post("/api/jira/status")
async def api_jira_status(
    jira_url: str = Form(""),
    jira_username: str = Form(""),
    jira_api_token: str = Form(""),
) -> JSONResponse:
    return JSONResponse(jira_status(jira_url, jira_username, jira_api_token))


@app.post("/api/jira/fetch-epic")
async def api_jira_fetch_epic(
    jira_url: str = Form(""),
    jira_username: str = Form(""),
    jira_api_token: str = Form(""),
    epic_key: str = Form(""),
    feature: str = Form(""),
    base_url: str = Form(""),
    generate_testcases_now: bool = Form(True),
    max_workers: int = Form(4),
) -> JSONResponse:
    base_url = _require_project_base_url(base_url)
    creds = JiraCredentials.from_values(jira_url, jira_username, jira_api_token)
    try:
        bundle = JiraClient(creds).fetch_epic_with_children(epic_key)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    epic_feature = _safe_feature(feature or epic_key or "jira_epic")
    source_text = epic_to_source_text(bundle)
    uploads_dir = QA_CACHE_DIR / "jira_epics" / epic_feature
    uploads_dir.mkdir(parents=True, exist_ok=True)
    source_path = uploads_dir / f"{epic_feature}_jira_epic.txt"
    source_path.write_text(source_text, encoding="utf-8")
    response = {
        "ok": True,
        "epic_key": epic_key,
        "feature": epic_feature,
        "source_file": _relative(source_path),
        "epic_summary": (bundle.get("epic", {}).get("fields", {}) or {}).get("summary", ""),
        "children_count": bundle.get("count", 0),
        "children_keys": [i.get("key") for i in bundle.get("children", [])],
        "search_attempts": bundle.get("search_attempts", []),
        "jql_errors": bundle.get("jql_errors", []),
        "source_preview": source_text[:8000],
        "security_note": "Jira API token was used for this request only and is not written to project_config.json.",
        "jira_api_note": "Uses current Jira Cloud /rest/api/3/search/jql endpoint first, then legacy/agile fallbacks only when needed.",
    }
    if generate_testcases_now:
        items = []
        # Enterprise expectation: generate one testcase set per child work item.
        # If an epic has no returned children, generate a fallback testcase from the epic itself.
        children = list(bundle.get("children", []) or [])
        issues = children if children else [bundle.get("epic", {})]
        for issue in issues:
            if not issue:
                continue
            key = issue.get("key") or epic_feature
            fields = issue.get("fields", {}) or {}
            items.append({
                "feature": key.lower().replace("-", "_"),
                "title": f"{key} {fields.get('summary','')}",
                "text": issue_to_testcase_text(issue),
            })
        parallel = generate_parallel(items, source_type="jira_epics", base_url=base_url, max_workers=max_workers)
        generated_features = [r.get("feature") for r in parallel.get("results", []) if r.get("ok") and r.get("feature")]
        active_context = write_active_context({
            "channel": "jira",
            "jira_mode": "epic_children" if children else "epic_fallback",
            "source_type": "jira_epics",
            "epic_key": epic_key,
            "requested_feature": epic_feature,
            "parent_feature": epic_feature,
            "children_keys": [i.get("key") for i in children],
            "features": generated_features,
            "testcase_paths": [r.get("testcase_file") for r in parallel.get("results", []) if r.get("testcase_file")],
            "playwright_generated": False,
            "functional_testcases_reviewed": False,
            "review_gate": "waiting_for_user_review",
            "strict_scope": True,
        })
        log_event("testcase_generation", f"Jira Epic {epic_key} generated {len(generated_features)} child testcase file(s); waiting for user review", status="done", progress=100, source_type="jira_epics", details={"features": generated_features})
        save_project_config({**load_project_config(), "source_type": "jira_epics", "feature": epic_feature, "base_url": base_url})
        response["parallel_testcase_generation"] = parallel
        response["active_context"] = active_context
        response["parallel_generation_scope"] = "children_only" if children else "epic_fallback_no_children_returned"
    html_report_path = generate_enterprise_html_report()
    response["html_report"] = _relative(html_report_path)
    response["html_report_url"] = "/artifacts/reports/enterprise/enterprise-report.html"
    return JSONResponse(response)


@app.post("/api/jira/fetch-issue")
async def api_jira_fetch_issue(
    jira_url: str = Form(""),
    jira_username: str = Form(""),
    jira_api_token: str = Form(""),
    issue_key: str = Form(""),
    feature: str = Form(""),
    base_url: str = Form(""),
    generate_testcases_now: bool = Form(True),
) -> JSONResponse:
    base_url = _require_project_base_url(base_url)
    creds = JiraCredentials.from_values(jira_url, jira_username, jira_api_token)
    try:
        issue = JiraClient(creds).get_issue(issue_key.strip().upper())
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    key = issue.get("key") or issue_key
    issue_feature = _safe_feature(feature or key)
    source_text = issue_to_testcase_text(issue)
    uploads_dir = QA_CACHE_DIR / "jira_issues" / issue_feature
    uploads_dir.mkdir(parents=True, exist_ok=True)
    source_path = uploads_dir / f"{issue_feature}_jira_issue.txt"
    source_path.write_text(source_text, encoding="utf-8")
    response = {
        "ok": True,
        "jira_mode": "single_issue",
        "issue_key": key,
        "feature": issue_feature,
        "source_file": _relative(source_path),
        "issue_summary": (issue.get("fields", {}) or {}).get("summary", ""),
        "source_preview": source_text[:8000],
        "security_note": "Jira API token was used for this request only and is not written to project_config.json.",
    }
    if generate_testcases_now:
        parallel = generate_parallel([{"feature": issue_feature, "title": key, "text": source_text}], source_type="jira_epics", base_url=base_url, max_workers=1)
        generated_features = [r.get("feature") for r in parallel.get("results", []) if r.get("ok") and r.get("feature")]
        active_context = write_active_context({
            "channel": "jira",
            "jira_mode": "single_issue",
            "source_type": "jira_epics",
            "issue_key": key,
            "requested_feature": issue_feature,
            "parent_feature": issue_feature,
            "features": generated_features or [issue_feature],
            "testcase_paths": [r.get("testcase_file") for r in parallel.get("results", []) if r.get("testcase_file")],
            "playwright_generated": False,
            "functional_testcases_reviewed": False,
            "review_gate": "waiting_for_user_review",
            "strict_scope": True,
        })
        log_event("testcase_generation", f"Jira issue {key} generated testcase file; waiting for user review", status="done", progress=100, source_type="jira_epics", details={"features": generated_features or [issue_feature]})
        save_project_config({**load_project_config(), "source_type": "jira_epics", "feature": issue_feature, "base_url": base_url})
        response["parallel_testcase_generation"] = parallel
        response["active_context"] = active_context
    html_report_path = generate_enterprise_html_report()
    response["html_report"] = _relative(html_report_path)
    response["html_report_url"] = "/artifacts/reports/enterprise/enterprise-report.html"
    return JSONResponse(response)


@app.post("/api/testcases/generate-parallel")
async def api_generate_parallel_testcases(
    source_type: str = Form("jira_epics"),
    base_url: str = Form(""),
    pasted_text: str = Form(""),
    max_workers: int = Form(4),
) -> JSONResponse:
    base_url = _effective_base_url(base_url)
    blocks = [b.strip() for b in (pasted_text or "").split("\n---") if b.strip()]
    if not blocks:
        return JSONResponse({"ok": False, "error": "Paste multiple testcase/story blocks separated by a line starting with ---"})
    items = [{"feature": f"parallel_{idx}", "title": block.splitlines()[0][:80] if block.splitlines() else f"parallel {idx}", "text": block} for idx, block in enumerate(blocks, start=1)]
    result = generate_parallel(items, source_type=source_type, base_url=base_url, max_workers=max_workers)
    html_report_path = generate_enterprise_html_report()
    result["html_report"] = _relative(html_report_path)
    result["html_report_url"] = "/artifacts/reports/enterprise/enterprise-report.html"
    return JSONResponse(result)


@app.post("/api/execute/distributed")
async def api_execute_distributed(
    feature: str = Form("login"),
    source_type: str = Form("srs"),
    project: str = Form("auto"),
    use_mcp: bool = Form(True),
    headed: bool = Form(True),
    base_url: str = Form(""),
    shards: int = Form(4),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    log_event("playwright_execution", f"Starting distributed execution for {feature} with {shards} shard(s)", progress=10, feature=feature, source_type=source_type, details={"headed": headed, "project": project, "shards": shards})
    write_playwright_mcp_configs(headless=not headed)
    pending = _read_rca_failed_only_pending()
    if pending.get("active") and pending.get("failed_specs"):
        safe_shards = max(1, min(int(shards or 1), 20))
        log_event("playwright_execution", "RCA guard is active: distributed execution was redirected to failed-only distributed rerun.", progress=12, status="warning", details=pending)
        result = execute_failed_only_after_healing(project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, execution_mode="distributed", shards=safe_shards)
        _clear_rca_failed_only_pending()
        html_report_path = generate_enterprise_html_report()
        return JSONResponse({
            "ok": result.get("ok", False),
            "stage": "rca_guard_failed_only_distributed_completed",
            "rerouted_from": "distributed_execution",
            "failed_only": result,
            "failed_only_pending": pending,
            "html_report": _relative(html_report_path),
            "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
            "playwright_html_report_url": "/artifacts/reports/html/index.html",
            "failed_only_consolidated_report_url": result.get("failed_only_consolidated_report_url"),
            "archived_full_report_url": result.get("archived_full_report_url"),
            "message": "RCA guard prevented full distributed rerun. Only failed specs were re-executed.",
        })
    active_features = _active_features(feature, source_type)
    if active_features:
        source_type = read_active_context().get("source_type", source_type)
        spec_precheck = _ensure_specs_for_features(active_features, source_type, load_project_config().get("provider", "codex"), load_project_config().get("ollama_model", "llama3"), base_url, parent_feature=feature)
        if not spec_precheck.get("ok"):
            return JSONResponse({"ok": False, "stage": "distributed_execution_precheck_failed", "error": "Could not generate every active batch spec.", "spec_precheck": spec_precheck, "active_context": read_active_context()})
        execution = execute_feature_distributed(feature="active_batch", features=active_features, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, shards=shards)
    else:
        spec_precheck = _ensure_spec_exists_for_execution(feature, source_type, base_url)
        if not spec_precheck.get("ok"):
            return JSONResponse({"ok": False, "stage": "distributed_execution_precheck_failed", "error": spec_precheck.get("message"), "spec_precheck": spec_precheck})
        execution = execute_feature_distributed(feature=feature, project=project, use_mcp=use_mcp, headed=headed, base_url=base_url, shards=shards)
    log_event("playwright_execution", "Distributed Playwright execution completed", status="done" if execution.get("ok") else "warning", progress=100, feature=feature, source_type=source_type, details={"ok": execution.get("ok"), "shards": shards})
    html_report_path = generate_enterprise_html_report()
    return JSONResponse({
        "ok": execution.get("ok", False),
        "stage": "distributed_execution_completed",
        "spec_precheck": spec_precheck,
        "execution": execution,
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
    })



@app.post("/api/app/profile")
async def api_app_profile(
    feature: str = Form("feature"),
    base_url: str = Form(""),
    use_mcp: bool = Form(True),
) -> JSONResponse:
    """Profile a complex app before code generation.

    This gives the LLM and deterministic generator an explicit app-understanding layer:
    page source, live DOM map, shadow DOM/iframe/overlay risks, locator strategy, and
    self-healing guardrails.
    """
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    profile = profile_application(feature=feature, base_url=base_url, use_mcp=use_mcp)
    html_report_path = generate_enterprise_html_report()
    profile["html_report"] = _relative(html_report_path)
    profile["html_report_url"] = "/artifacts/reports/enterprise/enterprise-report.html"
    return JSONResponse(profile)



def _spawn_command_in_user_terminal(args: list[str], title: str = "Codex Login") -> dict:
    """Launch an interactive command without blocking the FastAPI GUI.

    Codex login is intentionally interactive. Capturing it in the GUI backend makes the
    button appear stuck and can prevent the browser/device-auth flow from opening. This
    helper opens a separate terminal window and returns immediately. The GUI then polls
    `codex login status` until the user completes authentication.
    """
    try:
        if os.name == "nt":
            command = subprocess.list2cmdline(args)
            # /k keeps the window open so the user can see browser/device-auth output.
            proc = subprocess.Popen(["cmd.exe", "/c", "start", title, "cmd.exe", "/k", command], cwd=str(REPO_ROOT))
            return {"ok": True, "pid": proc.pid, "mode": "windows_terminal", "command": command}
        if sys.platform == "darwin":
            command = " ".join(subprocess.list2cmdline([a]) for a in args)
            script = f'tell application "Terminal" to do script "cd {str(REPO_ROOT).replace(chr(34), chr(92)+chr(34))}; {command}"'
            proc = subprocess.Popen(["osascript", "-e", script])
            return {"ok": True, "pid": proc.pid, "mode": "mac_terminal", "command": command}
        # Linux fallback: start detached. If no terminal emulator exists, user can still
        # run the returned command manually.
        proc = subprocess.Popen(args, cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True, "pid": proc.pid, "mode": "detached", "command": " ".join(args)}
    except Exception as exc:
        return {"ok": False, "error": f"Could not launch interactive terminal: {type(exc).__name__}: {exc}", "manual_command": " ".join(args)}


@app.post("/api/codex/login/start")
async def api_codex_login_start(device_auth: bool = Form(False)) -> JSONResponse:
    """Launch Codex login interactively and return immediately.

    This is the GUI-safe login path. It does not collect or store credentials. Codex
    owns the local auth session; this app only checks `codex login status` after the
    user finishes the browser/device-auth flow.
    """
    codex = resolve_command("codex")
    if not codex:
        return JSONResponse({"ok": False, "error": "Codex CLI not found. Install with: npm install -g @openai/codex"})
    existing = CodexCliProvider(REPO_ROOT).login_status()
    if existing.ok:
        session = _provider_readiness()
        return JSONResponse({
            "ok": True,
            "already_logged_in": True,
            "login_status_ok": True,
            "status_stdout": existing.stdout[-2000:],
            "ai_session": session,
            "message": "Codex is already logged in. The local session will be reused by the pipeline.",
        })
    args = [codex, "login"]
    login_mode = "browser"
    if device_auth:
        args.append("--device-auth")
        login_mode = "device_auth"
    launched = _spawn_command_in_user_terminal(args, title="Codex Login")
    return JSONResponse({
        "ok": bool(launched.get("ok")),
        "launched": launched,
        "login_mode": login_mode,
        "login_status_ok": False,
        "next_steps": [
            "A separate Codex login terminal/window should be open now.",
            "Complete the browser or device-auth login shown by Codex.",
            "Return to this GUI and click Check Codex/Ollama session or Refresh readiness gate.",
        ],
        "security_note": "The framework never saves your ChatGPT username/password or Codex token. Codex manages local authentication.",
    })


@app.post("/api/codex/login")
async def api_codex_login(device_auth: bool = Form(False)) -> JSONResponse:
    # Backward-compatible endpoint: now delegates to the non-blocking interactive launcher.
    return await api_codex_login_start(device_auth=device_auth)


@app.get("/api/failure-learning/status")
def api_failure_learning_status() -> dict:
    return summarize_failure_learning()


@app.post("/api/failure-learning/record")
async def api_failure_learning_record(
    error: str = Form(""),
    test_name: str = Form(""),
    category: str = Form("unknown"),
) -> JSONResponse:
    if not error.strip():
        return JSONResponse({"ok": False, "error": "Provide error text to record."})
    return JSONResponse(record_failure(error=error, test_name=test_name, category=category))


@app.get("/api/source-context/active")
def api_active_source_context() -> dict:
    return {"ok": True, "active_context": read_active_context(), "available_specs": _available_generated_specs()}



@app.get("/api/action-history")
def api_action_history() -> dict:
    return {"ok": True, "history": read_action_history(200), "summary": write_action_memory_summary()}

@app.post("/api/action-history/record")
async def api_action_history_record(action: str = Form("manual_note"), message: str = Form(""), status: str = Form("note")) -> JSONResponse:
    event = record_action(action, status, message, {})
    log_event("ai_memory", f"Action history note recorded: {action}", status="done", progress=100, details={"action": action})
    return JSONResponse({"ok": True, "event": event, "summary": write_action_memory_summary(), "message": "Action history memory updated."})

@app.get("/api/reports/html")
def api_html_report() -> dict:
    html_report_path = generate_enterprise_html_report()
    content = html_report_path.read_text(encoding="utf-8") if html_report_path.exists() else ""
    return {
        "ok": html_report_path.exists(),
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "content_preview": content[-20000:],
    }

@app.post("/api/generate")
async def generate_full_flow(
    source_type: str = Form("jira"),
    feature: str = Form("login"),
    provider: str = Form("codex"),
    model: str = Form("llama3"),
    pasted_text: str = Form(""),
    base_url: str = Form(""),
    skip_npm: bool = Form(True),
    source_file: Optional[UploadFile] = File(None),
) -> JSONResponse:
    feature = _safe_feature(feature)
    base_url = _effective_base_url(base_url)
    source_path, normalized_path = _source_to_normalized(source_type, feature, pasted_text, source_file, base_url)
    deterministic_url_guard = sanitize_testcase_urls(normalized_path, base_url)
    try:
        ai_source_path, ai_plan = maybe_enhance_testcases_with_ai(normalized_path, provider, model, feature, base_url)
        ai_url_guard = sanitize_testcase_urls(ai_source_path, base_url)
        ai_plan["url_guard"] = {"deterministic": deterministic_url_guard, "ai": ai_url_guard}
    except Exception as exc:
        ai_source_path = normalized_path
        ai_plan = {
            "ai_used": False,
            "provider": provider,
            "ai_ok": False,
            "message": f"AI enhancement failed safely: {type(exc).__name__}: {exc}",
            "fallback": "Deterministic testcase JSON was used.",
            "url_guard": {"deterministic": deterministic_url_guard},
        }
    sanitize_testcase_urls(ai_source_path, base_url)
    testcase_path = ingest_source(ai_source_path, source_type, feature)
    sanitize_testcase_urls(testcase_path, base_url)
    tc = read_json(testcase_path)
    crawl_report = crawl_dynamic_page(base_url=base_url, feature=feature, headed=False)
    try:
        ai_codegen = _ai_codegen_message(provider, model, feature, source_type, tc)
    except Exception as exc:
        ai_codegen = {"provider": provider, "ai_ok": False, "message": f"AI codegen assistance failed safely: {type(exc).__name__}: {exc}"}
    generation = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
    spec_path = _generated_spec_path(feature)
    if spec_path.exists():
        _remember_latest_generation(feature, source_type, spec_path, testcase_path)
    review = run_review(skip_npm=skip_npm)
    summary_path = generate_summary()
    html_report_path = generate_enterprise_html_report()
    payload = {
        "ok": review.get("ok", False),
        "stage": "full_flow_completed",
        "source_uploaded": _relative(source_path),
        "deterministic_normalized_source": _relative(normalized_path),
        "testcase_generation_source": _relative(ai_source_path),
        "testcase_file": _relative(testcase_path),
        "functional_testcases": tc,
        "generated_playwright_dir": _relative(GENERATED_PLAYWRIGHT_DIR),
        "created": [d.__dict__ for d in generation.created],
        "reused": [d.__dict__ for d in generation.reused],
        "files": generation.files,
        "spec_path": _relative(spec_path),
        "spec_exists": spec_path.exists(),
        "available_specs": _available_generated_specs(),
        "review": review,
        "summary": _relative(summary_path),
        "html_report": _relative(html_report_path),
        "html_report_url": "/artifacts/reports/enterprise/enterprise-report.html",
        "playwright_html_report_url": "/artifacts/reports/html/index.html",
        "ai": {"testcase_planning": ai_plan, "codegen_assistance": ai_codegen},
        "dynamic_crawl": crawl_report,
        "llm_message_preview": (ai_plan.get("message", "") + "\n\n" + ai_codegen.get("message", ""))[-6000:],
    }
    payload.update(_playwright_preview(feature, source_type))
    return JSONResponse(payload)



# -----------------------------------------------------------------------------
# Decoupled Module APIs
# -----------------------------------------------------------------------------
@app.post("/api/module1/app-url/generate")
async def module1_app_url_generate(
    app_url: str = Form(""),
    feature: str = Form("module1_feature"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
) -> JSONResponse:
    from qa_pipeline.modules.functional_testcase_generator.controller import generate_testcases_from_url
    if not app_url:
        raise HTTPException(status_code=400, detail="Application URL is required.")
    return JSONResponse(generate_testcases_from_url(app_url, feature, provider, model))

@app.post("/api/module1/testcases/quality-rca")
async def module1_testcase_quality_rca(
    feature: str = Form("module1_feature"),
    source_type: str = Form("module1"),
    base_url: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.modules.functional_testcase_generator.controller import quality_rca_and_complete
    return JSONResponse(quality_rca_and_complete(feature, source_type, base_url))

@app.post("/api/module1/testdata/generate")
async def module1_testdata_generate(
    feature: str = Form("module1_feature"),
    source_type: str = Form("module1"),
) -> JSONResponse:
    from qa_pipeline.modules.functional_testcase_generator.controller import generate_and_save_testdata
    return JSONResponse(generate_and_save_testdata(feature, source_type))

@app.post("/api/module1/human-review/save")
async def module1_human_review_save(
    feature: str = Form("module1_feature"),
    source_type: str = Form("module1"),
    edited_json: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.modules.functional_testcase_generator.controller import save_human_review
    return JSONResponse(save_human_review(feature, edited_json, source_type))

@app.post("/api/module2/testcases/load")
async def module2_load_testcases(
    feature: str = Form("module2_feature"),
    pasted_json_or_steps: str = Form(""),
    jira_story: str = Form(""),
    jira_epic: str = Form(""),
    source_mode: str = Form("auto"),
    testcase_file: Optional[UploadFile] = File(None),
) -> JSONResponse:
    from qa_pipeline.modules.playwright_ts_generator.controller import load_functional_testcases_enterprise
    uploaded = await testcase_file.read() if testcase_file else None
    return JSONResponse(load_functional_testcases_enterprise(feature, pasted_json_or_steps, uploaded, testcase_file.filename if testcase_file else "", jira_story=jira_story, jira_epic=jira_epic, source_mode=source_mode))


@app.post("/api/module2/playwright/preview-placement")
async def module2_preview_existing_placement(
    framework_path: str = Form(""),
    feature: str = Form("module2_feature"),
    target_test_folder: str = Form(""),
    target_page_file: str = Form(""),
    target_locator_file: str = Form(""),
    placement_mode: str = Form("confirm_if_ambiguous"),
) -> JSONResponse:
    from qa_pipeline.modules.playwright_ts_generator.controller import preview_existing_framework_generation_enterprise
    return JSONResponse(preview_existing_framework_generation_enterprise(
        framework_path=framework_path,
        feature=feature,
        target_test_folder=target_test_folder,
        target_page_file=target_page_file,
        target_locator_file=target_locator_file,
        placement_mode=placement_mode,
    ))


@app.post("/api/module2/atlassian/status")
async def module2_atlassian_status(
    jira_url: str = Form(""),
    confluence_url: str = Form(""),
    atlassian_username: str = Form(""),
    jira_api_token: str = Form(""),
    jira_password: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.integrations.atlassian_mcp import AtlassianCredentials, atlassian_status
    creds = AtlassianCredentials.from_values(jira_url, confluence_url, atlassian_username, jira_api_token, jira_password)
    return JSONResponse(atlassian_status(creds, include_confluence=bool(confluence_url.strip())))


@app.post("/api/module2/atlassian/fetch")
async def module2_atlassian_fetch(
    feature: str = Form("module2_feature"),
    jira_url: str = Form(""),
    confluence_url: str = Form(""),
    atlassian_username: str = Form(""),
    jira_api_token: str = Form(""),
    jira_password: str = Form(""),
    atlassian_source_kind: str = Form("jira_issue"),
    jira_issue_key: str = Form(""),
    jira_epic_key: str = Form(""),
    jira_jql: str = Form(""),
    confluence_page: str = Form(""),
    atlassian_max_results: int = Form(200),
) -> JSONResponse:
    from qa_pipeline.integrations.atlassian_mcp import AtlassianCredentials, fetch_atlassian_source
    from qa_pipeline.modules.playwright_ts_generator.controller import load_functional_testcases_enterprise
    try:
        creds = AtlassianCredentials.from_values(jira_url, confluence_url, atlassian_username, jira_api_token, jira_password)
        fetched = fetch_atlassian_source(
            creds=creds,
            source_kind=atlassian_source_kind,
            issue_key=jira_issue_key,
            epic_key=jira_epic_key,
            jql=jira_jql,
            confluence_page=confluence_page,
            max_results=max(1, min(int(atlassian_max_results or 200), 1000)),
        )
        normalized = load_functional_testcases_enterprise(
            feature=feature,
            pasted_json_or_steps=fetched.get("source_text", ""),
            source_mode="jira" if atlassian_source_kind.startswith("jira") else "auto",
        )
        return JSONResponse({**fetched, "normalized_testcases": normalized, "ok": bool(fetched.get("ok") and normalized.get("ok")), "message": fetched.get("message", "") + " " + normalized.get("message", "")})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Atlassian source fetch failed. Credentials were not saved."})

@app.post("/api/module2/playwright/generate-new")
async def module2_generate_new(
    feature: str = Form("module2_feature"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
) -> JSONResponse:
    from qa_pipeline.modules.playwright_ts_generator.controller import generate_new_playwright_framework
    return JSONResponse(generate_new_playwright_framework(feature, provider, model, base_url))

@app.post("/api/module2/playwright/generate-existing")
async def module2_generate_existing(
    framework_path: str = Form(""),
    feature: str = Form("module2_feature"),
    provider: str = Form("deterministic"),
    model: str = Form("llama3"),
    base_url: str = Form(""),
    target_test_folder: str = Form(""),
    target_page_file: str = Form(""),
    target_locator_file: str = Form(""),
    placement_mode: str = Form("confirm_if_ambiguous"),
    allow_new_support_files: bool = Form(True),
    validate_generated: bool = Form(True),
    bdd_output_mode: str = Form("playwright_specs"),
) -> JSONResponse:
    from qa_pipeline.modules.playwright_ts_generator.controller import generate_existing_framework_extension_enterprise
    return JSONResponse(generate_existing_framework_extension_enterprise(
        framework_path=framework_path,
        feature=feature,
        provider=provider,
        model=model,
        base_url=base_url,
        target_test_folder=target_test_folder,
        target_page_file=target_page_file,
        target_locator_file=target_locator_file,
        placement_mode=placement_mode,
        allow_new_support_files=allow_new_support_files,
        validate_generated=validate_generated,
        bdd_output_mode=bdd_output_mode,
    ))
