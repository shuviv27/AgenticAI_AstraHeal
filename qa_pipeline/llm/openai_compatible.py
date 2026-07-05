from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class OpenAICompatibleResult:
    ok: bool
    text: str
    error: str = ""
    provider: str = "openai_compatible"
    status_code: int = 0
    endpoint: str = ""
    diagnostic: str = ""


class OpenAICompatibleProvider:
    """Tiny dependency-free OpenAI-compatible chat client.

    This is intentionally minimal so the enterprise build does not require a new
    SDK package. It works with OpenAI-compatible /chat/completions APIs such as
    OpenAI and DeepSeek when the base URL, API key and model are configured.

    The OpenAI provider is now stricter and clearer about base URLs:
    - Public OpenAI should use https://api.openai.com/v1
    - If the user accidentally enters https://api.openai.com, /v1 is added.
    - If the user enters a full endpoint like /chat/completions, /responses, or
      /models, it is normalized back to the API base.
    - Azure OpenAI endpoints are detected and reported as unsupported by the
      public OpenAI provider path.
    """

    def __init__(self, provider: str = "openai", api_key: str = "", base_url: str = "", model: str = "") -> None:
        self.provider = (provider or "openai").strip().lower()
        self.api_key = api_key or self._env_key(self.provider)
        raw_base_url = base_url or self._default_base_url(self.provider)
        self.base_url = self._normalize_base_url(self.provider, raw_base_url)
        self.model = model or self._default_model(self.provider)

    @staticmethod
    def _env_key(provider: str) -> str:
        if provider == "deepseek":
            return os.getenv("DEEPSEEK_API_KEY", "")
        if provider == "perplexity":
            return os.getenv("PERPLEXITY_API_KEY", "")
        return os.getenv("OPENAI_API_KEY", "")

    @staticmethod
    def _default_base_url(provider: str) -> str:
        if provider == "deepseek":
            return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if provider == "perplexity":
            return os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    @staticmethod
    def _default_model(provider: str) -> str:
        if provider == "deepseek":
            return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if provider == "perplexity":
            return os.getenv("PERPLEXITY_MODEL", "sonar")
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    @staticmethod
    def _normalize_base_url(provider: str, base_url: str) -> str:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            return base

        lower = base.lower()
        # Users often paste the full endpoint instead of the base URL.
        for suffix in ("/chat/completions", "/responses", "/models"):
            if lower.endswith(suffix):
                base = base[: -len(suffix)]
                lower = base.lower().rstrip("/")
                base = base.rstrip("/")
                break

        # Public OpenAI API base must include /v1.  DeepSeek and Perplexity
        # commonly work without /v1 for Chat Completions, so do not force /v1.
        if provider == "openai" and lower in {"https://api.openai.com", "http://api.openai.com"}:
            base = base + "/v1"
        return base.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _looks_like_azure_openai(self) -> bool:
        host = urlparse(self.base_url).hostname or ""
        return ".openai.azure.com" in host.lower() or ".cognitiveservices.azure.com" in host.lower()

    def _request_json(self, url: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout_seconds: int = 45) -> OpenAICompatibleResult:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return OpenAICompatibleResult(True, body, provider=self.provider, status_code=getattr(resp, "status", 0), endpoint=url)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            body_tail = body[-1200:] if body else ""
            return OpenAICompatibleResult(False, "", f"HTTPError {exc.code}: {exc.reason}. Response: {body_tail}", provider=self.provider, status_code=exc.code, endpoint=url)
        except Exception as exc:
            return OpenAICompatibleResult(False, "", f"{type(exc).__name__}: {exc}", provider=self.provider, endpoint=url)

    def _list_models(self, timeout_seconds: int = 45) -> OpenAICompatibleResult:
        return self._request_json(self.base_url + "/models", method="GET", timeout_seconds=timeout_seconds)

    def _model_visible_in_list(self, models_text: str) -> bool | None:
        try:
            data = json.loads(models_text or "{}")
            ids = [str(m.get("id") or "") for m in data.get("data", []) if isinstance(m, dict)]
            if not ids:
                return None
            return self.model in ids
        except Exception:
            return None

    def chat(self, prompt: str, system: str = "", timeout_seconds: int = 180) -> OpenAICompatibleResult:
        if not self.is_configured():
            return OpenAICompatibleResult(False, "", f"{self.provider} is not configured. Set API key/base URL/model in .env or GUI provider config.", provider=self.provider)
        if self.provider == "openai" and self._looks_like_azure_openai():
            return OpenAICompatibleResult(
                False,
                "",
                "Azure OpenAI endpoint detected. The current 'OpenAI API' provider expects the public OpenAI API base URL https://api.openai.com/v1. Use a public OpenAI API key/base URL, or add a dedicated Azure OpenAI provider configuration.",
                provider=self.provider,
                diagnostic="azure_endpoint_detected",
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You are an enterprise QA automation assistant. Return concise, auditable guidance."},
                {"role": "user", "content": prompt or ""},
            ],
            "temperature": 0.2,
        }
        url = self.base_url + "/chat/completions"
        result = self._request_json(url, method="POST", payload=payload, timeout_seconds=timeout_seconds)
        if not result.ok:
            result.error = self._explain_http_failure(result)
            return result
        try:
            data = json.loads(result.text or "{}")
            text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            result.text = text
            return result
        except Exception as exc:
            return OpenAICompatibleResult(False, "", f"{self.provider} returned non-JSON or unexpected response: {type(exc).__name__}: {exc}", provider=self.provider, endpoint=url)

    def _explain_http_failure(self, result: OpenAICompatibleResult) -> str:
        error = result.error or ""
        if result.status_code == 404 and self.provider == "perplexity":
            return (
                "Perplexity live validation reached HTTP 404. For Sonar Chat Completions use base URL "
                "'https://api.perplexity.ai' unless your organization provides a proxy base URL. "
                f"Attempted endpoint: {result.endpoint}. Raw error: {error}"
            )
        if result.status_code == 404 and self.provider == "openai":
            return (
                "OpenAI live validation reached HTTP 404. This usually means one of these is wrong: "
                "OPENAI_BASE_URL, endpoint style, or model name. For public OpenAI use base URL 'https://api.openai.com/v1' "
                "only; do not enter '/chat/completions', '/responses', or an Azure deployment URL as the base. "
                f"Attempted endpoint: {result.endpoint}. Raw error: {error}"
            )
        if result.status_code == 401:
            return f"Authentication failed. Check the API key for {self.provider}. Raw error: {error}"
        if result.status_code == 403:
            return f"Access forbidden. The key may not have permission for this project/model or outbound access is restricted. Raw error: {error}"
        return error

    def validate_connection(self, timeout_seconds: int = 45) -> OpenAICompatibleResult:
        """Perform a small live backend validation call for the selected API provider.

        Validation now separates base URL/API-key reachability from model/chat
        readiness so the GUI can show a useful message instead of a generic 404.
        """
        if not self.is_configured():
            return OpenAICompatibleResult(False, "", f"{self.provider} is not configured. Set API key/base URL/model in .env or GUI provider config.", provider=self.provider)
        if self.provider == "openai" and self._looks_like_azure_openai():
            return OpenAICompatibleResult(
                False,
                "",
                "Azure OpenAI endpoint detected. This build's OpenAI provider validates the public OpenAI API. Set OPENAI_BASE_URL=https://api.openai.com/v1, or use an Azure-specific provider enhancement.",
                provider=self.provider,
                diagnostic="azure_endpoint_detected",
            )

        # First check the base URL and API key using /models.  This avoids
        # confusing a bad model name with a completely wrong base URL.
        models_probe = self._list_models(timeout_seconds=timeout_seconds)
        if not models_probe.ok:
            models_probe.error = self._explain_http_failure(models_probe)
            return models_probe

        model_visible = self._model_visible_in_list(models_probe.text)
        if model_visible is False:
            return OpenAICompatibleResult(
                False,
                "",
                f"{self.provider} API key and base URL are reachable, but model '{self.model}' was not returned by /models. Choose a model available to this key/project, then retry. Base URL checked: {self.base_url}",
                provider=self.provider,
                endpoint=self.base_url + "/models",
                diagnostic="model_not_visible",
            )

        chat_probe = self.chat(
            "Return exactly: AI_PROVIDER_CONNECTION_OK",
            system="You are a connection health check. Return only the requested token.",
            timeout_seconds=timeout_seconds,
        )
        if chat_probe.ok:
            chat_probe.diagnostic = "api_key_base_url_and_model_confirmed"
        return chat_probe
