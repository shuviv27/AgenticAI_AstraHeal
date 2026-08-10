from __future__ import annotations

import json
import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from qa_pipeline.core.commands import run_command

Progress = Callable[[str, int, str, dict[str, Any] | None], None]


def _emit(progress: Progress | None, stage: str, pct: int, message: str, details: dict[str, Any] | None = None) -> None:
    if progress:
        progress(stage, pct, message, details)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace")), "ok"
    except Exception as exc:
        return None, f"invalid_json: {type(exc).__name__}: {exc}"


def _find_config(root: Path) -> Path | None:
    for name in ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs"):
        p = root / name
        if p.exists():
            return p
    found = list(root.glob("**/playwright.config.*"))
    return next((p for p in found if "node_modules" not in p.parts), None)


def _discover_test_dir(root: Path) -> str:
    candidates = ["tests", "test", "src/test/specs", "src/tests", "e2e", "specs"]
    for rel in candidates:
        p = root / rel
        if p.exists() and any(p.rglob("*.spec.ts")):
            return rel.replace("\\", "/")
    specs = [p for p in root.rglob("*.spec.ts") if "node_modules" not in p.parts]
    if specs:
        try:
            common = Path(os.path.commonpath([str(p.parent) for p in specs]))
            return str(common.relative_to(root)).replace("\\", "/")
        except Exception:
            pass
    return "tests"


def analyze_playwright_gaps(framework_path: str | Path) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    gaps: list[dict[str, Any]] = []
    suggestions: list[str] = []
    package_path = root / "package.json"
    tsconfig_path = root / "tsconfig.json"
    config_path = _find_config(root)
    package, package_status = _load_json(package_path)
    tsconfig, tsconfig_status = _load_json(tsconfig_path)

    if package_status != "ok":
        gaps.append({"code": "package_json_missing_or_invalid", "severity": "critical", "file": str(package_path), "details": package_status, "auto_fixable": True})
    else:
        scripts = package.get("scripts") or {}
        dev = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
        if "@playwright/test" not in dev and "playwright" not in dev:
            gaps.append({"code": "playwright_dependency_missing", "severity": "critical", "file": "package.json", "auto_fixable": True})
        if "typescript" not in dev:
            gaps.append({"code": "typescript_dependency_missing", "severity": "high", "file": "package.json", "auto_fixable": True})
        if not scripts.get("build"):
            gaps.append({"code": "npm_build_script_missing", "severity": "high", "file": "package.json", "auto_fixable": True, "recommended": "tsc --noEmit"})
        if not scripts.get("test") and not scripts.get("test:e2e"):
            suggestions.append("Add a test script such as 'playwright test' for easier CI and human execution.")

    if tsconfig_status != "ok":
        gaps.append({"code": "tsconfig_missing_or_invalid", "severity": "critical", "file": str(tsconfig_path), "details": tsconfig_status, "auto_fixable": True})
    else:
        compiler = tsconfig.get("compilerOptions") or {}
        ignore_deprecations = str(compiler.get("ignoreDeprecations") or "")
        if ignore_deprecations and not re.fullmatch(r"(?:5\.0|5\.5|6\.0)", ignore_deprecations):
            gaps.append({"code": "invalid_ignore_deprecations", "severity": "high", "file": "tsconfig.json", "value": ignore_deprecations, "auto_fixable": True})
        if not compiler.get("moduleResolution"):
            suggestions.append("Set compilerOptions.moduleResolution explicitly (usually 'Node' or 'Bundler') when path aliases are used.")
        if compiler.get("paths") and not compiler.get("baseUrl"):
            gaps.append({"code": "paths_without_base_url", "severity": "high", "file": "tsconfig.json", "auto_fixable": True})

    if config_path is None:
        gaps.append({"code": "playwright_config_missing", "severity": "critical", "file": "playwright.config.ts", "auto_fixable": True})
    else:
        text = config_path.read_text(encoding="utf-8", errors="replace")
        if "defineConfig" not in text:
            suggestions.append("Use defineConfig from @playwright/test for typed, clearer Playwright configuration.")
        if "testDir" not in text:
            gaps.append({"code": "playwright_test_dir_missing", "severity": "medium", "file": str(config_path), "auto_fixable": True, "recommended": _discover_test_dir(root)})
        if re.search(r"workers\s*:\s*1\b", text):
            suggestions.append("workers: 1 disables local parallelism. Keep it only for debugging; use environment-driven workers for distributed execution.")

    commands = [
        "npm config set registry https://registry.npmjs.org/",
        "npm install --registry=https://registry.npmjs.org/",
        "npx playwright install chromium",
        "npm run build",
    ]
    return {
        "ok": root.exists() and root.is_dir(),
        "framework_path": str(root),
        "is_playwright": bool(config_path or (package and ("@playwright/test" in json.dumps(package) or "playwright" in json.dumps(package)))),
        "package_json": {"path": str(package_path), "status": package_status},
        "tsconfig": {"path": str(tsconfig_path), "status": tsconfig_status},
        "playwright_config": str(config_path) if config_path else "",
        "discovered_test_dir": _discover_test_dir(root),
        "gaps": gaps,
        "gap_count": len(gaps),
        "critical_gap_count": len([g for g in gaps if g.get("severity") == "critical"]),
        "suggestions": suggestions,
        "required_commands": commands,
        "message": f"Playwright framework gap analysis found {len(gaps)} concrete gap(s)." if gaps else "No structural Playwright configuration gaps were found.",
    }


def apply_safe_config_fixes(framework_path: str | Path, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    analysis = analysis or analyze_playwright_gaps(root)
    changed: list[str] = []
    backups: list[str] = []

    def backup(path: Path) -> None:
        if path.exists():
            b = path.with_suffix(path.suffix + ".astraheal.bak")
            shutil.copy2(path, b)
            backups.append(str(b))

    package_path = root / "package.json"
    package, status = _load_json(package_path)
    if status == "missing":
        package = {"name": root.name.lower().replace(" ", "-"), "private": True, "scripts": {}, "devDependencies": {}}
    if package is not None:
        original = deepcopy(package)
        package.setdefault("scripts", {})
        package.setdefault("devDependencies", {})
        package["scripts"].setdefault("build", "tsc --noEmit")
        package["scripts"].setdefault("test", "playwright test")
        package["devDependencies"].setdefault("@playwright/test", "latest")
        package["devDependencies"].setdefault("typescript", "latest")
        if package != original or not package_path.exists():
            backup(package_path)
            package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
            changed.append("package.json")

    tsconfig_path = root / "tsconfig.json"
    tsconfig, status = _load_json(tsconfig_path)
    if tsconfig is None:
        tsconfig = {"compilerOptions": {"target": "ES2022", "module": "commonjs", "moduleResolution": "Node", "strict": True, "esModuleInterop": True, "resolveJsonModule": True, "skipLibCheck": True, "noEmit": True}, "include": ["**/*.ts"]}
    original_ts = deepcopy(tsconfig)
    compiler = tsconfig.setdefault("compilerOptions", {})
    if compiler.get("paths") and not compiler.get("baseUrl"):
        compiler["baseUrl"] = "."
    ignore = str(compiler.get("ignoreDeprecations") or "")
    if ignore and not re.fullmatch(r"(?:5\.0|5\.5|6\.0)", ignore):
        compiler.pop("ignoreDeprecations", None)
    compiler.setdefault("skipLibCheck", True)
    compiler.setdefault("noEmit", True)
    if tsconfig != original_ts or not tsconfig_path.exists():
        backup(tsconfig_path)
        tsconfig_path.write_text(json.dumps(tsconfig, indent=2) + "\n", encoding="utf-8")
        changed.append("tsconfig.json")

    config = _find_config(root)
    test_dir = analysis.get("discovered_test_dir") or _discover_test_dir(root)
    if config is None:
        config = root / "playwright.config.ts"
        config.write_text(
            "import { defineConfig, devices } from '@playwright/test';\n\n"
            "export default defineConfig({\n"
            f"  testDir: './{test_dir}',\n"
            "  fullyParallel: true,\n"
            "  forbidOnly: !!process.env.CI,\n"
            "  retries: process.env.CI ? 1 : 0,\n"
            "  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : undefined,\n"
            "  reporter: [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],\n"
            "  use: { baseURL: process.env.BASE_URL || process.env.TEST_BASE_URL, trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'retain-on-failure' },\n"
            "  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],\n"
            "});\n",
            encoding="utf-8",
        )
        changed.append("playwright.config.ts")
    else:
        text = config.read_text(encoding="utf-8", errors="replace")
        if "testDir" not in text and "defineConfig" in text:
            backup(config)
            text = re.sub(r"defineConfig\(\s*\{", f"defineConfig({{\n  testDir: './{test_dir}',", text, count=1)
            config.write_text(text, encoding="utf-8")
            changed.append(str(config.relative_to(root)).replace("\\", "/"))

    return {"ok": True, "changed_files": changed, "backups": backups, "message": "Safe Playwright configuration fixes applied." if changed else "No safe configuration changes were required."}


def run_required_commands(framework_path: str | Path, *, progress: Progress | None = None, stop_on_failure: bool = False) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    commands = [
        (["npm", "config", "set", "registry", "https://registry.npmjs.org/"], 15, "Setting npm registry"),
        (["npm", "install", "--registry=https://registry.npmjs.org/"], 35, "Installing npm dependencies"),
        (["npx", "playwright", "install", "chromium"], 60, "Installing Playwright Chromium"),
        (["npm", "run", "build"], 82, "Running TypeScript/build validation"),
    ]
    results = []
    env = {"npm_config_registry": "https://registry.npmjs.org/", "PLAYWRIGHT_HTML_OPEN": "never"}
    for args, pct, title in commands:
        _emit(progress, "playwright_doctor", pct, title, {"command": args})
        timeout = 1200 if "install" in args else 300
        result = run_command(args, cwd=root, timeout=timeout, extra_env=env)
        item = {"ok": result.ok, "command": result.command, "return_code": result.returncode, "stdout_tail": result.stdout[-12000:], "stderr_tail": result.stderr[-12000:], "error": result.error}
        results.append(item)
        if not result.ok and stop_on_failure:
            break
    ok = all(r.get("ok") for r in results) and len(results) == len(commands)
    _emit(progress, "playwright_doctor", 100, "Playwright prerequisite command sequence completed." if ok else "Playwright command sequence completed with blockers.", {"ok": ok})
    return {"ok": ok, "framework_path": str(root), "commands": results, "message": "All requested Playwright commands passed." if ok else "One or more requested Playwright commands failed. Review exact stdout/stderr; no success is assumed."}


def diagnose_and_prepare(framework_path: str | Path, *, apply_fixes: bool = False, run_commands: bool = True, progress: Progress | None = None) -> dict[str, Any]:
    analysis = analyze_playwright_gaps(framework_path)
    _emit(progress, "playwright_doctor", 8, analysis.get("message", "Gap analysis completed."), {"gap_count": analysis.get("gap_count")})
    fixes = {"ok": True, "changed_files": [], "message": "Fix mode disabled."}
    if apply_fixes:
        fixes = apply_safe_config_fixes(framework_path, analysis)
        _emit(progress, "playwright_doctor", 12, fixes.get("message", "Safe fixes completed."), {"changed_files": fixes.get("changed_files")})
        analysis = analyze_playwright_gaps(framework_path)
    commands = {"ok": True, "commands": [], "message": "Command execution disabled."}
    if run_commands and analysis.get("is_playwright"):
        commands = run_required_commands(framework_path, progress=progress)
    final_analysis = analyze_playwright_gaps(framework_path)
    return {"ok": bool(commands.get("ok") and final_analysis.get("critical_gap_count", 0) == 0), "analysis_before": analysis, "safe_fixes": fixes, "command_validation": commands, "analysis_after": final_analysis, "message": "Playwright framework preparation passed." if commands.get("ok") and final_analysis.get("critical_gap_count", 0) == 0 else "Playwright framework still has validated blockers. Review the gap and command evidence before execution."}
