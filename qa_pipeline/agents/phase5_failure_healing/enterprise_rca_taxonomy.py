from __future__ import annotations

import re
from typing import Any

RCA_TAXONOMY: dict[str, dict[str, Any]] = {
    "LOCATOR_NOT_FOUND": {
        "symptoms": ["waiting for locator", "to be visible", "getbyrole", "getbytext", "strict mode violation"],
        "healing": "Repair locator in pageObjects using getByTestId/getByRole/getByLabel before CSS/XPath.",
        "files": ["pageObjects/*.ts"],
        "auto_healable": True,
    },
    "ELEMENT_DISABLED": {
        "symptoms": ["not enabled", "disabled", "aria-disabled"],
        "healing": "Diagnose business/API condition; wait for required input/API/session state. Do not force click.",
        "files": ["pages/*.ts", "fixtures/*.ts", "testData/*"],
        "auto_healable": False,
    },
    "ELEMENT_NOT_INTERACTABLE": {
        "symptoms": ["intercepts pointer events", "outside of the viewport", "detached", "not attached to the dom", "element is not attached", "not visible", "click timeout"],
        "healing": "Use safe action wrapper: close overlays, scroll into view, wait visible/enabled/stable, then click.",
        "files": ["utils/safeActions.ts", "pages/*.ts"],
        "auto_healable": True,
    },
    "UNEXPECTED_POPUP_MODAL": {
        "symptoms": ["modal", "popup", "cookie", "newsletter", "survey", "chatbot", "overlay"],
        "healing": "Update centralized popup/dialog handler instead of patching every spec.",
        "files": ["utils/popupHandler.ts", "utils/dialogHandler.ts", "fixtures/*.ts"],
        "auto_healable": True,
    },
    "BROWSER_PERMISSION": {
        "symptoms": ["permission", "geolocation", "notification", "clipboard", "camera", "microphone"],
        "healing": "Configure context/project permissions or app-aware permission fixture.",
        "files": ["fixtures/*.ts", "playwright.config.ts"],
        "auto_healable": True,
    },
    "NETWORK_OR_API": {
        "symptoms": ["401", "403", "500", "net::err", "econnrefused", "api", "xhr", "fetch"],
        "healing": "Use HAR/network evidence. Patch UI waits only if API is healthy; otherwise mark env/product/data issue.",
        "files": ["pages/*.ts", "fixtures/*.ts", "testData/*"],
        "auto_healable": False,
    },
    "ASSERTION_DRIFT_OR_PRODUCT_REGRESSION": {
        "symptoms": ["expected", "received", "tohavetext", "tocontaintext", "toequal", "tohaveurl"],
        "healing": "Run assertion drift classifier. Cosmetic copy may be proposed; behavior/value drift needs human review.",
        "files": ["manual-review"],
        "auto_healable": False,
    },
    "IFRAME_OR_SHADOW_DOM": {
        "symptoms": ["iframe", "frame", "shadow", "frameLocator"],
        "healing": "Use frameLocator or Playwright shadow-compatible locators in pageObjects.",
        "files": ["pageObjects/*.ts"],
        "auto_healable": True,
    },
    "TIMING_OR_FLAKE": {
        "symptoms": ["timeout", "flaky", "retry", "networkidle", "load state"],
        "healing": "Replace hard waits with deterministic web-first assertions, API waits, and stable DOM/actionability helpers.",
        "files": ["pages/*.ts", "utils/safeActions.ts"],
        "auto_healable": True,
    },
}


def classify_text(error_text: str) -> dict[str, Any]:
    low = (error_text or "").lower()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for label, meta in RCA_TAXONOMY.items():
        score = 0
        for symptom in meta.get("symptoms", []):
            if symptom.lower() in low:
                score += 1
        if score:
            scored.append((score, label, meta))
    if not scored:
        return {"category": "UNKNOWN", "confidence": 0.25, "auto_healable": False, "healing": "Collect trace/video/screenshot/DOM/HAR evidence and rerun RCA.", "files": []}
    score, label, meta = sorted(scored, reverse=True)[0]
    confidence = min(0.92, 0.45 + score * 0.12)
    return {"category": label, "confidence": round(confidence, 3), **meta}
