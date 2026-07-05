from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

SCHEMA_VERSION = "1.0.0"


@dataclass
class EventEnvelope:
    event_type: str
    phase: str
    status: Literal["created", "running", "completed", "failed"] = "created"
    pipeline_run_id: str = field(default_factory=lambda: str(uuid4()))
    phase_run_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestStep:
    action: str
    target: str
    value: str | None = None
    page: str | None = None
    expected: str | None = None


@dataclass
class TestScenario:
    id: str
    title: str
    feature: str
    page: str
    source_type: str
    source_ref: str
    priority: str
    tags: list[str]
    preconditions: list[str]
    steps: list[TestStep]
    expected_result: str
    start_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(s) for s in self.steps]
        return data
