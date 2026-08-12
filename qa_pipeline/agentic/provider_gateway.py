from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import REPO_ROOT
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.llm.openai_compatible import OpenAICompatibleProvider


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.I)
    candidates.extend(fenced)
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


class AIProviderGateway:
    """One provider gateway used by every LangGraph agent.

    Existing provider implementations remain the source of truth, preserving all
    current authentication and VM behaviour. LangChain RunnableLambda is used
    when installed, while a direct call fallback keeps legacy workflows usable.
    """

    def invoke(self, prompt: str, *, system: str = "", provider: str = "deterministic", model: str = "", repo_root: str | Path | None = None, timeout_seconds: int = 180) -> dict[str, Any]:
        selected = (provider or "deterministic").strip().lower()
        root = Path(repo_root or REPO_ROOT).resolve()

        def call(_: Any = None) -> dict[str, Any]:
            if selected in {"deterministic", "rules", "none", ""}:
                return {"ok": False, "provider": "deterministic", "text": "", "error": "No LLM provider requested."}
            if selected in {"openai", "deepseek", "perplexity"}:
                result = OpenAICompatibleProvider(provider=selected, model=model).chat(prompt, system=system, timeout_seconds=timeout_seconds)
                return {"ok": bool(result.ok), "provider": selected, "text": result.text, "error": result.error, "endpoint": result.endpoint}
            if selected == "ollama":
                result = OllamaProvider(model=model or "llama3").chat(prompt, system=system)
                return {"ok": bool(result.ok), "provider": selected, "text": result.text, "error": result.error}
            if selected == "codex":
                result = CodexCliProvider(root, timeout_seconds=timeout_seconds).run((system + "\n\n" + prompt).strip())
                return {"ok": bool(result.ok), "provider": selected, "text": result.stdout, "error": result.stderr, "return_code": result.exit_code}
            return {"ok": False, "provider": selected, "text": "", "error": f"Provider {selected} is not enabled for autonomous orchestration."}

        try:
            from langchain_core.runnables import RunnableLambda
            return RunnableLambda(call).invoke({})
        except Exception:
            return call({})

    def invoke_json(self, prompt: str, *, system: str = "", provider: str = "deterministic", model: str = "", repo_root: str | Path | None = None, timeout_seconds: int = 180) -> dict[str, Any]:
        result = self.invoke(prompt, system=system, provider=provider, model=model, repo_root=repo_root, timeout_seconds=timeout_seconds)
        parsed = _extract_json(str(result.get("text") or "")) if result.get("ok") else None
        result["json"] = parsed
        if result.get("ok") and parsed is None:
            result["ok"] = False
            result["error"] = "Provider returned no parseable JSON."
        return result


provider_gateway = AIProviderGateway()
