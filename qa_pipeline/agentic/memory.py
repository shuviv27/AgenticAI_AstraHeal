from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from qa_pipeline.core.paths import REPO_ROOT

DB_PATH = REPO_ROOT / "astraheal_memory.sqlite3"
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

_SCHEMA_LOCK = threading.RLock()
_CHECKPOINTER_LOCK = threading.RLock()
_CHECKPOINTER: Any = None
_CHECKPOINTER_CONN: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> Path:
    with _SCHEMA_LOCK, connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS astraheal_agent_runs (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                workflow TEXT NOT NULL,
                framework_path TEXT,
                provider TEXT,
                model TEXT,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_astraheal_runs_thread ON astraheal_agent_runs(thread_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_astraheal_runs_framework ON astraheal_agent_runs(framework_path, updated_at DESC);

            CREATE TABLE IF NOT EXISTS astraheal_agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_astraheal_events_run ON astraheal_agent_events(run_id, id);

            CREATE TABLE IF NOT EXISTS astraheal_framework_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                framework_path TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'agent',
                updated_at TEXT NOT NULL,
                UNIQUE(framework_path, memory_key)
            );
            CREATE INDEX IF NOT EXISTS idx_astraheal_memory_framework ON astraheal_framework_memory(framework_path, updated_at DESC);

            CREATE TABLE IF NOT EXISTS astraheal_code_graph_nodes (
                framework_path TEXT NOT NULL,
                node_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT,
                line_no INTEGER,
                properties_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(framework_path, node_id)
            );
            CREATE TABLE IF NOT EXISTS astraheal_code_graph_edges (
                framework_path TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1,
                provenance TEXT NOT NULL DEFAULT 'EXTRACTED',
                properties_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(framework_path, source_id, target_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_astraheal_graph_edges_source ON astraheal_code_graph_edges(framework_path, source_id);
            CREATE INDEX IF NOT EXISTS idx_astraheal_graph_edges_target ON astraheal_code_graph_edges(framework_path, target_id);
            """
        )
    return DB_PATH


def get_checkpointer() -> Any:
    """Return the project-root SQLite LangGraph checkpointer.

    The optional import keeps existing non-agentic commands usable before the new
    dependencies are installed. The agentic status endpoint clearly reports that
    situation instead of breaking the whole GUI.
    """
    global _CHECKPOINTER, _CHECKPOINTER_CONN
    initialize_database()
    with _CHECKPOINTER_LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except Exception:
            return None
        _CHECKPOINTER_CONN = _connect()
        _CHECKPOINTER = SqliteSaver(_CHECKPOINTER_CONN)
        try:
            _CHECKPOINTER.setup()
        except Exception:
            pass
        return _CHECKPOINTER


def upsert_run(run_id: str, thread_id: str, workflow: str, *, framework_path: str = "", provider: str = "", model: str = "", status: str = "created", request: dict[str, Any] | None = None, result: dict[str, Any] | None = None, error: str = "") -> None:
    initialize_database()
    now = _now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO astraheal_agent_runs(run_id, thread_id, workflow, framework_path, provider, model, status, request_json, result_json, error, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
              thread_id=excluded.thread_id, workflow=excluded.workflow,
              framework_path=excluded.framework_path, provider=excluded.provider,
              model=excluded.model, status=excluded.status,
              request_json=CASE WHEN excluded.request_json='{}' THEN astraheal_agent_runs.request_json ELSE excluded.request_json END,
              result_json=CASE WHEN excluded.result_json='{}' THEN astraheal_agent_runs.result_json ELSE excluded.result_json END,
              error=excluded.error, updated_at=excluded.updated_at
            """,
            (run_id, thread_id, workflow, framework_path, provider, model, status,
             json.dumps(request or {}, ensure_ascii=False, default=str),
             json.dumps(result or {}, ensure_ascii=False, default=str), error or "", now, now),
        )


def record_event(run_id: str, agent: str, event_type: str, status: str, message: str, *, progress: int | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    initialize_database()
    ts = _now()
    safe_progress = None if progress is None else max(0, min(100, int(progress)))
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO astraheal_agent_events(run_id,ts,agent,event_type,status,progress,message,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, ts, agent, event_type, status, safe_progress, message,
             json.dumps(payload or {}, ensure_ascii=False, default=str)),
        )
        event_id = int(cur.lastrowid)
    return {"id": event_id, "run_id": run_id, "ts": ts, "agent": agent, "event_type": event_type, "status": status, "progress": safe_progress, "message": message, "payload": payload or {}}


def read_events(run_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    initialize_database()
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM astraheal_agent_events WHERE run_id=? AND id>? ORDER BY id ASC LIMIT ?",
            (run_id, max(0, int(after_id or 0)), max(1, min(int(limit or 500), 5000))),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        try:
            data["payload"] = json.loads(data.pop("payload_json") or "{}")
        except Exception:
            data["payload"] = {}
        events.append(data)
    return events


def get_run(run_id: str) -> dict[str, Any]:
    initialize_database()
    with connection() as conn:
        row = conn.execute("SELECT * FROM astraheal_agent_runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return {}
    data = dict(row)
    for key in ("request_json", "result_json"):
        try:
            data[key[:-5]] = json.loads(data.pop(key) or "{}")
        except Exception:
            data[key[:-5]] = {}
    return data


def list_runs(limit: int = 50, framework_path: str = "") -> list[dict[str, Any]]:
    initialize_database()
    with connection() as conn:
        if framework_path:
            rows = conn.execute("SELECT * FROM astraheal_agent_runs WHERE framework_path=? ORDER BY updated_at DESC LIMIT ?", (framework_path, max(1, min(limit, 500)))).fetchall()
        else:
            rows = conn.execute("SELECT * FROM astraheal_agent_runs ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data.pop("request_json", None)
        data.pop("result_json", None)
        result.append(data)
    return result


def put_framework_memory(framework_path: str, key: str, value: Any, *, confidence: float = 1.0, source: str = "agent") -> None:
    initialize_database()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO astraheal_framework_memory(framework_path,memory_key,value_json,confidence,source,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(framework_path,memory_key) DO UPDATE SET value_json=excluded.value_json,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at
            """,
            (framework_path, key, json.dumps(value, ensure_ascii=False, default=str), float(confidence), source, _now()),
        )


def get_framework_memory(framework_path: str, key: str = "") -> dict[str, Any]:
    initialize_database()
    with connection() as conn:
        if key:
            rows = conn.execute("SELECT * FROM astraheal_framework_memory WHERE framework_path=? AND memory_key=?", (framework_path, key)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM astraheal_framework_memory WHERE framework_path=? ORDER BY updated_at DESC", (framework_path,)).fetchall()
    result: dict[str, Any] = {}
    for row in rows:
        try:
            result[row["memory_key"]] = {"value": json.loads(row["value_json"]), "confidence": row["confidence"], "source": row["source"], "updated_at": row["updated_at"]}
        except Exception:
            result[row["memory_key"]] = {"value": row["value_json"], "confidence": row["confidence"], "source": row["source"], "updated_at": row["updated_at"]}
    return result


initialize_database()
