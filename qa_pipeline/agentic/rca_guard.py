from __future__ import annotations

import json
import re
from typing import Any

NO_IDEA = "No idea to fix"


def _flatten_text(value: Any, limit: int = 200000) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except Exception:
        return str(value)[:limit]


def _numeric_confidence(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for key in ("confidence", "confidence_score", "patch_confidence", "score"):
            value = payload.get(key)
            try:
                if value is not None:
                    f = float(value)
                    return f / 100 if f > 1 else f
            except Exception:
                pass
        for value in payload.values():
            found = _numeric_confidence(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _numeric_confidence(value)
            if found is not None:
                return found
    return None


def assess_grounding(payload: dict[str, Any], threshold: float = 0.67) -> dict[str, Any]:
    text = _flatten_text(payload).lower()
    evidence_markers = [
        "stack", "stderr", "stdout", "trace", "screenshot", "failed spec", "error:", "locator", "expected", "received", "return_code", "test-results", "playwright"
    ]
    evidence_score = sum(1 for marker in evidence_markers if marker in text)
    speculative = sum(1 for marker in ["might be", "probably", "perhaps", "try changing", "could be", "guess", "likely maybe"] if marker in text)
    confidence = _numeric_confidence(payload)
    if confidence is None:
        confidence = min(0.92, 0.32 + evidence_score * 0.075 - speculative * 0.08)
    has_concrete_error = bool(re.search(r"(?:error|failed|timeout|expected|received|cannot find module|return.?code)", text))
    grounded = bool(confidence >= threshold and evidence_score >= 2 and has_concrete_error)
    reasons = []
    if confidence < threshold: reasons.append(f"confidence {confidence:.2f} is below {threshold:.2f}")
    if evidence_score < 2: reasons.append("insufficient independent evidence markers")
    if not has_concrete_error: reasons.append("no concrete failure signature")
    return {"grounded": grounded, "confidence": round(max(0.0, min(1.0, confidence)), 3), "evidence_marker_count": evidence_score, "speculative_marker_count": speculative, "reasons": reasons}


def enforce_grounded_rca(payload: dict[str, Any], threshold: float = 0.67) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"ok": False, "no_idea_to_fix": True, "fix_proposal": NO_IDEA, "message": "RCA payload was not structured enough to produce a safe fix."}
    result = dict(payload)
    grounding = assess_grounding(result, threshold=threshold)
    result["grounding"] = grounding
    result["confidence"] = grounding["confidence"]
    if grounding["grounded"]:
        result["no_idea_to_fix"] = False
        result.setdefault("should_patch", True)
        return result
    result["no_idea_to_fix"] = True
    result["should_patch"] = False
    result["fix_proposal"] = NO_IDEA
    result["suggested_fix"] = NO_IDEA
    result["recommendation"] = NO_IDEA
    result["message"] = f"{NO_IDEA}. AstraHeal did not find enough independent evidence for a safe patch. Collect a trace, screenshot, exact stack, DOM/network evidence, or reproduce the failure before healing."
    # Preserve evidence and classifications but remove likely hallucinated patch instructions.
    for key in ("patch", "patch_plan", "proposed_patch", "code_changes", "replacements"):
        if key in result:
            result[key] = [] if isinstance(result[key], list) else {}
    return result


def healing_allowed(rca_payload: dict[str, Any], threshold: float = 0.67) -> tuple[bool, dict[str, Any]]:
    guarded = enforce_grounded_rca(rca_payload, threshold=threshold)
    return bool(not guarded.get("no_idea_to_fix") and guarded.get("should_patch", True)), guarded
