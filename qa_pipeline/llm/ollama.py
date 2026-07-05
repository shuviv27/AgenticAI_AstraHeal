from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class OllamaResult:
    ok: bool
    text: str
    error: str = ""


class OllamaProvider:
    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3") -> None:
        self.host = host.rstrip("/")
        self.model = model

    def chat(self, prompt: str, system: str = "") -> OllamaResult:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system or "You are a concise enterprise QA automation assistant."},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return OllamaResult(True, data.get("message", {}).get("content", ""))
        except Exception as exc:
            return OllamaResult(False, "", str(exc))
