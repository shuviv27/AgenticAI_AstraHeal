from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, ensure_dirs

CONFIG_PATH = QA_CACHE_DIR / "project_config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "project_name": "AI QA Automation Project",
    "application_name": "Application Under Test",
    "base_url": "",
    "source_type": "jira",
    "feature": "login",
    "provider": "codex",
    "ollama_model": "llama3",
    "execution_project": "chromium",
    "use_mcp": True,
    "skip_npm": False,
    "test_id_attribute": "data-test",
    "notes": "Configure from GUI Project Setup. No credentials are stored here.",
}


def load_project_config() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        save_project_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(data if isinstance(data, dict) else {})
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_project_config(config: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    safe = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in config and config[key] is not None:
            safe[key] = config[key]
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Keep a short human-readable copy at repo root for demo/visibility.
    (REPO_ROOT / ".project-config.example.json").write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return safe
