from __future__ import annotations

from pathlib import Path

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, ensure_dirs


def run_review(skip_npm: bool = False) -> dict:
    ensure_dirs()
    report = {
        "generated_playwright_dir": str(GENERATED_PLAYWRIGHT_DIR),
        "checks": [],
        "ok": True,
    }
    required = [
        GENERATED_PLAYWRIGHT_DIR / "pageObjects",
        GENERATED_PLAYWRIGHT_DIR / "pages",
        GENERATED_PLAYWRIGHT_DIR / "tests" / "generated",
        GENERATED_PLAYWRIGHT_DIR / "utils" / "locatorFactory.ts",
        GENERATED_PLAYWRIGHT_DIR / "pages" / "BasePage.ts",
    ]
    for path in required:
        ok = path.exists()
        report["checks"].append({"name": f"exists:{path.relative_to(GENERATED_PLAYWRIGHT_DIR)}", "ok": ok})
        report["ok"] = report["ok"] and ok

    # Check that generated specs do not inline locators.
    forbidden = ["getByTestId(", "getByRole(", "locator(", "xpath="]
    for spec in (GENERATED_PLAYWRIGHT_DIR / "tests" / "generated").glob("*.spec.ts"):
        text = spec.read_text(encoding="utf-8")
        hits = [f for f in forbidden if f in text]
        ok = not hits
        report["checks"].append({"name": f"no-inline-locators:{spec.name}", "ok": ok, "hits": hits})
        report["ok"] = report["ok"] and ok

    npm_available = resolve_command("npm") is not None
    node_modules_exists = (GENERATED_PLAYWRIGHT_DIR / "node_modules").exists()
    if not skip_npm and node_modules_exists and npm_available:
        proc = run_command(["npm", "--prefix", str(GENERATED_PLAYWRIGHT_DIR), "run", "build"], timeout=120)
        ok = proc.ok
        report["checks"].append({
            "name": "typescript-build",
            "ok": ok,
            "command": proc.command,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "error": proc.error,
        })
        report["ok"] = report["ok"] and ok
    else:
        reason = []
        if skip_npm:
            reason.append("--skip-npm used")
        if not node_modules_exists:
            reason.append("generated-playwright/node_modules missing; run npm install inside generated-playwright")
        if not npm_available:
            reason.append("npm command not found in PATH; install Node.js LTS with npm or fix PATH")
        report["checks"].append({"name": "typescript-build", "ok": True, "skipped": True, "reason": "; ".join(reason)})

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    import json
    (REPORTS_DIR / "quality-review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_smoke() -> int:
    if resolve_command("npm") is None:
        print("npm command not found. Install Node.js LTS with npm or fix PATH, then rerun smoke.")
        return 2
    proc = run_command(["npm", "--prefix", str(GENERATED_PLAYWRIGHT_DIR), "run", "smoke"], timeout=300)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    if proc.error:
        print(proc.error)
    return proc.returncode or 0
