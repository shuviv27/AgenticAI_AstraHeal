from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator


def configure_langsmith() -> dict[str, Any]:
    """Configure LangSmith without forcing telemetry when no key is present."""
    api_key = (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY") or "").strip()
    enabled = bool(api_key and (os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "true")).lower() not in {"0", "false", "no"}) )
    if enabled:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
        os.environ.setdefault("LANGSMITH_API_KEY", api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "astraheal-autonomous-multi-agent"))
    return {
        "enabled": enabled,
        "project": os.getenv("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "astraheal-autonomous-multi-agent")),
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")),
        "api_key_configured": bool(api_key),
        "message": "LangSmith tracing is enabled for LangGraph/LangChain runs." if enabled else "LangSmith is ready but disabled until LANGSMITH_API_KEY is configured.",
    }


def traceable_agent(name: str):
    """Use LangSmith traceable when installed, otherwise return an identity decorator."""
    try:
        from langsmith import traceable
        return traceable(name=name, run_type="chain")
    except Exception:
        def decorator(fn):
            return fn
        return decorator


@contextmanager
def tracing_context(**metadata: Any) -> Iterator[None]:
    """Enable LangSmith tracing without masking workflow exceptions.

    Only failures while importing or entering LangSmith's tracing context are
    treated as optional-observability failures. Exceptions raised by the
    LangGraph workflow body must propagate unchanged so the user sees the real
    framework-analysis error instead of ``generator didn't stop after throw()``.
    """
    configure_langsmith()
    try:
        from langsmith import tracing_context as _tracing_context
    except Exception:
        yield
        return

    stack = ExitStack()
    try:
        stack.enter_context(_tracing_context(metadata=metadata))
    except Exception:
        stack.close()
        yield
        return

    with stack:
        yield
