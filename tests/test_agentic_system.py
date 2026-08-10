from __future__ import annotations

import json
import time
from pathlib import Path

from qa_pipeline.agentic.code_graph import build_code_graph
from qa_pipeline.agentic.memory import DB_PATH, get_run
from qa_pipeline.agentic.rca_guard import enforce_grounded_rca
from qa_pipeline.agentic.runtime import start_run


def _playwright_project(root: Path) -> None:
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "smoke.spec.ts").write_text("import { test } from '@playwright/test'; test('smoke', async ({ page }) => { await page.goto('/'); });", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"name": "sample", "scripts": {"build": "tsc --noEmit"}, "devDependencies": {"@playwright/test": "latest", "typescript": "latest"}}), encoding="utf-8")
    (root / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"target": "ES2022", "moduleResolution": "Node", "noEmit": True}}), encoding="utf-8")
    (root / "playwright.config.ts").write_text("import { defineConfig } from '@playwright/test'; export default defineConfig({ testDir: './tests' });", encoding="utf-8")


def test_root_sqlite_memory_exists() -> None:
    assert DB_PATH.name == "astraheal_memory.sqlite3"
    assert DB_PATH.exists()


def test_code_graph_indexes_playwright_files(tmp_path: Path) -> None:
    _playwright_project(tmp_path)
    result = build_code_graph(tmp_path, use_graphify=False)
    assert result["ok"] is True
    assert result["file_count"] >= 4
    assert result["node_count"] >= result["file_count"]


def test_rca_returns_no_idea_without_evidence() -> None:
    result = enforce_grounded_rca({"ok": True, "suggested_fix": "Maybe change the locator"})
    assert result["no_idea_to_fix"] is True
    assert result["suggested_fix"] == "No idea to fix"
    assert result["should_patch"] is False


def test_deep_learn_workflow_completes(tmp_path: Path) -> None:
    _playwright_project(tmp_path)
    started = start_run({"workflow": "deep_learn", "framework_path": str(tmp_path), "provider": "deterministic", "input_payload": {"use_graphify": False, "run_commands": False}})
    run = {}
    for _ in range(200):
        run = get_run(started["run_id"])
        if run.get("status") in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert run.get("status") == "completed", run.get("error")
    assert (run.get("result") or {}).get("workflow") == "deep_learn"


def test_tracing_context_preserves_workflow_exception(monkeypatch) -> None:
    import sys
    import types
    from contextlib import contextmanager

    @contextmanager
    def fake_langsmith_context(**_kwargs):
        yield

    fake_module = types.SimpleNamespace(tracing_context=fake_langsmith_context)
    monkeypatch.setitem(sys.modules, "langsmith", fake_module)

    from qa_pipeline.agentic.observability import tracing_context

    try:
        with tracing_context(run_id="test"):
            raise ValueError("real framework failure")
    except ValueError as exc:
        assert str(exc) == "real framework failure"
    else:
        raise AssertionError("Workflow exception was swallowed")


def test_gui_places_framework_agents_only_under_existing_framework() -> None:
    html_path = Path(__file__).resolve().parents[1] / "qa_pipeline" / "gui" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    home = html.split('<section id="home"', 1)[1].split('</section>', 1)[0]
    framework = html.split('<section id="framework"', 1)[1].split('</section>', 1)[0]
    assert "Autonomous Multi-Agent Control" not in home
    assert "Analyse framework &amp; check setup" in framework
    assert "Validate &amp; fix framework" in framework
    assert "Prepare browser-assisted diagnosis (MCP)" in framework
    assert 'id="agentTimeline"' in framework
