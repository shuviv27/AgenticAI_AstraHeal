from __future__ import annotations

from qa_pipeline.agents.phase3_reuse_aware_codegen.locator_strategy import infer_locator


def propose_locator(action: str, target: str, page: str = "Page") -> dict:
    inferred = infer_locator(action, target)
    return {"page": page, "name": inferred.get("locatorName", target or action), "action": action, "target": target, "recommended": inferred, "strategy_priority": ["getByTestId", "getByRole", "getByLabel", "getByText", "css"]}
