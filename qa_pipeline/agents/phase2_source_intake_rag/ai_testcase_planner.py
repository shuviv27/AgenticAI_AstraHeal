from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # Remove fenced code block markers when present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(candidate[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _testcase_prompt(normalized: dict[str, Any], feature: str, base_url: str = "") -> str:
    return f"""
You are an enterprise QA analyst. Convert the requirement/manual steps below into clear functional testcases.
Return JSON only. Do not return markdown.

Strict JSON shape:
{{
  "source_ref": "input source name",
  "source_type": "jira|srs|pdf|confluence|test_management",
  "feature": "{feature}",
  "page": "PascalCasePageNameWithoutPageSuffix",
  "priority": "low|medium|high|critical",
  "tags": ["{feature}"],
  "scenarios": [
    {{
      "id": "SCENARIO-ID",
      "title": "business-readable title",
      "page": "PascalCasePageNameWithoutPageSuffix",
      "priority": "medium",
      "test_type": "smoke|functional|regression|accessibility|negative|api|performance|security",
      "suite": "smoke|functional|regression|accessibility|negative|api|performance|security",
      "preconditions": [],
      "start_url": "{base_url}",
      "steps": [
        {{"action":"goto","target":"application","value":"{base_url}","page":"PascalCasePageNameWithoutPageSuffix"}},
        {{"action":"fill","target":"username input","value":"provided value if present","page":"PascalCasePageNameWithoutPageSuffix"}},
        {{"action":"click","target":"Login button","page":"PascalCasePageNameWithoutPageSuffix"}},
        {{"action":"verify","target":"expected page or message","expected":"expected business result","page":"PascalCasePageNameWithoutPageSuffix"}}
      ],
      "expected_result": "clear expected result",
      "source_ref": "input source name"
    }}
  ]
}}

Important:
- Preserve exact URLs and data values supplied by the user.
- Do not invent credentials or URLs.
- If a value is missing, leave it empty rather than inventing it.
- Keep steps actionable for Playwright generation.
- Categorize each scenario intelligently: smoke for first-page/load/critical checks, regression for broad navigation/footer/business coverage, accessibility for keyboard/alt/heading/contrast checks, negative for 404/error/restricted cases, api for endpoint/OpenAPI cases, performance/security only when explicitly requested.
- Do not create generic visible-text assertions such as "home page"; convert page concepts into concrete checks using real headings/buttons/URLs.
- For complex DOM apps, include stable target names, expected URL fragments, and semantic hints that help pageObjects choose getByRole/getByLabel/getByTestId/href locators.
- Page Object Model guardrail: `page` must be the real application page/screen name, not the testcase/story id. Use names like `Home`, `Login`, `FindStore`, `ShopOnline`, `HowItWorks`, `Checkout`, `Dashboard`. Never use `Testcase1`, `SCRUM-6`, `Story1`, or feature ids as page object names unless the real UI page is actually named that.
- Reuse guardrail: if two testcases touch the same page, they must share the same page and pageObjects files. Example: both testcase1 and testcase2 home-page checks must map to `HomePage` and `HomePage.objects`, while navigation after Shop In-store maps following checks to `FindStorePage`.
- Self-healing guardrail: preserve spec.ts -> pages -> pageObjects. Never suggest raw locators in specs.

Requirement/initial deterministic extraction:
{json.dumps(normalized, indent=2, ensure_ascii=False)}
"""


def maybe_enhance_testcases_with_ai(normalized_path: Path, provider: str, model: str, feature: str, base_url: str = "") -> tuple[Path, dict[str, Any]]:
    """Use Codex/Ollama to refine functional testcases, then return a JSON path.

    Deterministic parsing always runs first. AI is used to improve testcase clarity when enabled.
    If AI is unavailable or returns invalid JSON, we safely keep the deterministic testcase JSON.
    """
    normalized = read_json(normalized_path)
    provider = (provider or "deterministic").lower()
    if provider not in {"codex", "ollama"}:
        return normalized_path, {"ai_used": False, "provider": provider, "message": "Deterministic parser used. Choose Codex or Ollama to use AI planning."}

    prompt = _testcase_prompt(normalized, feature, base_url)
    message = ""
    ok = False
    data: dict[str, Any] | None = None

    try:
        if provider == "codex":
            result = CodexCliProvider(REPO_ROOT).run(prompt)
            message = result.stdout if result.ok else (result.stderr or "Codex failed")
            ok = result.ok
            data = _extract_json_object(message)
        elif provider == "ollama":
            result = OllamaProvider(model=model).chat(prompt, system="Return valid JSON only.")
            message = result.text if result.ok else result.error
            ok = result.ok
            data = _extract_json_object(message)
    except Exception as exc:
        return normalized_path, {
            "ai_used": False,
            "provider": provider,
            "ai_ok": False,
            "message": f"AI provider failed safely: {type(exc).__name__}: {exc}",
            "fallback": "Deterministic testcase JSON was used so the GUI does not fail with HTTP 500.",
        }

    if not ok or not data or not data.get("scenarios"):
        return normalized_path, {
            "ai_used": False,
            "provider": provider,
            "ai_ok": ok,
            "message": (message or "AI response was empty")[-4000:],
            "fallback": "AI output was unavailable or invalid JSON. Deterministic testcase JSON was used safely.",
        }

    out_dir = QA_CACHE_DIR / "ai_plans" / feature
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{feature}_{provider}_functional_testcases.json"
    # Preserve source metadata if the model omitted it.
    data.setdefault("source_ref", normalized.get("source_ref", normalized_path.name))
    data.setdefault("source_type", normalized.get("source_type", "jira"))
    data.setdefault("feature", feature)
    data.setdefault("page", normalized.get("page", feature.title()))
    for scenario in data.get("scenarios", []):
        scenario.setdefault("source_ref", data["source_ref"])
        scenario.setdefault("page", data.get("page"))
        scenario.setdefault("start_url", base_url or normalized.get("start_url"))
        for step in scenario.get("steps", []):
            step.setdefault("page", scenario.get("page"))
    write_json(out, data)
    return out, {"ai_used": True, "provider": provider, "ai_ok": ok, "message": message[-4000:], "ai_testcase_file": str(out.relative_to(REPO_ROOT))}
