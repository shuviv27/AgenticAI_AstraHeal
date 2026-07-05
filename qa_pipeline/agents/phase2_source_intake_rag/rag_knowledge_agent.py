from __future__ import annotations

from qa_pipeline.rag.framework_inventory import scan_framework


def build_retrieval_context(feature: str = "feature") -> dict:
    inv = scan_framework().to_dict()
    return {"feature": feature, "framework_inventory": inv, "context_status": "ready"}
