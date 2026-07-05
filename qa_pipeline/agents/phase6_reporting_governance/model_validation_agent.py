from __future__ import annotations


def model_validation_matrix() -> dict:
    rows = [
        "Requirements extraction", "Quality scoring", "RAG retrieval", "Test scenario generation", "POM/locator generation",
        "Playwright code generation", "Code review agent", "Failure classification", "Self-healing", "Root cause analysis",
        "Reporting agent", "Safety/security", "Cost and latency",
    ]
    return {"status": "registered", "rows": rows, "release_gate": "All mandatory rows must be green before model/prompt promotion."}
