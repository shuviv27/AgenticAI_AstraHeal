from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.agents.existing_framework_control.structure_discovery import build_structure_profile
from qa_pipeline.core.paths import REPORTS_DIR
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.openai_compatible import OpenAICompatibleProvider
from qa_pipeline.llm.ollama import OllamaProvider


_TS_ERROR_RE = re.compile(
    r"^(?P<file>.*?\.(?:ts|tsx|js|jsx))(?:\:(?P<line>\d+)\:(?P<col>\d+)\s+-\s+error|\((?P<line2>\d+),(?P<col2>\d+)\)\s*:\s+error)\s+(?P<code>TS\d+):\s+(?P<message>.*)$",
    re.MULTILINE,
)


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def _framework_reports_dir(root: Path) -> Path:
    p = root / ".aiqa-history" / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _solution_reports_dir() -> Path:
    p = REPORTS_DIR / "existing-framework"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tail(value: str, limit: int = 12000) -> str:
    value = value or ""
    return value[-limit:]


def _read_package_json(root: Path) -> tuple[dict[str, Any] | None, str]:
    package_file = root / "package.json"
    if not package_file.exists():
        return None, "package.json not found in framework root. Select the correct Playwright framework folder."
    try:
        return json.loads(package_file.read_text(encoding="utf-8", errors="replace")), ""
    except Exception as exc:
        return None, f"package.json exists but could not be parsed: {type(exc).__name__}: {exc}"


def extract_typescript_errors(output: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for m in _TS_ERROR_RE.finditer(output or ""):
        line = m.group("line") or m.group("line2") or 0
        col = m.group("col") or m.group("col2") or 0
        errors.append({
            "file": (m.group("file") or "").replace("\\", "/"),
            "line": int(line or 0),
            "column": int(col or 0),
            "code": m.group("code") or "",
            "message": (m.group("message") or "").strip(),
        })
    return errors


def _write_report(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    title = "MCP Readiness Preflight"
    status = "PASS" if payload.get("ok") else ("ACTION REQUIRED" if payload.get("action_required") else "WARNING")
    checks = payload.get("checks") or {}
    errors = payload.get("typescript_errors") or []
    recommended = payload.get("recommended_user_message") or payload.get("message") or ""

    def check_row(name: str, data: Any) -> str:
        if not isinstance(data, dict):
            data = {"value": data}
        ok = data.get("ok")
        badge = "PASS" if ok is True else ("FAIL" if ok is False else "INFO")
        cls = "ok" if ok is True else ("bad" if ok is False else "info")
        msg = html.escape(str(data.get("message") or data.get("error") or data.get("value") or ""))
        return f"<tr><td>{html.escape(name)}</td><td><span class='{cls}'>{badge}</span></td><td>{msg}</td></tr>"

    err_rows = "".join(
        f"<tr><td>{html.escape(str(e.get('file','')))}</td><td>{e.get('line','')}</td><td>{html.escape(str(e.get('code','')))}</td><td>{html.escape(str(e.get('message','')))}</td></tr>"
        for e in errors
    ) or "<tr><td colspan='4'>No TypeScript errors parsed.</td></tr>"
    body_json = html.escape(json.dumps(payload, indent=2, ensure_ascii=False))
    html_text = f"""<!doctype html>
<html><head><meta charset='utf-8'/><title>{title}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#111827}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 1px 3px #0001}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #dbe3ef;padding:8px;text-align:left;vertical-align:top}}th{{background:#e2e8f0}}pre{{white-space:pre-wrap;background:#0f172a;color:#d1fae5;border-radius:10px;padding:14px;overflow:auto;max-height:520px}}.ok{{background:#dcfce7;color:#166534;padding:4px 8px;border-radius:999px;font-weight:700}}.bad{{background:#fee2e2;color:#991b1b;padding:4px 8px;border-radius:999px;font-weight:700}}.info{{background:#dbeafe;color:#1e40af;padding:4px 8px;border-radius:999px;font-weight:700}}.warn{{background:#fef3c7;color:#92400e;padding:4px 8px;border-radius:999px;font-weight:700}}
</style></head><body>
<h1>{title}</h1>
<div class='card'><h2>Status: <span class='{'ok' if payload.get('ok') else 'bad'}'>{html.escape(status)}</span></h2><p>{html.escape(recommended)}</p></div>
<div class='card'><h2>Checks</h2><table><tr><th>Check</th><th>Status</th><th>Message</th></tr>{''.join(check_row(k, v) for k, v in checks.items())}</table></div>
<div class='card'><h2>Parsed TypeScript Errors</h2><table><tr><th>File</th><th>Line</th><th>Code</th><th>Message</th></tr>{err_rows}</table></div>
<div class='card'><h2>Next actions shown to user</h2><ul>{''.join('<li>'+html.escape(str(x))+'</li>' for x in (payload.get('next_actions') or []))}</ul></div>
<div class='card'><h2>Raw JSON</h2><pre>{body_json}</pre></div>
</body></html>"""
    fdir = _framework_reports_dir(root)
    sdir = _solution_reports_dir()
    files = {
        "framework_html": str(fdir / "mcp-readiness-preflight.html"),
        "framework_json": str(fdir / "mcp-readiness-preflight.json"),
        "solution_html": str(sdir / "mcp-readiness-preflight.html"),
        "solution_json": str(sdir / "mcp-readiness-preflight.json"),
    }
    for key, path_s in files.items():
        p = Path(path_s)
        p.parent.mkdir(parents=True, exist_ok=True)
        if key.endswith("html"):
            p.write_text(html_text, encoding="utf-8")
        else:
            p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return files


def run_mcp_readiness_preflight(framework_path: str, project: str = "auto", browser: str = "chromium", run_build: bool = True, run_test_list: bool = True, check_browser: bool = True) -> dict[str, Any]:
    root = Path(framework_path or ".").expanduser()
    if not root.is_absolute():
        root = root.resolve()
    payload: dict[str, Any] = {
        "ok": False,
        "stage": "mcp_readiness_preflight",
        "framework_path": str(root),
        "checks": {},
        "typescript_errors": [],
        "next_actions": [],
    }
    if not root.exists() or not root.is_dir():
        payload["checks"]["framework_path"] = {"ok": False, "message": "Framework path does not exist or is not a folder."}
        payload["action_required"] = True
        payload["message"] = "MCP readiness preflight failed because the framework path is invalid."
        payload["recommended_user_message"] = "Please select the actual Playwright framework root folder and retry MCP assist."
        payload["next_actions"] = ["Correct the framework_path in GUI.", "Retry Prepare Playwright MCP assist."]
        payload["report_files"] = _write_report(root if root.exists() else Path.cwd(), payload)
        return payload

    payload["checks"]["framework_path"] = {"ok": True, "message": "Framework path exists."}
    try:
        structure_profile = build_structure_profile(root, limit=5000)
    except Exception as exc:
        structure_profile = {"ok": False, "executable_specs": [], "error": f"{type(exc).__name__}: {exc}"}
    payload["framework_structure"] = structure_profile
    payload["checks"]["deep_test_discovery"] = {
        "ok": bool(structure_profile.get("executable_specs")),
        "message": (
            f"Recursive structure scan found {len(structure_profile.get('executable_specs') or [])} executable Playwright spec file(s) "
            f"under {', '.join((structure_profile.get('discovered_test_roots') or [])[:8]) or 'content-proven custom locations'}."
            if structure_profile.get("executable_specs")
            else "Recursive structure scan did not find executable Playwright specs. Checked configured testDir, nested test folders and executable Playwright content."
        ),
        "discovered_test_roots": structure_profile.get("discovered_test_roots") or [],
        "sample_specs": (structure_profile.get("executable_specs") or [])[:30],
        "source_layout": structure_profile.get("source_layout") or {},
    }
    package, package_error = _read_package_json(root)
    if package is None:
        payload["checks"]["package_json"] = {"ok": False, "message": package_error}
        payload["action_required"] = True
        payload["message"] = "MCP readiness preflight cannot continue because package.json is missing or invalid."
        payload["recommended_user_message"] = package_error
        payload["next_actions"] = ["Select correct framework root folder.", "Cancel MCP prepare until package.json is available."]
        payload["report_files"] = _write_report(root, payload)
        return payload

    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    payload["checks"]["package_json"] = {"ok": True, "message": "package.json found and parsed."}
    payload["scripts"] = scripts
    npm_ok = resolve_command("npm") is not None
    npx_ok = resolve_command("npx") is not None
    payload["checks"]["npm"] = {"ok": npm_ok, "message": "npm found." if npm_ok else "npm not found. Install Node.js LTS and reopen terminal."}
    payload["checks"]["npx"] = {"ok": npx_ok, "message": "npx found." if npx_ok else "npx not found. Install Node.js LTS and reopen terminal."}
    if not npm_ok or not npx_ok:
        payload["action_required"] = True
        payload["message"] = "MCP readiness preflight failed because Node/npm/npx is unavailable."
        payload["recommended_user_message"] = "Install Node.js LTS on this VM/worker and reopen the terminal before preparing MCP assist."
        payload["next_actions"] = ["Install Node.js LTS.", "Run node -v, npm -v, npx --version.", "Retry MCP assist."]
        payload["report_files"] = _write_report(root, payload)
        return payload

    if run_build:
        if "build" in scripts:
            build = run_command(["npm", "run", "build"], cwd=root, timeout=240)
            build_text = (build.stdout or "") + "\n" + (build.stderr or "") + "\n" + (build.error or "")
            errors = extract_typescript_errors(build_text)
            payload["typescript_errors"] = errors
            payload["checks"]["npm_run_build"] = {
                "ok": build.ok,
                "message": "npm run build passed." if build.ok else f"npm run build failed with {len(errors) or 'unparsed'} TypeScript/build error(s).",
                "command": build.command,
                "returncode": build.returncode,
                "stdout_tail": _tail(build.stdout),
                "stderr_tail": _tail(build.stderr or build.error),
            }
            if not build.ok:
                payload["action_required"] = True
                payload["stage"] = "mcp_preflight_build_failed"
                payload["message"] = f"MCP assist cannot start cleanly because npm run build failed with {len(errors) or 'build'} error(s)."
                payload["recommended_user_message"] = "Framework TypeScript build failed. Choose Fix with selected AI provider to apply a focused readiness fix, Continue MCP without build only for exploratory evidence, or Cancel and fix manually."
                payload["next_actions"] = [
                    "Fix with selected AI provider: Codex applies direct patches; OpenAI/DeepSeek use API-key guidance plus safe local TypeScript fix application. Backup/history is always created.",
                    "Continue MCP without build: use only if you need exploratory browser evidence and accept that framework readiness is not clean.",
                    "Cancel: no MCP preparation and no file changes.",
                ]
                payload["report_files"] = _write_report(root, payload)
                return payload
        else:
            payload["checks"]["npm_run_build"] = {"ok": None, "message": "No build script in package.json. Skipped npm run build."}

    if run_test_list:
        args = ["npx", "playwright", "test", "--list"]
        if project and project != "auto":
            args.append(f"--project={project}")
        listing = run_command(args, cwd=root, timeout=180)
        listing_text = ((listing.stdout or "") + "\n" + (listing.stderr or "") + "\n" + (listing.error or "")).lower()
        default_has_tests = listing.ok and not any(marker in listing_text for marker in ("no tests found", "total: 0 test", "0 tests"))
        fallback = None
        effective_ok = default_has_tests
        discovered_specs = list((structure_profile or {}).get("executable_specs") or [])

        # Some enterprise frameworks have valid deep specs but a stale/mismatched
        # testDir. The selectable-test runner executes explicit paths, so verify
        # that same scope before blocking MCP preparation.
        if not default_has_tests and discovered_specs:
            fallback_args = ["npx", "playwright", "test", *discovered_specs[:25], "--list"]
            if project and project != "auto":
                fallback_args.append(f"--project={project}")
            fallback_run = run_command(fallback_args, cwd=root, timeout=180)
            fallback_text = ((fallback_run.stdout or "") + "\n" + (fallback_run.stderr or "") + "\n" + (fallback_run.error or "")).lower()
            fallback_ok = fallback_run.ok and not any(marker in fallback_text for marker in ("no tests found", "total: 0 test", "0 tests"))
            effective_ok = fallback_ok
            fallback = {
                "used": True,
                "ok": fallback_ok,
                "reason": "Default Playwright --list did not prove test discovery; retried with recursively discovered explicit specs.",
                "command": fallback_run.command,
                "returncode": fallback_run.returncode,
                "stdout_tail": _tail(fallback_run.stdout),
                "stderr_tail": _tail(fallback_run.stderr or fallback_run.error),
                "target_count": min(len(discovered_specs), 25),
            }

        payload["checks"]["playwright_test_list"] = {
            "ok": effective_ok,
            "default_config_ok": default_has_tests,
            "message": (
                "Playwright test listing passed using the framework default configuration."
                if default_has_tests
                else "Default Playwright discovery did not prove tests, but listing passed with recursively discovered explicit spec paths. Review testDir/testMatch alignment; selected execution remains available."
                if effective_ok
                else "Playwright could not list recursively discovered tests. Framework may have config/import/compile issues."
            ),
            "command": listing.command,
            "returncode": listing.returncode,
            "stdout_tail": _tail(listing.stdout),
            "stderr_tail": _tail(listing.stderr or listing.error),
            "recursive_discovery_fallback": fallback,
        }
        if not effective_ok:
            payload["action_required"] = True
            payload["stage"] = "mcp_preflight_test_list_failed"
            payload["message"] = "MCP assist cannot start cleanly because Playwright test discovery failed for both default configuration and recursive explicit targets."
            payload["recommended_user_message"] = "Playwright could not list the discovered tests. Choose Fix with selected AI provider for config/import/build repair, Continue MCP without build only for exploratory evidence, or Cancel."
            payload["next_actions"] = ["Fix framework config/import/test discovery issue.", "Review recursively discovered test roots in the preflight report.", "Retry MCP assist after listing passes."]
            payload["report_files"] = _write_report(root, payload)
            return payload

    if check_browser:
        dry = run_command(["npx", "playwright", "install", "--dry-run", browser or "chromium"], cwd=root, timeout=180)
        payload["checks"]["playwright_browser_check"] = {
            "ok": dry.ok,
            "message": "Playwright browser install dry-run passed." if dry.ok else f"Playwright browser check failed for {browser or 'chromium'}. Run npx playwright install {browser or 'chromium'}." ,
            "command": dry.command,
            "returncode": dry.returncode,
            "stdout_tail": _tail(dry.stdout, 4000),
            "stderr_tail": _tail(dry.stderr or dry.error, 4000),
        }
        if not dry.ok:
            payload["action_required"] = True
            payload["stage"] = "mcp_preflight_browser_check_failed"
            payload["message"] = "MCP assist cannot start cleanly because Playwright browser readiness check failed."
            payload["recommended_user_message"] = f"Run npx playwright install {browser or 'chromium'} on the VM/worker where browser execution happens, then retry."
            payload["next_actions"] = [f"Run npx playwright install {browser or 'chromium'}.", "Retry MCP assist."]
            payload["report_files"] = _write_report(root, payload)
            return payload

    payload["ok"] = True
    payload["action_required"] = False
    payload["stage"] = "mcp_readiness_preflight_passed"
    payload["message"] = "MCP readiness preflight passed. package.json, build/list/browser checks are ready enough for MCP assist."
    payload["recommended_user_message"] = "MCP assist can proceed. Playwright Test remains the deterministic runner; MCP provides browser/accessibility evidence for RCA/self-healing."
    payload["next_actions"] = ["Continue with Playwright MCP assist.", "Run failed element RCA if a test has failed."]
    payload["report_files"] = _write_report(root, payload)
    return payload


def _backup_files(root: Path, files: list[str]) -> dict[str, Any]:
    stamp = _now_id()
    backup_root = root / ".aiqa-history" / "backups" / f"mcp-build-fix-{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    copied = []
    skipped = []
    for rel in sorted(set(files)):
        rel_norm = rel.replace("\\", "/").lstrip("/")
        src = root / rel_norm
        if not src.exists() or not src.is_file():
            skipped.append(rel_norm)
            continue
        dest = backup_root / rel_norm
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(rel_norm)
    return {"backup_root": str(backup_root), "copied": copied, "skipped": skipped}




def _escape_regex_literal(value: str) -> str:
    return re.escape(value or "").replace("/", r"\/")


def _safe_apply_known_typescript_fixes(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply narrowly-scoped TypeScript readiness fixes for known MCP blockers.

    This is intentionally conservative. It only edits files already reported by
    tsc and only for well-known TypeScript-safe patterns observed in Playwright
    page objects. It never skips tests or weakens assertions.
    """
    changed: list[str] = []
    notes: list[str] = []
    blocked: list[str] = []
    files = sorted({str(e.get("file") or "").replace("\\", "/") for e in errors if e.get("file")})
    for rel in files:
        path = root / rel
        try:
            original = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            blocked.append(f"{rel}: could not read file: {exc}")
            continue
        updated = original

        # TS2339: Element.offsetParent. Cast the exact variable used before offsetParent.
        updated = re.sub(r"!([A-Za-z_$][\w$]*)\.offsetParent\b", r"!(\1 as HTMLElement).offsetParent", updated)
        updated = re.sub(r"\b([A-Za-z_$][\w$]*)\.offsetParent\b", r"(\1 as HTMLElement).offsetParent", updated)
        if updated != original:
            notes.append(f"{rel}: added HTMLElement cast for offsetParent usage.")

        before = updated
        # TS18046: catch variable is unknown. Keep template literals intact with a safe inline conversion.
        catch_vars = set()
        for e in errors:
            if str(e.get("file") or "").replace("\\", "/") != rel:
                continue
            msg = str(e.get("message") or e.get("text") or "")
            if "is of type 'unknown'" not in msg:
                continue
            m = re.search(r"'([^']+)'\s+is of type 'unknown'", msg)
            if m:
                catch_vars.add(m.group(1))
        for var in sorted(catch_vars):
            updated = re.sub(r"\$\{\s*" + re.escape(var) + r"\.message\s*\}", "${" + var + " instanceof Error ? " + var + ".message : String(" + var + ")}", updated)
        if updated != before:
            notes.append(f"{rel}: converted unknown catch error.message usage to safe Error/String conversion.")

        before = updated
        # Playwright locator misuse: page.locator("text=a", "text=b") passes selector as options.
        def repl_locator(match: re.Match[str]) -> str:
            prefix, first, second = match.group(1), match.group(2), match.group(3)
            base = first.replace("text=", "").strip() or second.replace("text=", "").strip()
            return f"{prefix}.getByText(/{_escape_regex_literal(base)}/i)"
        updated = re.sub(r"(\b(?:this\.)?page)\.locator\(\s*\"(text=[^\"]+)\"\s*,\s*\"(text=[^\"]+)\"\s*\)", repl_locator, updated)
        if updated != before:
            notes.append(f"{rel}: replaced invalid page.locator(selector, selector) with getByText(/.../i).")

        if updated != original:
            try:
                path.write_text(updated, encoding="utf-8")
                changed.append(rel)
            except Exception as exc:
                blocked.append(f"{rel}: could not write file: {exc}")
    return {"changed_files": changed, "notes": notes, "blocked": blocked}


def _provider_guidance(provider: str, model: str, prompt: str) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    if provider in {"openai", "deepseek", "perplexity"}:
        result = OpenAICompatibleProvider(provider=provider, model=model or "").chat(
            prompt,
            system="You are a senior Playwright TypeScript automation engineer. Return minimal, auditable fix guidance only. Do not suggest skipping tests.",
        )
        return {"provider": provider, "ok": bool(result.ok), "text": result.text if result.ok else "", "error": result.error if not result.ok else "", "mode": "api_key_no_login"}
    if provider == "ollama":
        result = OllamaProvider(model=model or "llama3").chat(
            prompt,
            system="You are a senior Playwright TypeScript automation engineer. Return minimal, auditable fix guidance only. Do not suggest skipping tests.",
        )
        return {"provider": provider, "ok": bool(result.ok), "text": result.text if result.ok else "", "error": result.error if not result.ok else "", "mode": "local_model"}
    return {"provider": provider, "ok": False, "text": "", "error": f"Provider {provider!r} does not support API guidance for this action.", "mode": "unsupported"}

def fix_mcp_preflight_build_errors_with_ai(framework_path: str, provider: str = "codex", model: str = "", project: str = "auto", browser: str = "chromium", human_instruction: str = "") -> dict[str, Any]:
    root = Path(framework_path or ".").expanduser()
    if not root.is_absolute():
        root = root.resolve()
    pre = run_mcp_readiness_preflight(str(root), project=project, browser=browser, run_build=True, run_test_list=False, check_browser=False)
    provider = (provider or "codex").strip().lower()
    if provider == "deterministic":
        provider = "rule_based"
    errors = pre.get("typescript_errors") or []
    files = [str(e.get("file")) for e in errors if e.get("file")]
    backup = _backup_files(root, files)
    result: dict[str, Any] = {
        "ok": False,
        "stage": "mcp_preflight_ai_fix",
        "provider": provider,
        "provider_routing": {
            "selected_provider": provider,
            "codex_forced": False,
            "explanation": "The selected GUI provider is used for this action. Codex is used only when provider=codex. OpenAI/DeepSeek use API keys; no interactive login is required.",
        },
        "framework_path": str(root),
        "preflight_before": pre,
        "backup": backup,
        "changed_files": [],
    }
    if not errors and not pre.get("action_required"):
        result.update({"ok": True, "message": "No build errors found. MCP preflight is already clean."})
        result["report_files"] = _write_report(root, {**result, "checks": {"ai_fix": {"ok": True, "message": result["message"]}}, "typescript_errors": []})
        return result

    error_block = json.dumps(errors, indent=2, ensure_ascii=False)
    build_check = (pre.get("checks", {}).get("npm_run_build", {}) or {})
    build_output_tail = (build_check.get("stdout_tail", "") + chr(10) + build_check.get("stderr_tail", ""))
    build_output_block = json.dumps(build_output_tail, ensure_ascii=False)[:12000]
    base_prompt = f"""
You are helping fix MCP readiness for an existing enterprise Playwright TypeScript automation framework.

Task: Fix only the TypeScript/build errors that block MCP readiness. Do not refactor unrelated files.

Strict rules:
- Modify only the files listed in the TypeScript errors unless a direct import/type helper in the same framework layer is absolutely required.
- Do not add test.skip, test.only, test.fixme, or weaken assertions to hide failures.
- Do not remove business validation.
- Preserve existing Page Object Model and framework style.
- Prefer minimal TypeScript-safe fixes.
- For Element.offsetParent errors, cast Element to HTMLElement before using offsetParent.
- For catch variables of type unknown, convert safely with: const message = error instanceof Error ? error.message : String(error)
- For page.locator("a", "b") misuse, use getByText(/.../i) or locator().or(...) as appropriate.

Human instruction, if any:
{human_instruction or "No extra human instruction."}

Parsed TypeScript errors:
{error_block}

Build output tail:
{build_output_block}
""".strip()

    if provider == "codex":
        codex = CodexCliProvider(root, timeout_seconds=600)
        if not codex.is_available():
            result.update({
                "ok": False,
                "message": "Codex was selected, but Codex CLI is not available or not authenticated on this VM. Select OpenAI/DeepSeek for API-key guidance + safe known TypeScript fixes, or complete Fresh AI login for Codex.",
                "next_actions": ["Run Fresh AI login for Codex, then retry.", "Or select DeepSeek/OpenAI and retry Fix with selected AI provider.", "Or fix the listed TypeScript errors manually."],
            })
            result["report_files"] = _write_report(root, {**result, "checks": {"codex": {"ok": False, "message": result["message"]}}, "typescript_errors": errors})
            return result
        ai = codex.run(base_prompt + "\n\nApply the minimal patch directly in the repository. Do not print unrelated explanations.")
        result["ai"] = {"ok": ai.ok, "provider": "codex", "stdout": _tail(ai.stdout, 16000), "stderr": _tail(ai.stderr, 16000), "exit_code": ai.exit_code, "mode": "cli_login_required"}
    elif provider in {"openai", "deepseek", "ollama"}:
        guidance = _provider_guidance(provider, model, base_prompt + "\n\nReturn clear patch guidance for the listed files. The local safe patcher will only apply known TypeScript-safe patterns.")
        result["ai"] = guidance
        if not guidance.get("ok"):
            result.update({
                "ok": False,
                "message": f"{provider} was selected, but it is not ready for this action: {guidance.get('error')}. API providers use API keys, not Codex login. Save the {provider} key/base URL/model in GUI or .env and retry.",
                "next_actions": [f"Verify {provider} API key/base URL/model in AI connection.", "Click Save AI provider config for this GUI session.", "Click Check AI status.", "Retry Fix with selected AI provider."],
            })
            result["report_files"] = _write_report(root, {**result, "checks": {"api_provider": {"ok": False, "message": result["message"]}}, "typescript_errors": errors})
            return result
        patch_result = _safe_apply_known_typescript_fixes(root, errors)
        result["safe_patch_applier"] = patch_result
    elif provider == "rule_based":
        patch_result = _safe_apply_known_typescript_fixes(root, errors)
        result["ai"] = {"ok": True, "provider": "rule_based", "text": "Rule-based safe TypeScript readiness fixes were attempted. No external AI provider was used.", "mode": "no_ai"}
        result["safe_patch_applier"] = patch_result
    else:
        result.update({
            "ok": False,
            "message": f"Unsupported MCP fix provider: {provider}. Select Codex, OpenAI, DeepSeek, Ollama, or Rule-based only.",
            "next_actions": ["Select a supported provider in AI connection.", "Save AI provider config.", "Retry Fix with selected AI provider."],
        })
        result["report_files"] = _write_report(root, {**result, "checks": {"ai_fix": {"ok": False, "message": result["message"]}}, "typescript_errors": errors})
        return result

    changed = []
    for rel in backup.get("copied") or []:
        src = root / rel
        old = Path(backup["backup_root"]) / rel
        try:
            if src.exists() and old.exists() and src.read_bytes() != old.read_bytes():
                changed.append(rel)
        except Exception:
            pass
    result["changed_files"] = sorted(set(changed + (result.get("safe_patch_applier", {}).get("changed_files") or [])))
    after = run_mcp_readiness_preflight(str(root), project=project, browser=browser, run_build=True, run_test_list=True, check_browser=True)
    result["preflight_after"] = after
    result["ok"] = bool(after.get("ok"))

    if result["ok"]:
        if provider == "codex":
            result["message"] = "Codex fixed the MCP readiness build/list issue and MCP preflight now passes. You can prepare MCP assist again."
        elif provider in {"openai", "deepseek", "ollama"}:
            result["message"] = f"{provider} was used for API-key guidance and safe TypeScript fixes were applied locally. MCP preflight now passes. No Codex login was used."
        else:
            result["message"] = "Rule-based safe TypeScript fixes were applied and MCP preflight now passes."
    elif result.get("changed_files"):
        result["message"] = f"{provider} attempted MCP readiness fixes and changed files, but issues remain. Review changed_files, remaining TypeScript errors, and the MCP readiness report."
    else:
        result["message"] = f"{provider} attempted MCP readiness guidance/fix, but no safe file changes were applied and issues remain. Review the report or provide human guidance."
    result["report_files"] = _write_report(root, {**result, "checks": {"ai_fix": {"ok": result["ok"], "message": result["message"]}}, "typescript_errors": (after.get("typescript_errors") or errors)})
    return result
