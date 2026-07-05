from __future__ import annotations

from qa_pipeline.rag.framework_inventory import scan_framework


def analyze_framework() -> dict:
    return scan_framework().to_dict()
