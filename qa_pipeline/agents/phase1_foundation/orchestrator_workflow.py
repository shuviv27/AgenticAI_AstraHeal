from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def create_pipeline_run(run_type: str = "manual", feature: str = "feature") -> dict:
    return {
        "pipeline_run_id": str(uuid4()),
        "run_type": run_type,
        "feature": feature,
        "status": "created",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "phase_order": ["foundation", "source_intake", "test_design_codegen", "review_execution", "failure_healing", "reporting_governance"],
    }
