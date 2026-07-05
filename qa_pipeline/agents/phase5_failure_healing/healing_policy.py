from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import REPO_ROOT

DEFAULT_POLICY: dict[str, Any] = {
    "version": "2026.06.enterprise-rca-v1",
    "maxHealingAttempts": 2,
    "minPatchProposalConfidence": 0.70,
    "minAutoApplyConfidence": 0.80,
    "semanticAssertionThreshold": 0.30,
    "allowedPaths": [
        "pageObjects/", "pages/", "utils/", "fixtures/", "testData/",
        "generated-playwright/pageObjects/", "generated-playwright/pages/", "generated-playwright/utils/",
        "generated-playwright/fixtures/", "generated-playwright/testData/", "qa-ai-support/",
    ],
    "manualApprovalPaths": ["tests/", "generated-playwright/tests/", "playwright.config.ts", "package.json"],
    "blockedPatterns": [
        r"test\.skip\s*\(", r"test\.fixme\s*\(", r"\.only\s*\(", r"waitForTimeout\s*\(",
        r"expect\.soft\s*\(", r"force\s*:\s*true", r"toBeTruthy\s*\(\s*\)",
    ],
    "allowForceClick": False,
    "allowAssertionChange": False,
    "allowSpecLocatorAddition": False,
    "requireTypecheck": True,
    "requireLintIfAvailable": True,
    "requireFailedTestOnlyRerun": True,
}


def policy_path() -> Path:
    return REPO_ROOT / "configs" / "self-healing-policy.json"


def load_healing_policy() -> dict[str, Any]:
    path = policy_path()
    if not path.exists():
        return dict(DEFAULT_POLICY)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        merged = dict(DEFAULT_POLICY)
        if isinstance(loaded, dict):
            merged.update(loaded)
        return merged
    except Exception:
        return dict(DEFAULT_POLICY)


def _norm(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _matches_any(path: str, prefixes: list[str]) -> bool:
    norm = _norm(path)
    return any(norm == p.rstrip("/") or norm.startswith(_norm(p)) for p in prefixes)


def validate_patch_diff(diff_payload: dict[str, Any], scoped_allowed_files: list[str] | None = None, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate an AI/self-healing patch against enterprise guardrails.

    The validator is intentionally deterministic and additive. It does not replace RCA;
    it is the final safety gate before a Codex/LLM patch can be accepted.
    """
    policy = policy or load_healing_policy()
    changed_files = [_norm(x) for x in (diff_payload or {}).get("changed_files", [])]
    combined_diff = str((diff_payload or {}).get("combined_diff") or "")
    scoped = [_norm(x) for x in (scoped_allowed_files or []) if _norm(x)]

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    allowed_prefixes = list(policy.get("allowedPaths") or [])
    manual_prefixes = list(policy.get("manualApprovalPaths") or [])

    for file in changed_files:
        if scoped and file not in scoped:
            violations.append({"type": "OUT_OF_FAILED_SCOPE", "file": file, "message": "Changed file is not in failed-spec dependency scope."})
        if manual_prefixes and _matches_any(file, manual_prefixes):
            warnings.append({"type": "MANUAL_APPROVAL_PATH", "file": file, "message": "Patch touches spec/config/package area; approval required."})
        if allowed_prefixes and not _matches_any(file, allowed_prefixes):
            violations.append({"type": "DISALLOWED_PATH", "file": file, "message": "Patch changed a file outside allowed self-healing paths."})

    for pat in policy.get("blockedPatterns") or []:
        try:
            if re.search(pat, combined_diff, flags=re.I):
                violations.append({"type": "BLOCKED_PATTERN", "pattern": pat, "message": "Diff contains a blocked anti-pattern."})
        except re.error:
            continue

    added_lines = "\n".join(line[1:] for line in combined_diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed_lines = "\n".join(line[1:] for line in combined_diff.splitlines() if line.startswith("-") and not line.startswith("---"))

    if not policy.get("allowAssertionChange", False):
        if re.search(r"\bexpect\s*\(", added_lines) or re.search(r"\bexpect\s*\(", removed_lines):
            # Assertion-preserving refactors are still review-worthy because this is where silent product regressions hide.
            warnings.append({"type": "ASSERTION_LINE_TOUCHED", "message": "Assertion line changed; manual review required unless assertion drift classifier explicitly allowed it."})

    if not policy.get("allowSpecLocatorAddition", False):
        spec_locator = any(re.search(r"(^|/)tests?/|\.spec\.ts$", f, flags=re.I) for f in changed_files) and re.search(r"page\.(locator|getByRole|getByText|getByTestId|getByLabel|getByPlaceholder)\s*\(", added_lines)
        if spec_locator:
            violations.append({"type": "RAW_LOCATOR_IN_SPEC", "message": "Self-healing must not add raw locators in specs; patch pageObjects/pages instead."})

    if not policy.get("allowForceClick", False) and re.search(r"force\s*:\s*true", added_lines, flags=re.I):
        violations.append({"type": "FORCE_CLICK_DEFAULT", "message": "force:true is blocked as an automatic healing strategy."})

    manual_required = bool(violations or warnings)
    return {
        "ok": not violations,
        "policy_version": policy.get("version"),
        "changed_files": changed_files,
        "violations": violations,
        "warnings": warnings,
        "human_approval_required": manual_required,
        "message": "Patch accepted by deterministic policy gate." if not manual_required else "Patch requires human approval or revision because policy gate found risks.",
    }


def policy_summary_for_prompt() -> str:
    policy = load_healing_policy()
    return json.dumps({
        "maxHealingAttempts": policy.get("maxHealingAttempts"),
        "minPatchProposalConfidence": policy.get("minPatchProposalConfidence"),
        "minAutoApplyConfidence": policy.get("minAutoApplyConfidence"),
        "allowedPaths": policy.get("allowedPaths"),
        "blockedPatterns": policy.get("blockedPatterns"),
        "allowForceClick": policy.get("allowForceClick"),
        "allowAssertionChange": policy.get("allowAssertionChange"),
        "allowSpecLocatorAddition": policy.get("allowSpecLocatorAddition"),
        "locatorPriority": policy.get("locatorPriority"),
    }, indent=2, ensure_ascii=False)
