from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.agentic.memory import connection, initialize_database, put_framework_memory
from qa_pipeline.agentic.framework_cache import compute_framework_fingerprint, load_matching_cache, save_cache
from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.commands import run_command
from qa_pipeline.core.operation_control import check_cancelled

CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".java", ".cs"}
IGNORE = {"node_modules", ".git", "dist", "build", "coverage", "playwright-report", "test-results", "reports", ".qa-cache", ".aiqa-history", "graphify-out"}
IMPORT_PATTERNS = [
    re.compile(r"(?:import|export)\s+(?:[\s\S]*?\s+from\s+)?['\"]([^'\"]+)['\"]"),
    re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)"),
]
DECL_PATTERNS = {
    "class": re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"),
    "function": re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
    "interface": re.compile(r"\binterface\s+([A-Za-z_$][\w$]*)"),
    "test": re.compile(r"\b(?:test|it)\s*(?:\.only|\.skip|\.fixme)?\s*\(\s*['\"]([^'\"]+)['\"]"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _framework_key(root: Path) -> str:
    return hashlib.sha1(str(root.resolve()).lower().encode()).hexdigest()[:12]


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _iter_code(root: Path, limit: int = 12000) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE]
        for name in names:
            path = Path(current) / name
            low_name = name.lower()
            is_framework_config = low_name == "package.json" or low_name.startswith("tsconfig") and low_name.endswith(".json") or low_name.startswith("playwright.config.")
            if path.suffix.lower() in CODE_SUFFIXES or is_framework_config:
                files.append(path)
                if len(files) >= limit:
                    return files
    return files


def _read(path: Path, limit: int = 500_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _resolve_import(root: Path, source: Path, raw: str) -> str | None:
    if not raw.startswith((".", "/")):
        return None
    base = (source.parent / raw).resolve() if raw.startswith(".") else (root / raw.lstrip("/")).resolve()
    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(s) for s in CODE_SUFFIXES)
        candidates.extend((base / ("index" + s)) for s in CODE_SUFFIXES)
    for c in candidates:
        if c.exists() and c.is_file():
            return _rel(c, root)
    return None


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha1(value.encode('utf-8', errors='ignore')).hexdigest()[:20]}"


def _persist(root: Path, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    initialize_database()
    framework_path = str(root.resolve())
    now = _now()
    with connection() as conn:
        conn.execute("DELETE FROM astraheal_code_graph_nodes WHERE framework_path=?", (framework_path,))
        conn.execute("DELETE FROM astraheal_code_graph_edges WHERE framework_path=?", (framework_path,))
        conn.executemany(
            "INSERT INTO astraheal_code_graph_nodes(framework_path,node_id,node_type,name,file_path,line_no,properties_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            [(framework_path, n["id"], n["type"], n["name"], n.get("file_path", ""), n.get("line_no"), json.dumps(n.get("properties") or {}, ensure_ascii=False), now) for n in nodes],
        )
        conn.executemany(
            "INSERT INTO astraheal_code_graph_edges(framework_path,source_id,target_id,relation,confidence,provenance,properties_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            [(framework_path, e["source"], e["target"], e["relation"], float(e.get("confidence", 1.0)), e.get("provenance", "EXTRACTED"), json.dumps(e.get("properties") or {}, ensure_ascii=False), now) for e in edges],
        )


def _run_graphify(root: Path) -> dict[str, Any]:
    command = shutil.which("graphify")
    if not command:
        return {"available": False, "used": False, "message": "Graphify CLI is not installed. Install optional dependency: pip install -e '.[codegraph]'"}
    output = root / "graphify-out"
    args = [command, "extract", str(root), "--code-only", "--no-viz"]
    try:
        proc = run_command(args, cwd=root, timeout=900)
    except Exception as exc:
        return {"available": True, "used": False, "command": args, "error": f"{type(exc).__name__}: {exc}"}
    graph_json = output / "graph.json"
    report_md = output / "GRAPH_REPORT.md"
    return {
        "available": True,
        "used": bool(proc.returncode == 0 and graph_json.exists()),
        "command": args,
        "return_code": proc.returncode,
        "stdout_tail": proc.stdout[-8000:],
        "stderr_tail": proc.stderr[-8000:],
        "graph_json": str(graph_json) if graph_json.exists() else "",
        "report_md": str(report_md) if report_md.exists() else "",
        "message": "Graphify code-only knowledge graph created." if proc.returncode == 0 and graph_json.exists() else "Graphify was available but did not create a usable graph; AstraHeal built-in graph remains active.",
    }


def build_code_graph(framework_path: str | Path, *, use_graphify: bool = True) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": f"Framework path does not exist: {root}"}
    fingerprint = compute_framework_fingerprint(root)
    cached = load_matching_cache(root, "code-graph-cache.json", fingerprint=fingerprint)
    if cached:
        graph_path = Path(str(cached.get("built_in_graph_json") or ""))
        if graph_path.exists():
            try:
                payload = json.loads(graph_path.read_text(encoding="utf-8", errors="replace"))
                nodes = payload.get("nodes") or []
                edges = payload.get("edges") or []
                if nodes:
                    _persist(root, nodes, edges)
                cached["cache_hit"] = True
                cached["graphify"] = {**(cached.get("graphify") or {}), "reused": True, "message": "Graphify/built-in code graph reused because the framework fingerprint is unchanged."}
                cached["message"] = "Framework code graph reused from .qa-cache; no repeated source parsing or Graphify extraction was required."
                return cached
            except Exception:
                pass
    files = _iter_code(root)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    file_ids: dict[str, str] = {}
    role_counts = Counter()
    unresolved_imports: list[dict[str, str]] = []
    symbol_to_nodes: defaultdict[str, list[str]] = defaultdict(list)

    for path in files:
        check_cancelled()
        rel = _rel(path, root)
        low = rel.lower()
        role = "source"
        if re.search(r"\.(?:specs?|test)\.(?:ts|tsx|js|jsx|mjs|cjs)$", low): role = "test_spec"
        elif "fixture" in low: role = "fixture"
        elif "pageobject" in low or "page-object" in low or "/pages/" in f"/{low}/": role = "page_object"
        elif "config" in low or path.name.lower() in {"package.json", "tsconfig.json"}: role = "configuration"
        role_counts[role] += 1
        fid = _node_id("file", rel)
        file_ids[rel] = fid
        nodes.append({"id": fid, "type": "file", "name": path.name, "file_path": rel, "properties": {"role": role, "suffix": path.suffix.lower()}})

    for path in files:
        rel = _rel(path, root)
        text = _read(path)
        source_id = file_ids[rel]
        for pattern in IMPORT_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(1)
                resolved = _resolve_import(root, path, raw)
                if resolved and resolved in file_ids:
                    edges.append({"source": source_id, "target": file_ids[resolved], "relation": "imports", "confidence": 1.0, "provenance": "EXTRACTED", "properties": {"raw": raw}})
                elif raw.startswith((".", "/")):
                    unresolved_imports.append({"source": rel, "import": raw})
        for kind, pattern in DECL_PATTERNS.items():
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                line_no = text.count("\n", 0, match.start()) + 1
                sid = _node_id(kind, f"{rel}:{name}:{line_no}")
                nodes.append({"id": sid, "type": kind, "name": name, "file_path": rel, "line_no": line_no, "properties": {}})
                edges.append({"source": source_id, "target": sid, "relation": "defines", "confidence": 1.0, "provenance": "EXTRACTED"})
                symbol_to_nodes[name].append(sid)

    # Conservative inferred symbol-use edges. Tokenise each file once instead of
    # scanning every symbol against every file (important for large enterprise repos).
    candidate_names = {name for name in symbol_to_nodes if len(name) >= 4}
    defined_pairs = {(e["source"], e["target"]) for e in edges if e["relation"] == "defines"}
    seen_refs: set[tuple[str, str]] = set()
    token_pattern = re.compile(r"\b[A-Za-z_$][\w$]{3,}\b")
    for path in files[:8000]:
        rel = _rel(path, root)
        text = _read(path, 240_000)
        source_id = file_ids[rel]
        used_names = token_pattern.findall(text)
        for name in set(used_names).intersection(candidate_names):
            for target in symbol_to_nodes[name][:3]:
                pair = (source_id, target)
                if pair not in defined_pairs and pair not in seen_refs:
                    edges.append({"source": source_id, "target": target, "relation": "references", "confidence": 0.65, "provenance": "INFERRED"})
                    seen_refs.add(pair)

    _persist(root, nodes, edges)
    reports = root / ".qa-cache" / "existing-framework" / "code-graph"
    reports.mkdir(parents=True, exist_ok=True)
    graph_path = reports / "astraheal-code-graph.json"
    graph_payload = {"framework_path": str(root), "generated_at": _now(), "nodes": nodes, "edges": edges}
    graph_path.write_text(json.dumps(graph_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    central = REPORTS_DIR / "existing-framework"
    central.mkdir(parents=True, exist_ok=True)
    central_graph = central / "astraheal-code-graph.json"
    central_graph.write_text(json.dumps(graph_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    graphify = _run_graphify(root) if use_graphify else {"available": bool(shutil.which("graphify")), "used": False, "message": "Graphify disabled for this run."}
    summary = {
        "ok": True,
        "framework_path": str(root),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "file_count": len(files),
        "roles": dict(role_counts),
        "unresolved_import_count": len(unresolved_imports),
        "unresolved_imports": unresolved_imports[:200],
        "built_in_graph_json": str(graph_path),
        "central_graph_json": str(central_graph),
        "graphify": graphify,
        "strategy": "hybrid_graphify_plus_astraheal_sqlite_graph" if graphify.get("used") else "astraheal_sqlite_structural_graph_with_optional_graphify",
        "message": "Framework code graph indexed. Graphify was used as an additional local structural index." if graphify.get("used") else "Framework code graph indexed in SQLite. Graphify is optional and can be enabled without replacing AstraHeal's guaranteed scanner.",
    }
    summary["cache_hit"] = False
    save_cache(root, "code-graph-cache.json", summary, fingerprint=fingerprint)
    put_framework_memory(str(root), "code_graph_summary", summary, confidence=1.0, source="code_graph_indexer")
    return summary


def query_code_graph(framework_path: str | Path, query: str, limit: int = 30) -> dict[str, Any]:
    root = str(Path(framework_path).expanduser().resolve())
    tokens = set(re.findall(r"[a-zA-Z_$][\w$.-]+", (query or "").lower()))
    initialize_database()
    with connection() as conn:
        rows = conn.execute("SELECT * FROM astraheal_code_graph_nodes WHERE framework_path=?", (root,)).fetchall()
        edges = conn.execute("SELECT * FROM astraheal_code_graph_edges WHERE framework_path=?", (root,)).fetchall()
    scored = []
    for row in rows:
        data = dict(row)
        hay = f"{data.get('name','')} {data.get('file_path','')} {data.get('node_type','')}".lower()
        score = sum(2 if t in data.get("name", "").lower() else 1 for t in tokens if t in hay)
        if score:
            scored.append((score, data))
    scored.sort(key=lambda x: (-x[0], x[1].get("file_path") or ""))
    selected = [d for _, d in scored[:max(1, limit)]]
    selected_ids = {d["node_id"] for d in selected}
    related = []
    for row in edges:
        e = dict(row)
        if e["source_id"] in selected_ids or e["target_id"] in selected_ids:
            related.append(e)
            if len(related) >= limit * 4:
                break
    return {"ok": True, "query": query, "nodes": selected, "edges": related, "message": f"Found {len(selected)} relevant graph node(s) and {len(related)} relationship(s)."}
