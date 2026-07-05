from __future__ import annotations

import difflib
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.openai_compatible import OpenAICompatibleProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.core.paths import REPORTS_DIR
from qa_pipeline.mcp.mcp_readiness_preflight import (
    _backup_files,
    _safe_apply_known_typescript_fixes,
    _tail,
    extract_typescript_errors,
    run_mcp_readiness_preflight,
)


_DISALLOWED_PATCH_RE = re.compile(
    r"\btest\s*\.\s*(skip|only|fixme)\s*\(|\bdescribe\s*\.\s*(skip|only|fixme)\s*\(|\bexpect\s*\(.*?\)\s*\.\s*not\s*\.\s*toBe",
    re.IGNORECASE | re.DOTALL,
)

_ALLOWED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".json", ".mjs", ".cjs"}


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _normalize_provider(provider: str) -> str:
    selected = (provider or "codex").strip().lower()
    if selected in {"deterministic", "rule-based", "rule_based_only"}:
        return "rule_based"
    return selected


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    candidates = [text]
    # Common fenced JSON response.
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE):
        candidates.insert(0, match.group(1))
    # Fallback to first JSON-looking object.
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _provider_patch_plan(provider: str, model: str, prompt: str) -> dict[str, Any]:
    provider = _normalize_provider(provider)
    if provider in {"openai", "deepseek", "perplexity"}:
        res = OpenAICompatibleProvider(provider=provider, model=model or "").chat(
            prompt,
            system=(
                "You are a senior Playwright TypeScript framework fixer. "
                "Return only valid JSON with minimal file replacement patches. "
                "Never skip tests, never weaken assertions, and never remove business validation."
            ),
            timeout_seconds=240,
        )
        return {"provider": provider, "ok": bool(res.ok), "raw_text": res.text if res.ok else "", "error": res.error if not res.ok else ""}
    if provider == "ollama":
        res = OllamaProvider(model=model or "llama3").chat(
            prompt,
            system=(
                "You are a senior Playwright TypeScript framework fixer. "
                "Return only valid JSON with minimal file replacement patches."
            ),
        )
        return {"provider": provider, "ok": bool(res.ok), "raw_text": res.text if res.ok else "", "error": res.error if not res.ok else ""}
    return {"provider": provider, "ok": False, "raw_text": "", "error": f"Provider {provider} does not support JSON patch planning."}


def _allowed_file(root: Path, file_value: str, impacted_files: set[str], full_control_scope: str) -> tuple[bool, str, Path, str]:
    rel = (file_value or "").replace("\\", "/").lstrip("/").strip()
    if not rel:
        return False, "empty file path", root, rel
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except Exception:
        return False, "path escapes framework root", target, rel
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        return False, f"file suffix {target.suffix} is not allowed", target, rel
    scope = (full_control_scope or "impacted_files_only").strip().lower()
    if scope != "framework_safe_scope" and rel not in impacted_files:
        return False, "file is outside impacted TypeScript error files", target, rel
    parts = {p.lower() for p in target.parts}
    if "node_modules" in parts or ".git" in parts or "playwright-report" in parts or "test-results" in parts:
        return False, "generated/dependency folder is not patchable", target, rel
    return True, "allowed", target, rel


def _apply_json_replacements(root: Path, patch_plan: dict[str, Any] | None, impacted_files: set[str], full_control_scope: str) -> dict[str, Any]:
    if not patch_plan:
        return {"changed_files": [], "blocked": ["AI provider did not return valid JSON patch plan."], "notes": []}
    changes = patch_plan.get("changes") or patch_plan.get("patches") or []
    if not isinstance(changes, list):
        return {"changed_files": [], "blocked": ["JSON patch plan did not contain a changes list."], "notes": []}
    changed: list[str] = []
    blocked: list[str] = []
    notes: list[str] = []
    diffs: dict[str, str] = {}
    for idx, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            blocked.append(f"change #{idx}: not an object")
            continue
        ok_file, reason, target, rel = _allowed_file(root, str(change.get("file") or ""), impacted_files, full_control_scope)
        if not ok_file:
            blocked.append(f"change #{idx} {rel}: {reason}")
            continue
        find_text = str(change.get("find") or change.get("old") or change.get("search") or "")
        replace_text = str(change.get("replace") or change.get("new") or "")
        if not find_text:
            blocked.append(f"change #{idx} {rel}: missing exact find/old text")
            continue
        if _DISALLOWED_PATCH_RE.search(replace_text):
            blocked.append(f"change #{idx} {rel}: replacement contains disallowed skip/only/fixme or assertion-weakening pattern")
            continue
        if not target.exists():
            blocked.append(f"change #{idx} {rel}: file does not exist")
            continue
        try:
            original = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            blocked.append(f"change #{idx} {rel}: could not read file: {exc}")
            continue
        count = original.count(find_text)
        if count != 1:
            blocked.append(f"change #{idx} {rel}: exact find text matched {count} times; expected 1")
            continue
        updated = original.replace(find_text, replace_text, 1)
        if _DISALLOWED_PATCH_RE.search(updated) and not _DISALLOWED_PATCH_RE.search(original):
            blocked.append(f"change #{idx} {rel}: updated file would introduce a disallowed pattern")
            continue
        try:
            target.write_text(updated, encoding="utf-8")
        except Exception as exc:
            blocked.append(f"change #{idx} {rel}: could not write file: {exc}")
            continue
        changed.append(rel)
        notes.append(str(change.get("reason") or f"Applied AI exact replacement in {rel}."))
        diffs[rel] = "\n".join(difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile=rel + " (before)",
            tofile=rel + " (after)",
            lineterm="",
        ))[-12000:]
    return {"changed_files": sorted(set(changed)), "blocked": blocked, "notes": notes, "diffs": diffs}


def _impacted_files_from_preflight(preflight: dict[str, Any]) -> set[str]:
    errors = preflight.get("typescript_errors") or []
    files = {str(e.get("file") or "").replace("\\", "/") for e in errors if e.get("file")}
    return {f for f in files if f}


def _build_full_control_prompt(root: Path, preflight: dict[str, Any], human_instruction: str, full_control_scope: str) -> str:
    errors = preflight.get("typescript_errors") or []
    checks = preflight.get("checks") or {}
    build = checks.get("npm_run_build") or {}
    output_tail = ((build.get("stdout_tail") or "") + "\n" + (build.get("stderr_tail") or ""))[-16000:]
    error_files = sorted(_impacted_files_from_preflight(preflight))
    file_snippets: dict[str, str] = {}
    for rel in error_files[:8]:
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            file_snippets[rel] = text[-18000:]
        except Exception as exc:
            file_snippets[rel] = f"<could not read: {exc}>"
    schema = {
        "summary": "short explanation",
        "changes": [
            {
                "file": "relative/path.ts",
                "find": "exact old text to replace; must match once",
                "replace": "new text",
                "reason": "why this is safe",
            }
        ],
    }
    return "\n".join([
        "You are allowed to fix the Playwright TypeScript framework build issues by proposing exact file replacements.",
        "Return ONLY valid JSON. Do not wrap in markdown.",
        "The local controller will create backups, apply exact replacements, rerun npm run build, and block unsafe changes.",
        "Rules:",
        "- Fix the actual framework-level TypeScript/build blocker, not only explain it.",
        "- Do not use test.skip, test.only, test.fixme, describe.only, or assertion weakening.",
        "- Do not delete tests or remove business validation.",
        "- Keep the existing framework/POM style.",
        "- Prefer exact minimal changes.",
        "- For catch variables typed unknown, use safe Error/String conversion.",
        "- For Element.offsetParent on Element, cast to HTMLElement.",
        "- For page.locator(selector, selector), use getByText(/.../i) or locator().or(...).",
        f"Full-control scope: {full_control_scope}",
        f"Human instruction: {human_instruction or 'No extra human instruction.'}",
        "Required JSON schema:",
        json.dumps(schema, indent=2),
        "Parsed TypeScript errors:",
        json.dumps(errors, indent=2, ensure_ascii=False),
        "Build output tail:",
        output_tail,
        "Impacted file snippets:",
        json.dumps(file_snippets, indent=2, ensure_ascii=False),
    ])


def _write_full_control_report(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    reports = root / ".aiqa-history" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    html_path = reports / "ai-full-control-framework-fix.html"
    json_path = reports / "ai-full-control-framework-fix.json"
    solution_reports = REPORTS_DIR / "existing-framework"
    solution_reports.mkdir(parents=True, exist_ok=True)
    solution_html = solution_reports / "ai-full-control-framework-fix.html"
    solution_json = solution_reports / "ai-full-control-framework-fix.json"
    status = "PASS" if payload.get("ok") else "ACTION REQUIRED"
    rows = []
    for run in payload.get("rounds") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(run.get('round')))}</td>"
            f"<td>{html.escape(str(run.get('provider')))}</td>"
            f"<td>{html.escape(str(run.get('changed_files') or []))}</td>"
            f"<td>{html.escape(str(run.get('message') or run.get('error') or ''))}</td>"
            "</tr>"
        )
    body_json = html.escape(json.dumps(payload, indent=2, ensure_ascii=False))
    html_text = f"""<!doctype html>
<html><head><meta charset='utf-8'/><title>AI Full-Control Framework Fix</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#111827;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:18px;margin:14px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #dbe3ef;padding:8px;vertical-align:top}}th{{background:#e2e8f0}}pre{{white-space:pre-wrap;background:#0f172a;color:#d1fae5;border-radius:10px;padding:14px;max-height:620px;overflow:auto}}.ok{{background:#dcfce7;color:#166534;padding:4px 8px;border-radius:999px;font-weight:700}}.bad{{background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:999px;font-weight:700}}</style>
</head><body><h1>AI Full-Control Framework Fix</h1>
<div class='card'><h2>Status: <span class='{'ok' if payload.get('ok') else 'bad'}'>{html.escape(status)}</span></h2><p>{html.escape(str(payload.get('message') or ''))}</p></div>
<div class='card'><h2>Changed files</h2><pre>{html.escape(json.dumps(payload.get('changed_files') or [], indent=2))}</pre></div>
<div class='card'><h2>Backup</h2><pre>{html.escape(json.dumps(payload.get('backup') or {}, indent=2))}</pre></div>
<div class='card'><h2>Rounds</h2><table><tr><th>Round</th><th>Provider</th><th>Changed files</th><th>Message</th></tr>{''.join(rows)}</table></div>
<div class='card'><h2>Raw JSON</h2><pre>{body_json}</pre></div>
</body></html>"""
    for p, text in ((html_path, html_text), (solution_html, html_text)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for p in (json_path, solution_json):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "framework_html": str(html_path),
        "framework_json": str(json_path),
        "solution_html": str(solution_html),
        "solution_json": str(solution_json),
    }


def ai_full_control_fix_framework_issues(
    framework_path: str,
    provider: str = "codex",
    model: str = "",
    project: str = "auto",
    browser: str = "chromium",
    human_instruction: str = "",
    max_rounds: int = 3,
    full_control_scope: str = "impacted_files_only",
) -> dict[str, Any]:
    """Agentic full-control framework repair with backups, patch guardrails and rerun loop.

    This function is intentionally broader than the conservative MCP readiness
    safe patcher. It lets the selected AI provider propose or apply real file
    changes, while the controller enforces backup, scope, forbidden-pattern and
    validation rules.
    """
    root = Path(framework_path or ".").expanduser()
    if not root.is_absolute():
        root = root.resolve()
    provider = _normalize_provider(provider)
    max_rounds = max(1, min(int(max_rounds or 3), 5))
    result: dict[str, Any] = {
        "ok": False,
        "stage": "ai_full_control_framework_fix",
        "provider": provider,
        "framework_path": str(root),
        "full_control_scope": full_control_scope,
        "rounds": [],
        "changed_files": [],
        "guardrails": [
            "backup before patch",
            "scope-limited file writes",
            "skip/only/fixme blocked",
            "build/list rerun after patch",
            "rollback possible from .aiqa-history/backups",
        ],
    }
    initial = run_mcp_readiness_preflight(str(root), project=project, browser=browser, run_build=True, run_test_list=False, check_browser=False)
    result["preflight_before"] = initial
    impacted = _impacted_files_from_preflight(initial)
    if not impacted and not initial.get("action_required"):
        result.update({"ok": True, "message": "Framework build readiness is already clean. No AI full-control fix was required."})
        result["report_files"] = _write_full_control_report(root, result)
        return result

    # Backup all currently impacted files before any patch attempt.
    backup = _backup_files(root, sorted(impacted))
    result["backup"] = backup

    current = initial
    for round_no in range(1, max_rounds + 1):
        errors = current.get("typescript_errors") or []
        impacted = _impacted_files_from_preflight(current)
        round_payload: dict[str, Any] = {"round": round_no, "provider": provider, "errors_before": errors, "changed_files": []}
        if not errors and not current.get("action_required"):
            round_payload["message"] = "No remaining build errors."
            result["rounds"].append(round_payload)
            break

        if provider == "codex":
            codex = CodexCliProvider(root, timeout_seconds=900)
            if not codex.is_available():
                round_payload["error"] = "Codex CLI is selected but not available/authenticated. Select OpenAI/DeepSeek/Ollama or run codex login."
                result["rounds"].append(round_payload)
                break
            prompt = _build_full_control_prompt(root, current, human_instruction, full_control_scope)
            ai = codex.run(prompt + "\n\nApply the minimal patch directly in the repository. Do not skip tests. Preserve framework style.")
            round_payload["ai"] = {"ok": ai.ok, "stdout": _tail(ai.stdout, 16000), "stderr": _tail(ai.stderr, 16000), "exit_code": ai.exit_code}
            if not ai.ok:
                round_payload["error"] = ai.stderr or "Codex did not complete successfully."
                result["rounds"].append(round_payload)
                break
        elif provider in {"openai", "deepseek", "ollama"}:
            prompt = _build_full_control_prompt(root, current, human_instruction, full_control_scope)
            plan_result = _provider_patch_plan(provider, model, prompt)
            round_payload["ai"] = plan_result
            if not plan_result.get("ok"):
                round_payload["error"] = plan_result.get("error") or "AI provider did not return a usable patch plan."
                # Still try deterministic known fixes for obvious framework blockers.
                safe = _safe_apply_known_typescript_fixes(root, errors)
                round_payload["safe_patch_fallback"] = safe
            else:
                plan = _extract_json_object(plan_result.get("raw_text") or "")
                round_payload["patch_plan"] = plan or {"error": "provider returned non-JSON text"}
                applied = _apply_json_replacements(root, plan, impacted, full_control_scope)
                round_payload["json_patch_apply"] = applied
                if not applied.get("changed_files"):
                    safe = _safe_apply_known_typescript_fixes(root, errors)
                    round_payload["safe_patch_fallback"] = safe
        elif provider == "rule_based":
            safe = _safe_apply_known_typescript_fixes(root, errors)
            round_payload["safe_patch"] = safe
        else:
            round_payload["error"] = f"Unsupported provider: {provider}"
            result["rounds"].append(round_payload)
            break

        # Detect changed files against backup or previous state for this round.
        changed: set[str] = set()
        for key in ("json_patch_apply", "safe_patch_fallback", "safe_patch"):
            item = round_payload.get(key)
            if isinstance(item, dict):
                changed.update(str(x) for x in (item.get("changed_files") or []))
        for rel in sorted(impacted):
            path = root / rel
            old = Path(backup.get("backup_root") or "") / rel
            try:
                if path.exists() and old.exists() and path.read_bytes() != old.read_bytes():
                    changed.add(rel)
            except Exception:
                pass
        round_payload["changed_files"] = sorted(changed)
        result["changed_files"] = sorted(set(result.get("changed_files") or []) | changed)

        current = run_mcp_readiness_preflight(str(root), project=project, browser=browser, run_build=True, run_test_list=(round_no == max_rounds), check_browser=False)
        round_payload["preflight_after"] = current
        round_payload["ok_after_round"] = bool(current.get("ok"))
        round_payload["message"] = "Round fixed readiness issues." if current.get("ok") else "Round completed but issues remain."
        result["rounds"].append(round_payload)
        if current.get("ok"):
            break
        if not round_payload.get("changed_files"):
            # Avoid endless AI calls when no patch was applied.
            break

    final = run_mcp_readiness_preflight(str(root), project=project, browser=browser, run_build=True, run_test_list=True, check_browser=True)
    result["preflight_after"] = final
    result["ok"] = bool(final.get("ok"))
    if result["ok"]:
        result["message"] = "AI full-control framework fix updated files and MCP readiness now passes. Review changed_files and commit only after human review."
    elif result.get("changed_files"):
        result["message"] = "AI full-control framework fix changed files, but issues remain. Review changed_files, remaining errors, and rerun after adding human guidance."
    else:
        result["message"] = "AI full-control framework fix could not safely change files. Review provider connectivity, patch plan, or provide human guidance."
    result["report_files"] = _write_full_control_report(root, result)
    return result
