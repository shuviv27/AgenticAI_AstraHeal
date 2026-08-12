from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from qa_pipeline.agentic.code_graph import build_code_graph
from qa_pipeline.agentic.graph import fix_node, playwright_gap_node, run_fallback
from qa_pipeline.agentic.memory import get_run
from qa_pipeline.agentic.runtime import start_run
from qa_pipeline.agentic.playwright_doctor import (
    analyze_playwright_gaps,
    build_safe_config_change_plan,
    run_required_commands,
)
from qa_pipeline.agents.existing_framework_control.controller import analyze_existing_framework


def _framework(root: Path) -> Path:
    (root / "tests").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "approval-test",
                "private": True,
                "scripts": {"test:ui": "playwright test"},
                "devDependencies": {"@playwright/test": "1.50.0", "typescript": "5.7.0"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text(
        '{\n  // enterprise JSONC is valid for TypeScript\n  "compilerOptions": {"target": "ES2022", "moduleResolution": "node",},\n  "include": ["tests/**/*.ts"],\n}\n',
        encoding="utf-8",
    )
    (root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\nexport default defineConfig({ testDir: './tests' });\n",
        encoding="utf-8",
    )
    (root / "tests" / "smoke.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\ntest('smoke', async () => { expect(1).toBe(1); });\n",
        encoding="utf-8",
    )
    return root


def test_jsonc_tsconfig_is_understood_and_only_real_gap_is_proposed(tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    gaps = analyze_playwright_gaps(root)
    assert [x["code"] for x in gaps["gaps"]] == ["npm_build_script_missing"]
    proposal = build_safe_config_change_plan(root, gaps)
    assert set(proposal["proposed_files"]) == {"package.json", ".astraheal-playwright-standard.json"}


def test_framework_analysis_and_code_graph_reuse_project_local_cache(tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    first = analyze_existing_framework(str(root), provider="deterministic", reuse_cache=True)
    second = analyze_existing_framework(str(root), provider="deterministic", reuse_cache=True)
    assert not bool(first.get("cache_hit"))
    assert bool(second.get("cache_hit") or (second.get("cache_reuse") or {}).get("used"))
    assert (root / ".qa-cache" / "existing-framework" / "framework-analysis-cache.json").exists()

    graph1 = build_code_graph(str(root), use_graphify=False)
    graph2 = build_code_graph(str(root), use_graphify=False)
    assert graph1["node_count"] > 0
    assert graph2.get("cache_hit") is True
    assert (root / ".qa-cache" / "existing-framework" / "code-graph-cache.json").exists()


def test_framework_fix_requires_exact_file_approval_before_write(tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    original = (root / "package.json").read_text(encoding="utf-8")
    gaps = {
        **__import__("qa_pipeline.agentic.playwright_doctor", fromlist=["diagnose_and_prepare"]).diagnose_and_prepare(
            root, apply_fixes=False, run_commands=False
        )
    }
    proposal_state = {
        "run_id": "proposal-run",
        "workflow": "framework_fix",
        "framework_path": str(root),
        "provider": "deterministic",
        "model": "",
        "input_payload": {"standard_profile": "astraheal-adaptive-enterprise-v1"},
        "gap_report": gaps,
        "approved": False,
        "completed_agents": [],
        "step_count": 0,
    }
    proposed = fix_node(proposal_state)
    assert proposed["approval_required"] is True
    approval = proposed["approval_payload"]
    assert set(approval["proposed_files"]) == {"package.json", ".astraheal-playwright-standard.json"}
    assert (root / "package.json").read_text(encoding="utf-8") == original

    approved_state = {
        **proposal_state,
        "run_id": "approved-run",
        "approved": True,
        "input_payload": {
            "standard_profile": "astraheal-adaptive-enterprise-v1",
            "framework_repair_plan": approval,
            "approved_files": ["package.json"],
        },
    }
    applied = fix_node(approved_state)
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert applied["approval_required"] is False
    assert "package.json" in applied["patch_result"]["changed_files"]
    assert package["scripts"]["build"] == "tsc --noEmit"
    assert (root / ".qa-cache" / "existing-framework" / "backups").exists()


def test_framework_fix_fallback_stops_at_approval_boundary(tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    state = run_fallback(
        {
            "run_id": "fallback-proposal",
            "thread_id": "test-thread",
            "workflow": "framework_fix",
            "framework_path": str(root),
            "provider": "deterministic",
            "model": "",
            "input_payload": {"run_commands": False, "use_graphify": False},
            "approved": False,
            "completed_agents": [],
            "step_count": 0,
            "findings": [],
        }
    )
    assert state.get("approval_required") is True
    assert "validation" not in (state.get("completed_agents") or [])
    assert "review" not in (state.get("completed_agents") or [])
    assert (state.get("output") or {}).get("approval_payload", {}).get("proposed_files") and set((state.get("output") or {}).get("approval_payload", {}).get("proposed_files")) == {"package.json", ".astraheal-playwright-standard.json"}


def test_framework_fix_runtime_reports_waiting_for_file_approval(tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    started = start_run(
        {
            "workflow": "framework_fix",
            "framework_path": str(root),
            "provider": "deterministic",
            "approved": False,
            "input_payload": {"run_commands": False, "use_graphify": False},
        }
    )
    run = {}
    for _ in range(200):
        run = get_run(started["run_id"])
        if run.get("status") in {"waiting_for_approval", "completed", "failed"}:
            break
        time.sleep(0.02)
    assert run.get("status") == "waiting_for_approval", run.get("error")
    result = run.get("result") or {}
    assert result.get("approval_required") is True
    assert set((result.get("approval_payload") or {}).get("proposed_files") or []) == {"package.json", ".astraheal-playwright-standard.json"}


def test_required_validation_sequence_is_exact_and_restores_unapproved_lockfile(tmp_path: Path, monkeypatch) -> None:
    root = _framework(tmp_path / "repo")
    lock = root / "package-lock.json"
    lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    before = lock.read_bytes()
    calls: list[list[str]] = []

    def fake_run(args, *, cwd, timeout, extra_env):
        calls.append(list(args))
        if args[:2] == ["npm", "install"]:
            lock.write_text('{"lockfileVersion":3,"changedByInstall":true}\n', encoding="utf-8")
        return SimpleNamespace(ok=True, command=" ".join(args), returncode=0, stdout="ok", stderr="", error="")

    monkeypatch.setattr("qa_pipeline.agentic.playwright_doctor.run_command", fake_run)
    result = run_required_commands(root, preserve_project_files=True, allowed_project_changes=[])
    assert calls == [
        ["npm", "config", "set", "registry", "https://registry.npmjs.org/"],
        ["npm", "install", "--registry=https://registry.npmjs.org/"],
        ["npx", "playwright", "install", "chromium"],
        ["npm", "run", "build"],
    ]
    assert result["ok"] is True
    assert "package-lock.json" in result["source_side_effects_restored"]
    assert lock.read_bytes() == before


def test_framework_fix_gap_phase_does_not_run_expensive_commands_before_repair(monkeypatch, tmp_path: Path) -> None:
    root = _framework(tmp_path / "repo")
    calls: list[dict] = []

    def fake_invoke(tool, **kwargs):
        calls.append(dict(kwargs))
        return {
            "ok": False,
            "analysis_before": {"gap_count": 1, "critical_gap_count": 0},
            "analysis_after": {"gap_count": 1, "critical_gap_count": 0},
            "change_proposal": {"changes": [], "proposed_files": []},
            "message": "proposal-only gap pass",
        }

    monkeypatch.setattr("qa_pipeline.agentic.graph._invoke", fake_invoke)
    state = {
        "run_id": "racpad-gap-pass",
        "workflow": "framework_fix",
        "framework_path": str(root),
        "input_payload": {"run_commands": True},
        "completed_agents": [],
        "step_count": 0,
    }
    playwright_gap_node(state)
    assert calls and calls[0]["run_commands"] is False

    calls.clear()
    state["workflow"] = "deep_learn"
    playwright_gap_node(state)
    assert calls and calls[0]["run_commands"] is True


def test_racpad_workspace_missing_build_gets_workspace_aware_build_and_locked_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "racpad-like"
    (root / "src" / "test" / "specs").mkdir(parents=True)
    (root / "src" / "test" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "types").mkdir(parents=True)
    (root / "db" / "src").mkdir(parents=True)
    (root / "shared" / "src").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "racpad-like",
                "private": True,
                "workspaces": ["db", "shared"],
                "scripts": {
                    "typecheck": "npm run typecheck --workspaces --if-present",
                    "test:ui": "playwright test",
                },
                "devDependencies": {
                    "@playwright/test": "^1.60.0",
                    "@types/node": "^22.15.21",
                    "typescript": "^5.9.3",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "db" / "package.json").write_text(
        json.dumps({"name": "@racpad-ts/db", "private": True, "scripts": {"typecheck": "tsc --noEmit"}}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "shared" / "package.json").write_text(
        json.dumps(
            {
                "name": "@racpad-ts/shared",
                "private": True,
                "scripts": {"typecheck": "tsc --noEmit"},
                "dependencies": {"js-yaml": "^4.1.0"},
                "devDependencies": {"@types/js-yaml": "^4.0.9"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "commonjs",
                    "moduleResolution": "node",
                    "baseUrl": ".",
                    "types": ["node"],
                    "paths": {"@testData/*": ["src/test/resources/*"]},
                },
                "include": ["playwright.config.ts", "src/main/**/*.ts", "src/test/**/*.ts"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\nexport default defineConfig({ testDir: './src/test/specs' });\n",
        encoding="utf-8",
    )
    (root / "src" / "test" / "resources" / "yaml-loader.ts").write_text(
        "import yaml from 'js-yaml';\nexport const load = (s: string) => yaml.load(s);\n",
        encoding="utf-8",
    )
    (root / "src" / "main" / "types" / "imapflow.d.ts").write_text(
        "declare module 'imapflow' { export class ImapFlow {} }\n",
        encoding="utf-8",
    )
    (root / "src" / "main" / "optional.ts").write_text(
        "export async function optional() { const mod = await import('imapflow'); return mod.ImapFlow; }\n",
        encoding="utf-8",
    )
    (root / "src" / "test" / "specs" / "smoke.spec.ts").write_text(
        "import { test } from '@playwright/test';\ntest('smoke', async () => {});\n",
        encoding="utf-8",
    )
    lock = {
        "name": "racpad-like",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "racpad-like",
                "workspaces": ["db", "shared"],
                "devDependencies": {
                    "@playwright/test": "^1.60.0",
                    "@types/node": "^22.15.21",
                    "typescript": "^5.9.3",
                },
            },
            "node_modules/js-yaml": {"version": "4.1.0"},
            "node_modules/@types/js-yaml": {"version": "4.0.9"},
            "node_modules/@playwright/test": {"version": "1.60.0"},
            "node_modules/@types/node": {"version": "22.15.21"},
            "node_modules/typescript": {"version": "5.9.3"},
        },
    }
    (root / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    gaps = analyze_playwright_gaps(root)
    requirements = gaps["package_requirements"]
    assert requirements["workspace_aware"] is True
    assert requirements["recommended_build_script"] == "npm run typecheck && tsc --noEmit"
    assert requirements["unresolved_external_imports"] == []
    assert requirements["missing_dev_dependencies"] == {
        "js-yaml": "^4.1.0",
        "@types/js-yaml": "^4.0.9",
    }
    assert "imapflow" in requirements["ambient_declared_modules"]

    proposal = build_safe_config_change_plan(root, gaps)
    assert {"package.json", "package-lock.json", ".astraheal-playwright-standard.json"}.issubset(set(proposal["proposed_files"]))
    package_change = next(x for x in proposal["changes"] if x["file"] == "package.json")
    package_after = json.loads(package_change["proposed_content"])
    assert package_after["scripts"]["build"] == "npm run typecheck && tsc --noEmit"
    assert package_after["devDependencies"]["js-yaml"] == "^4.1.0"
    assert package_after["devDependencies"]["@types/js-yaml"] == "^4.0.9"
    lock_change = next(x for x in proposal["changes"] if x["file"] == "package-lock.json")
    lock_after = json.loads(lock_change["proposed_content"])
    assert lock_after["packages"][""]["devDependencies"]["js-yaml"] == "^4.1.0"
    assert lock_after["packages"][""]["devDependencies"]["@types/js-yaml"] == "^4.0.9"
