from __future__ import annotations

from typing import Any, TypedDict


class AstraHealAgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    workflow: str
    objective: str
    framework_path: str
    provider: str
    model: str
    base_url: str
    input_payload: dict[str, Any]
    status: str
    next_agent: str
    routing_reason: str
    completed_agents: list[str]
    step_count: int
    max_steps: int
    messages: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    inventory: dict[str, Any]
    framework_intelligence: dict[str, Any]
    code_graph: dict[str, Any]
    gap_report: dict[str, Any]
    plan: dict[str, Any]
    approval_required: bool
    approved: bool
    approval_payload: dict[str, Any]
    patch_result: dict[str, Any]
    validation: dict[str, Any]
    execution: dict[str, Any]
    walkthrough: dict[str, Any]
    rca: dict[str, Any]
    report: dict[str, Any]
    confidence: float
    no_idea_to_fix: bool
    errors: list[str]
    output: dict[str, Any]
