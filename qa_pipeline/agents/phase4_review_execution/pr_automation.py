from __future__ import annotations

from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR


def build_pr_metadata(feature: str = "feature") -> dict:
    changed = [str(p.relative_to(GENERATED_PLAYWRIGHT_DIR)) for p in GENERATED_PLAYWRIGHT_DIR.rglob("*.ts")]
    return {"status": "pr_ready_metadata", "feature": feature, "changed_files": changed[:200], "safety": "No git push or PR creation is performed automatically from GUI."}
