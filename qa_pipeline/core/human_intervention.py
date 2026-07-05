from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event

HUMAN_DIR = QA_CACHE_DIR / "existing-framework" / "human-intervention"
HUMAN_MEMORY_JSONL = HUMAN_DIR / "human-intervention-memory.jsonl"
HUMAN_LATEST_JSON = HUMAN_DIR / "latest-human-intervention.json"
HUMAN_REQUEST_JSON = HUMAN_DIR / "latest-human-intervention-request.json"
HUMAN_REPORT_HTML = REPORTS_DIR / "existing-framework" / "human-intervention-report.html"
EXISTING_REPORTS_DIR = REPORTS_DIR / "existing-framework"


def _html(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_human_intervention_memory(limit: int = 25) -> dict[str, Any]:
    HUMAN_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if HUMAN_MEMORY_JSONL.exists():
        for line in HUMAN_MEMORY_JSONL.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    latest = _read_json(HUMAN_LATEST_JSON, {})
    request = _read_json(HUMAN_REQUEST_JSON, {})
    return {
        "ok": True,
        "latest_request": request,
        "latest_update": latest,
        "records": records[-limit:],
        "count": len(records),
        "memory_file": str(HUMAN_MEMORY_JSONL),
        "report_url": "/artifacts/reports/existing-framework/human-intervention-report.html",
    }


def _summarize_current_blockers() -> dict[str, Any]:
    rca = _read_json(EXISTING_REPORTS_DIR / "root-cause-report.json", {}) or {}
    self_heal = _read_json(EXISTING_REPORTS_DIR / "self-healing-report.json", {}) or {}
    failed = _read_json(EXISTING_REPORTS_DIR / "failed-tests.json", {}) or {}
    failed_specs = (
        self_heal.get("root_cause", {}).get("failed_specs")
        or rca.get("failed_specs")
        or failed.get("failed_specs")
        or []
    )
    allowed_files = (
        self_heal.get("scope", {}).get("allowed_files")
        or rca.get("scope", {}).get("allowed_files")
        or []
    )
    signals = rca.get("signals") or self_heal.get("root_cause", {}).get("signals") or []
    return {
        "failed_specs": failed_specs,
        "allowed_files": allowed_files,
        "stage": self_heal.get("stage") or rca.get("stage") or "unknown",
        "message": self_heal.get("message") or rca.get("message") or "No RCA/self-healing summary found yet.",
        "human_approval_required": bool(self_heal.get("human_approval_required")),
        "signals": signals[:8],
        "self_healing_report_url": "/artifacts/reports/existing-framework/self-healing-report.html",
        "rca_report_url": "/artifacts/reports/existing-framework/plain-english-failure-report.html",
    }


def create_human_intervention_request(framework_path: str = "", reason: str = "", source: str = "gui") -> dict[str, Any]:
    HUMAN_DIR.mkdir(parents=True, exist_ok=True)
    blockers = _summarize_current_blockers()
    request_id = f"HIR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    request = {
        "ok": True,
        "request_id": request_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "created_at_epoch_ms": int(time.time() * 1000),
        "source": source,
        "framework_path": framework_path,
        "reason": reason or blockers.get("message") or "AI needs human confirmation before patching or rerun.",
        "blockers": blockers,
        "what_human_can_update": [
            "Framework-level: confirm page class/pageObject/helper/testData files that are safe to update.",
            "Environment-level: confirm VPN/proxy/certificate/base URL/login/session/test data issues.",
            "AUT/product-level: confirm expected behavior, changed labels/buttons, product bug or requirement change.",
            "Manual fix-level: describe any fix already applied manually so AI memory can use it before rerun.",
        ],
        "recommended_next_action": "Add a human update in the GUI, save it to AI memory, then run Create safe fix plan / Fix failed tests safely / Run failed tests again.",
    }
    HUMAN_REQUEST_JSON.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _append_jsonl(HUMAN_MEMORY_JSONL, {"type": "human_intervention_request", **request})
    _write_human_intervention_report()
    log_event("human_intervention", "Human intervention request created and saved to AI memory.", status="warning", progress=100, details={"request_id": request_id})
    return {**request, "report_url": "/artifacts/reports/existing-framework/human-intervention-report.html"}


def save_human_intervention_update(
    framework_path: str = "",
    intervention_type: str = "framework_code",
    decision: str = "reviewed",
    summary: str = "",
    details: str = "",
    affected_files: str = "",
    environment_updates: str = "",
    test_data_updates: str = "",
    safe_files: str = "",
    rerun_instruction: str = "",
) -> dict[str, Any]:
    HUMAN_DIR.mkdir(parents=True, exist_ok=True)
    record_id = f"HIU-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    record = {
        "ok": True,
        "type": "human_intervention_update",
        "record_id": record_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "created_at_epoch_ms": int(time.time() * 1000),
        "framework_path": framework_path,
        "intervention_type": intervention_type,
        "decision": decision,
        "summary": summary.strip(),
        "details": details.strip(),
        "affected_files": [x.strip().replace("\\", "/") for x in affected_files.replace(";", "\n").splitlines() if x.strip()],
        "environment_updates": environment_updates.strip(),
        "test_data_updates": test_data_updates.strip(),
        "safe_files_confirmed_by_human": [x.strip().replace("\\", "/") for x in safe_files.replace(";", "\n").splitlines() if x.strip()],
        "rerun_instruction": rerun_instruction.strip(),
        "usage_policy": "Use this as safe project memory. If decision is approved_to_patch, exact files listed under safe_files_confirmed_by_human may extend the safe patch scope for the next self-healing run, but destructive blocked patterns remain protected.",
    }
    HUMAN_LATEST_JSON.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _append_jsonl(HUMAN_MEMORY_JSONL, record)
    _write_human_intervention_report()
    log_event("human_intervention", "Human update saved to AI memory for future RCA/self-healing.", status="done", progress=100, details={"record_id": record_id, "intervention_type": intervention_type, "decision": decision})
    return {**record, "message": "Human update saved to project AI memory. Next RCA/self-healing prompt will include this update.", "report_url": "/artifacts/reports/existing-framework/human-intervention-report.html"}


def _write_human_intervention_report() -> Path:
    mem = read_human_intervention_memory(limit=100)
    rows = []
    for i, rec in enumerate(mem.get("records") or [], 1):
        rows.append(f"<tr><td>{i}</td><td>{_html(rec.get('type'))}</td><td>{_html(rec.get('created_at'))}</td><td>{_html(rec.get('intervention_type') or rec.get('source'))}</td><td>{_html(rec.get('decision') or rec.get('reason'))}</td><td><pre>{_html(json.dumps(rec, indent=2, ensure_ascii=False)[:5000])}</pre></td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Human Intervention Memory</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:8px;vertical-align:top;text-align:left}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:12px;max-height:280px;overflow:auto}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}</style></head><body>
<h1>Human Intervention Memory</h1>
<div class='card'><p>This report contains human decisions and environment/framework clarifications saved for RCA, safe fix planning, self-healing and failed-only reruns. It does not expose hidden chain-of-thought; it stores observable decisions and user-provided context only.</p></div>
<div class='card'><h2>Latest request</h2><pre>{_html(json.dumps(mem.get('latest_request') or {}, indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Latest human update</h2><pre>{_html(json.dumps(mem.get('latest_update') or {}, indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>History</h2><table><tr><th>#</th><th>Record</th><th>Time</th><th>Type</th><th>Decision/Reason</th><th>Details</th></tr>{''.join(rows) if rows else '<tr><td colspan="6">No human updates saved yet.</td></tr>'}</table></div>
</body></html>"""
    HUMAN_REPORT_HTML.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_REPORT_HTML.write_text(html, encoding="utf-8")
    return HUMAN_REPORT_HTML
