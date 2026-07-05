from __future__ import annotations

from pathlib import Path


def normalize_connector_input(source: str | Path, source_type: str) -> dict:
    return {"source_type": source_type, "source": str(source), "status": "normalized_or_upload_ready"}
