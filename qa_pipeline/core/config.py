from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("BASE_URL", "http://localhost:3000")
    llm_provider: str = os.getenv("LLM_PROVIDER", "deterministic")
    codegen_provider: str = os.getenv("CODEGEN_PROVIDER", "deterministic")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")


def get_settings() -> Settings:
    return Settings()
