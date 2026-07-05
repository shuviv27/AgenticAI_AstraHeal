from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR

# Central GUI mirror locations. These keep existing /artifacts links working.
INTELLIGENCE_DIR = REPORTS_DIR / "existing-framework"
INTELLIGENCE_V2_JSON = INTELLIGENCE_DIR / "framework-intelligence-v2.json"
INTELLIGENCE_V2_HTML = INTELLIGENCE_DIR / "framework-intelligence-v2.html"
PLAIN_FAILURE_JSON = INTELLIGENCE_DIR / "plain-english-failure-report.json"
PLAIN_FAILURE_HTML = INTELLIGENCE_DIR / "plain-english-failure-report.html"

# Existing-framework RAG/cache must belong to the framework selected by the user,
# not to generated-playwright.  The central files below are only compatibility
# mirrors/pointers for the GUI and older functions.
CENTRAL_EXISTING_CACHE_DIR = QA_CACHE_DIR / "existing-framework"
CENTRAL_RAG_DIR = CENTRAL_EXISTING_CACHE_DIR / "rag"
CHUNKS_JSONL = CENTRAL_RAG_DIR / "framework-chunks.jsonl"
RAG_SUMMARY_JSON = CENTRAL_RAG_DIR / "framework-rag-summary.json"
ACTIVE_FRAMEWORK_CACHE_JSON = CENTRAL_EXISTING_CACHE_DIR / "active-framework-cache.json"


def framework_cache_dir(root: Path) -> Path:
    return Path(root).resolve() / ".qa-cache" / "existing-framework"


def framework_rag_dir(root: Path) -> Path:
    return framework_cache_dir(root) / "rag"


def framework_reports_dir(root: Path) -> Path:
    return framework_cache_dir(root) / "reports"


def framework_chunks_jsonl(root: Path) -> Path:
    return framework_rag_dir(root) / "framework-chunks.jsonl"


def framework_rag_summary_json(root: Path) -> Path:
    return framework_rag_dir(root) / "framework-rag-summary.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_active_framework_pointer(root: Path, summary: dict[str, Any]) -> None:
    CENTRAL_EXISTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pointer = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(Path(root).resolve()),
        "framework_local_cache_dir": str(framework_cache_dir(root)),
        "framework_local_rag_dir": str(framework_rag_dir(root)),
        "framework_local_chunk_store": str(framework_chunks_jsonl(root)),
        "framework_local_rag_summary": str(framework_rag_summary_json(root)),
        "central_gui_mirror_chunk_store": str(CHUNKS_JSONL),
        "central_gui_mirror_rag_summary": str(RAG_SUMMARY_JSON),
        "summary": summary,
    }
    _write_json(ACTIVE_FRAMEWORK_CACHE_JSON, pointer)

CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
DATA_SUFFIXES = {".json", ".yaml", ".yml", ".csv", ".env", ".txt", ".md"}
IGNORED_PARTS = {"node_modules", ".git", "dist", "build", "coverage", "playwright-report", "test-results", "reports", ".next"}

TECH_HINTS = {
    "playwright": ["@playwright/test", "playwright"],
    "typescript": ["typescript", "ts-node", "tsx"],
    "eslint": ["eslint", "@typescript-eslint"],
    "allure": ["allure", "allure-playwright"],
    "cucumber_bdd": ["cucumber", "@cucumber/cucumber", "gherkin"],
    "axios_api": ["axios"],
    "graphql": ["graphql", "apollo"],
    "prisma_db": ["prisma", "@prisma/client"],
    "typeorm_db": ["typeorm"],
    "sequelize_db": ["sequelize"],
    "mongoose_db": ["mongoose"],
    "postgres_db": ["pg", "postgres"],
    "mysql_db": ["mysql", "mysql2"],
    "mssql_db": ["mssql"],
    "redis": ["redis", "ioredis"],
    "dotenv": ["dotenv"],
}

VPN_VDI_KEYWORDS = [
    "vpn", "vdi", "vm", "virtual desktop", "citrix", "zscaler", "globalprotect", "anyconnect",
    "forticlient", "pulse secure", "proxy", "jumpbox", "bastion", "corp network", "corporate network",
    "internal app", "intranet", "remote desktop", "rdp", "private dns",
]


def _safe_read(path: Path, limit: int = 220_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except Exception:
        parts = path.parts
    return any(part in IGNORED_PARTS for part in parts)


def _iter_files(root: Path, suffixes: set[str] | None = None, limit: int = 6000) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= limit:
            break
        if not path.is_file() or _ignored(path, root):
            continue
        if suffixes is None or path.suffix.lower() in suffixes:
            files.append(path)
    return sorted(files, key=lambda p: _rel(p, root))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_./:-]{1,}", (text or "").lower())


def _hash_embedding(text: str, dims: int = 64) -> list[float]:
    """Small deterministic sparse embedding used when no external embedding model is configured.

    It is intentionally local/offline so framework indexing stays cheap and safe. A production
    system can swap this with OpenAI/Ollama embeddings without changing the stored chunk schema.
    """
    vector = [0.0] * dims
    for tok in _tokens(text)[:2500]:
        digest = hashlib.sha256(tok.encode("utf-8", errors="ignore")).digest()
        idx = int.from_bytes(digest[:2], "big") % dims
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vector]


def _score(query: str, chunk: dict[str, Any]) -> float:
    q = set(_tokens(query))
    if not q:
        return 0.0
    c = set(chunk.get("tokens", []))
    overlap = len(q & c)
    tag_boost = sum(0.5 for tag in chunk.get("tags", []) if tag in q)
    path_boost = sum(0.35 for tok in q if tok in str(chunk.get("path", "")).lower())
    return overlap + tag_boost + path_boost


def _chunk_text(text: str, max_chars: int = 9000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        cut = text.rfind("\n", start, end)
        if cut <= start + max_chars // 2:
            cut = end
        chunks.append(text[start:cut])
        start = cut
    return chunks[:80]


def _classify_chunk(path: Path, rel: str, text: str) -> tuple[str, list[str]]:
    low_path = rel.lower()
    low_text = text.lower()
    tags: list[str] = []
    kind = "code"
    if any(x in low_path for x in ["pageobject", "page-object", "objects"]):
        kind = "page_object"; tags.append("locator")
    elif "/pages/" in f"/{low_path}/" or low_path.endswith("page.ts"):
        kind = "page_class"; tags.extend(["flow", "pom"])
    elif any(x in low_path for x in ["fixtures", "fixture"]):
        kind = "fixture"; tags.append("session")
    elif any(x in low_path for x in ["testdata", "test-data", "/data/"]):
        kind = "test_data"; tags.append("data")
    elif low_path.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js")):
        kind = "spec"; tags.append("test")
    elif low_path.startswith(".github/") or "pipeline" in low_path or "workflow" in low_path:
        kind = "ci_trigger"; tags.append("trigger")
    elif path.suffix.lower() in {".md", ".txt"}:
        kind = "documentation"; tags.append("knowledge")
    if any(x in low_text for x in ["waitforresponse", "fetch(", "axios", "request.", "page.route", "api/"]):
        tags.append("api")
    if any(x in low_text for x in ["database", "db_", "postgres", "mysql", "mongodb", "prisma", "typeorm", "connectionstring"]):
        tags.append("database")
    if any(x in low_text for x in VPN_VDI_KEYWORDS):
        tags.append("vdi_vpn")
    if any(x in low_text for x in ["getbyrole", "getbytestid", "locator(", "xpath", "css="]):
        tags.append("locator")
    return kind, sorted(set(tags))


def build_framework_rag_index(root: Path, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    local_rag_dir = framework_rag_dir(root)
    local_chunks_jsonl = framework_chunks_jsonl(root)
    local_summary_json = framework_rag_summary_json(root)
    local_rag_dir.mkdir(parents=True, exist_ok=True)
    CENTRAL_RAG_DIR.mkdir(parents=True, exist_ok=True)
    code_files = _iter_files(root, CODE_SUFFIXES | DATA_SUFFIXES, limit=4500)
    chunks: list[dict[str, Any]] = []
    for file in code_files:
        text = _safe_read(file, limit=180_000)
        if not text.strip():
            continue
        rel = _rel(file, root)
        for idx, chunk in enumerate(_chunk_text(text, max_chars=8500)):
            kind, tags = _classify_chunk(file, rel, chunk)
            toks = _tokens(chunk)
            record = {
                "id": hashlib.sha1(f"{rel}:{idx}:{chunk[:64]}".encode("utf-8", errors="ignore")).hexdigest()[:16],
                "path": rel,
                "chunk_index": idx,
                "kind": kind,
                "tags": tags,
                "size_chars": len(chunk),
                "sha256": hashlib.sha256(chunk.encode("utf-8", errors="ignore")).hexdigest(),
                "tokens": sorted(set(toks[:1200]))[:500],
                "embedding_model": "local_hash_sparse_v1_64d",
                "embedding": _hash_embedding(chunk, dims=64),
                "preview": re.sub(r"\s+", " ", chunk.strip())[:700],
            }
            chunks.append(record)
    for target in (local_chunks_jsonl, CHUNKS_JSONL):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for rec in chunks:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    by_kind = Counter(c["kind"] for c in chunks)
    by_tag = Counter(tag for c in chunks for tag in c.get("tags", []))
    summary = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "chunk_count": len(chunks),
        "file_count_indexed": len({c["path"] for c in chunks}),
        "cache_ownership": "framework_local",
        "framework_local_cache_dir": str(framework_cache_dir(root)),
        "framework_local_rag_dir": str(local_rag_dir),
        "chunk_store": str(local_chunks_jsonl),
        "central_gui_mirror_chunk_store": str(CHUNKS_JSONL),
        "embedding_strategy": "local deterministic sparse hash embeddings stored under the selected framework; replaceable with enterprise vector DB/OpenAI/Ollama embeddings",
        "counts_by_kind": dict(by_kind),
        "counts_by_tag": dict(by_tag),
        "top_files": [p for p, _ in Counter(c["path"] for c in chunks).most_common(25)],
    }
    for target in (local_summary_json, RAG_SUMMARY_JSON):
        _write_json(target, summary)
    _write_active_framework_pointer(root, summary)
    return summary


def _active_framework_chunk_store() -> Path:
    try:
        data = json.loads(ACTIVE_FRAMEWORK_CACHE_JSON.read_text(encoding="utf-8", errors="replace"))
        path = Path(str(data.get("framework_local_chunk_store") or ""))
        if path.exists():
            return path
    except Exception:
        pass
    return CHUNKS_JSONL


def load_framework_chunks(limit: int = 5000, framework_path: str | Path | None = None) -> list[dict[str, Any]]:
    if framework_path:
        source = framework_chunks_jsonl(Path(framework_path).resolve())
    else:
        source = _active_framework_chunk_store()
    if not source.exists():
        return []
    chunks: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if len(chunks) >= limit:
                break
            try:
                chunks.append(json.loads(line))
            except Exception:
                continue
    return chunks


def query_framework_context(query: str, top_k: int = 10, framework_path: str | Path | None = None) -> dict[str, Any]:
    chunks = load_framework_chunks(framework_path=framework_path)
    scored = sorted(((round(_score(query, c), 3), c) for c in chunks), key=lambda item: item[0], reverse=True)
    hits = [dict(score=s, **{k: v for k, v in c.items() if k != "embedding"}) for s, c in scored if s > 0][:top_k]
    return {
        "ok": True,
        "query": query,
        "top_k": top_k,
        "hit_count": len(hits),
        "cache_source": str(framework_chunks_jsonl(Path(framework_path).resolve())) if framework_path else str(_active_framework_chunk_store()),
        "hits": hits,
        "message": "RAG context retrieved from indexed chunks stored under the selected external framework cache. This reduces prompt repetition and keeps Codex/Ollama focused on the relevant failed scope.",
    }


def _load_package(root: Path) -> dict[str, Any]:
    p = root / "package.json"
    if not p.exists():
        return {}
    try:
        return json.loads(_safe_read(p, limit=120_000))
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def analyze_technology_stack(root: Path) -> dict[str, Any]:
    pkg = _load_package(root)
    deps: dict[str, str] = {}
    if isinstance(pkg, dict):
        for section in ["dependencies", "devDependencies", "peerDependencies"]:
            if isinstance(pkg.get(section), dict):
                deps.update(pkg[section])
    detected = []
    for name, needles in TECH_HINTS.items():
        if any(any(n.lower() in dep.lower() for n in needles) for dep in deps):
            detected.append(name)
    config_files = []
    for name in ["playwright.config.ts", "playwright.config.js", "tsconfig.json", ".env", ".env.local", "docker-compose.yml", "Dockerfile", "eslint.config.js", ".eslintrc.js"]:
        if (root / name).exists():
            config_files.append(name)
    return {"package_name": pkg.get("name") if isinstance(pkg, dict) else None, "detected_stack": sorted(detected), "dependency_count": len(deps), "important_dependencies": {k: deps[k] for k in sorted(deps) if any(h in k.lower() for hints in TECH_HINTS.values() for h in hints) } , "config_files": config_files, "scripts": pkg.get("scripts", {}) if isinstance(pkg, dict) else {}}


def analyze_triggering_flows(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    pkg = _load_package(root)
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    ci_files = [_rel(p, root) for p in _iter_files(root, {".yml", ".yaml"}, limit=200) if p.parts and ".github" in p.parts]
    spec_titles = []
    hook_counts = Counter()
    for spec_rel in (inventory or {}).get("sample_specs", [])[:120]:
        text = _safe_read(root / spec_rel, limit=90_000)
        spec_titles.extend(re.findall(r"\b(?:test|it)\s*\(\s*['\"]([^'\"]+)", text)[:20])
        for hook in ["beforeAll", "beforeEach", "afterEach", "afterAll"]:
            hook_counts[hook] += len(re.findall(rf"\b{hook}\s*\(", text))
    return {"npm_scripts": scripts, "ci_workflow_files": ci_files[:40], "sample_test_titles": spec_titles[:80], "hook_counts": dict(hook_counts), "execution_entrypoints": [k for k, v in scripts.items() if "playwright" in str(v).lower() or "test" in k.lower() or "e2e" in k.lower()]}


def analyze_normal_flows(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    files = _iter_files(root, CODE_SUFFIXES, limit=2500)
    flow_records = []
    counters = Counter()
    for file in files:
        rel = _rel(file, root)
        low = rel.lower()
        if not any(x in low for x in ["pages", "pageobject", "page-object", "tests", "spec"]):
            continue
        text = _safe_read(file, limit=100_000)
        methods = re.findall(r"(?:async\s+)?(?:function\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*[:\w\s<>]*\{", text)
        locators = len(re.findall(r"\b(?:page\.)?(?:locator|getByRole|getByTestId|getByLabel|getByText|getByPlaceholder)\s*\(", text))
        actions = len(re.findall(r"\.(click|fill|check|selectOption|press|goto)\s*\(", text))
        expects = len(re.findall(r"\bexpect\s*\(", text))
        if methods or locators or actions or expects:
            counters["files_with_flow"] += 1
            counters["locator_calls"] += locators
            counters["ui_actions"] += actions
            counters["assertions"] += expects
            flow_records.append({"file": rel, "sample_methods": methods[:25], "locator_calls": locators, "ui_actions": actions, "assertions": expects})
    return {"summary": dict(counters), "flow_files_sample": flow_records[:120], "architecture_observation": "Specs should remain thin; page classes should hold business flows; pageObjects/locator modules should hold locator definitions."}


def analyze_backend_connections(root: Path) -> dict[str, Any]:
    files = _iter_files(root, CODE_SUFFIXES | {".env", ".json", ".md", ".txt"}, limit=3000)
    endpoints = Counter()
    api_files = []
    db_files = []
    db_indicators = []
    for file in files:
        text = _safe_read(file, limit=120_000)
        low = text.lower()
        rel = _rel(file, root)
        urls = re.findall(r"https?://[^'\"\s)]+", text)
        paths = re.findall(r"['\"](/api/[A-Za-z0-9_./{}:-]+)['\"]", text)
        for u in urls + paths:
            endpoints[u[:180]] += 1
        if any(x in low for x in ["waitforresponse", "fetch(", "axios", "request.", "page.route", "/api/"]):
            api_files.append(rel)
        if any(x in low for x in ["database_url", "db_host", "postgres", "mysql", "mongodb", "prisma", "typeorm", "connectionstring", "sequelize"]):
            db_files.append(rel)
            for needle in ["DATABASE_URL", "DB_HOST", "POSTGRES", "MYSQL", "MONGODB", "PRISMA", "TYPEORM", "SEQUELIZE"]:
                if needle.lower() in low:
                    db_indicators.append(needle)
    return {"api_candidate_files": sorted(set(api_files))[:120], "db_candidate_files": sorted(set(db_files))[:80], "detected_endpoint_samples": [e for e, _ in endpoints.most_common(80)], "db_indicators": sorted(set(db_indicators)), "recommendation": "Validate backend/API health before patching UI scripts. For 401/403/500/empty payloads, classify as auth/data/environment/product issue unless the script wait strategy is wrong."}


def analyze_test_data(root: Path) -> dict[str, Any]:
    data_files = [p for p in _iter_files(root, DATA_SUFFIXES, limit=2500) if any(x in _rel(p, root).lower() for x in ["testdata", "test-data", "fixtures", "/data/", ".env"])]
    results = []
    for file in data_files[:250]:
        rel = _rel(file, root)
        text = _safe_read(file, limit=80_000)
        status = "readable"
        detail = ""
        if file.suffix.lower() == ".json":
            try:
                parsed = json.loads(text)
                status = "valid_json"
                detail = f"top_type={type(parsed).__name__}"
            except Exception as exc:
                status = "invalid_json"; detail = f"{type(exc).__name__}: {exc}"
        elif file.suffix.lower() == ".csv":
            try:
                sample = text.splitlines()[:20]
                dialect = csv.Sniffer().sniff("\n".join(sample)) if sample else csv.excel
                rows = list(csv.reader(sample, dialect))
                status = "valid_csv_sample"; detail = f"columns={len(rows[0]) if rows else 0}"
            except Exception as exc:
                status = "csv_needs_review"; detail = f"{type(exc).__name__}: {exc}"
        elif file.suffix.lower() in {".yaml", ".yml"}:
            status = "yaml_readable_not_strictly_validated"
            detail = "PyYAML is not required by this lightweight validator. Enterprise mode can add strict YAML schema validation."
        sensitive_keys = [k for k in ["password", "token", "secret", "api_key", "client_secret"] if k in text.lower()]
        results.append({"file": rel, "status": status, "detail": detail, "sensitive_key_hints": sensitive_keys[:8]})
    return {"test_data_file_count": len(data_files), "files": results, "update_strategy": "Only update testData files when RCA evidence proves data drift or missing seed data. Do not change expected business outcomes as data healing."}


def analyze_infra_vdi_vpn_knowledge(root: Path) -> dict[str, Any]:
    files = _iter_files(root, CODE_SUFFIXES | DATA_SUFFIXES | {".ps1", ".sh", ".cmd"}, limit=3500)
    hits = []
    for file in files:
        text = _safe_read(file, limit=60_000)
        low = text.lower()
        matched = [kw for kw in VPN_VDI_KEYWORDS if kw in low]
        if matched:
            hits.append({"file": _rel(file, root), "matched_terms": sorted(set(matched))[:12], "preview": re.sub(r"\s+", " ", text.strip())[:500]})
    return {"detected_vdi_vpn_hints": hits[:80], "confidence": "medium" if hits else "not_detected_from_repository", "important_note": "The framework can only infer VDI/VM/VPN knowledge from repository files, env examples, scripts, and docs. If the app runs only on a specific VDI/VPN, add that as project metadata in the GUI so RCA can classify network/auth failures correctly instead of patching tests."}


def build_framework_intelligence_v2(root: Path, inventory: dict[str, Any], base_url: str = "") -> dict[str, Any]:
    root = Path(root).resolve()
    INTELLIGENCE_DIR.mkdir(parents=True, exist_ok=True)
    framework_reports_dir(root).mkdir(parents=True, exist_ok=True)
    rag = build_framework_rag_index(root, inventory)
    report = {
        "ok": True,
        "stage": "framework_intelligence_v2_completed",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "base_url": base_url,
        "architecture": {
            "directory_model": (inventory or {}).get("directory_model", {}),
            "pom_compliance": (inventory or {}).get("pom_compliance", {}),
            "spec_count": (inventory or {}).get("spec_count", 0),
            "import_graph_sample": (inventory or {}).get("spec_import_graph_sample", {}),
        },
        "technology_stack": analyze_technology_stack(root),
        "triggering_flows": analyze_triggering_flows(root, inventory or {}),
        "normal_flows": analyze_normal_flows(root, inventory or {}),
        "backend_connections": analyze_backend_connections(root),
        "test_data_validation": analyze_test_data(root),
        "vdi_vm_vpn_knowledge": analyze_infra_vdi_vpn_knowledge(root),
        "rag_index": rag,
        "cache_storage_policy": {
            "selected_framework_owns_cache": True,
            "framework_local_cache_dir": str(framework_cache_dir(root)),
            "framework_local_rag_dir": str(framework_rag_dir(root)),
            "framework_local_reports_dir": str(framework_reports_dir(root)),
            "central_gui_report_mirror": str(INTELLIGENCE_DIR),
            "why": "Existing-framework learning must follow the exact framework path provided by the user. Central files are GUI mirrors only and should not be treated as the source of truth."
        },
        "operating_rules": [
            "Use RAG chunks to retrieve only relevant page/spec/pageObject/helper context before calling Codex/Ollama.",
            "Do not generate duplicate locators or methods when an existing reusable layer is indexed.",
            "Validate API/DB/test data/environment signals before classifying a failure as a script issue.",
            "RCA output must be plain English for humans plus structured JSON for automation.",
            "Use auditable reasoning summaries, not hidden chain-of-thought transcripts.",
        ],
    }
    INTELLIGENCE_V2_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    local_json = framework_reports_dir(root) / "framework-intelligence-v2.json"
    local_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_framework_intelligence_html(report)
    try:
        (framework_reports_dir(root) / "framework-intelligence-v2.html").write_text(INTELLIGENCE_V2_HTML.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except Exception:
        pass
    return report


def _h(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_framework_intelligence_html(report: dict[str, Any]) -> None:
    cards = []
    for key in ["architecture", "technology_stack", "triggering_flows", "normal_flows", "backend_connections", "test_data_validation", "vdi_vm_vpn_knowledge", "rag_index"]:
        cards.append(f"<section class='card'><h2>{_h(key.replace('_',' ').title())}</h2><pre>{_h(json.dumps(report.get(key), indent=2, ensure_ascii=False))}</pre></section>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Framework Intelligence V2</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:#fff;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;overflow:auto}}code{{background:#e2e8f0;padding:2px 6px;border-radius:6px}}</style></head><body>
<h1>Existing Framework Intelligence V2</h1><p>Framework: <code>{_h(report.get('framework_path'))}</code></p>{''.join(cards)}</body></html>"""
    INTELLIGENCE_V2_HTML.write_text(html, encoding="utf-8")




def _plain_status(status: Any) -> str:
    s = str(status or '').lower()
    if s in {'passed', 'expected', 'skipped'}:
        return 'passed'
    if s in {'failed', 'timedout', 'interrupted'}:
        return 'failed'
    return s or 'unknown'


def _plain_reason(rec: dict[str, Any]) -> str:
    status = _plain_status(rec.get('status'))
    if status == 'passed':
        return 'passed'
    text = json.dumps(rec.get('errors') or rec, ensure_ascii=False).lower()
    if 'element(s) not found' in text or ('locator' in text and 'not found' in text):
        return 'locator is missing or not available in DOM'
    if 'strict mode violation' in text:
        return 'locator is ambiguous and matched multiple elements'
    if 'not attached to the dom' in text or 'detached' in text:
        return 'locator became detached from DOM before action'
    if 'intercepts pointer events' in text or 'chakra-modal' in text or 'modal' in text or 'overlay' in text:
        return 'element is blocked by overlay/modal/popup'
    if 'timeout' in text or '30000ms exceeded' in text or 'timed out' in text:
        return 'test timed out while waiting for page, action, locator, API, or data'
    if 'tohaveurl' in text or 'received string' in text:
        return 'page did not navigate to expected URL/state'
    if 'expected' in text and 'received' in text:
        return 'assertion did not match actual product behavior/data'
    return 'failure evidence available in Playwright trace/screenshot/error-context'


def _plain_test_case_rows(rca: dict[str, Any]) -> list[dict[str, Any]]:
    inv = rca.get('failed_inventory') or {}
    records = []
    for rec in inv.get('all_test_cases') or []:
        if not isinstance(rec, dict):
            continue
        status = _plain_status(rec.get('status'))
        records.append({
            'spec': rec.get('spec') or '',
            'line': rec.get('line') or '',
            'test': rec.get('title') or '(whole spec fallback)',
            'status': status,
            'plain_english_reason': _plain_reason(rec),
            'suggested_fix_area': _plain_suggested_fix_area(_plain_reason(rec)),
        })
    if not records:
        for spec in rca.get('failed_specs') or []:
            records.append({'spec': spec, 'line': '', 'test': '(spec-level fallback)', 'status': 'failed', 'plain_english_reason': 'failed spec detected; detailed Playwright JSON was not available', 'suggested_fix_area': 'open native Playwright shard report and trace first'})
    return records


def _plain_suggested_fix_area(reason: str) -> str:
    low = (reason or '').lower()
    if 'locator' in low and 'dom' in low:
        return 'check DOM with Playwright MCP/codegen, then update pageObjects/locator repository and page method'
    if 'ambiguous' in low:
        return 'replace broad selector with stable getByRole/getByTestId/getByLabel in pageObjects'
    if 'detached' in low:
        return 're-query locator after page settles in page method/BasePage; avoid stale ElementHandle'
    if 'overlay' in low or 'modal' in low or 'popup' in low:
        return 'handle blocker in shared popup/browser blocker helper before action'
    if 'timeout' in low:
        return 'check AUT slowness, navigation, data/API, then improve deterministic wait or locator in reusable layer'
    if 'url' in low or 'navigate' in low:
        return 'fix navigation helper or page action, not assertion weakening'
    if 'assertion' in low:
        return 'verify product/data change before changing expected result'
    return 'review trace/screenshot and patch only reusable framework layer'

def plain_english_failure_report(rca: dict[str, Any], failure_text: str = "") -> dict[str, Any]:
    failed_specs = rca.get("failed_specs") or []
    signals = rca.get("signals") or []
    robust = rca.get("robust_multi_signal_rca") or {}
    strategy = robust.get("strategy") or {}
    primary = (strategy.get("selected_chain") or {}).get("name") or (signals[0].get("kind") if signals else "unknown")
    category = str(primary).replace("_", " ").title()
    heal_allowed = bool(strategy.get("auto_heal_allowed", False)) if strategy else bool(signals)
    text_low = (failure_text or json.dumps(rca, ensure_ascii=False)).lower()
    suspected = []
    if any(x in text_low for x in ["timeout", "waiting for", "tobevisible", "locator"]):
        suspected.append("The test most likely waited for an element that was missing, unstable, hidden, or matched by an outdated locator.")
    if any(x in text_low for x in ["intercepts pointer", "modal", "dialog", "overlay", "popup"]):
        suspected.append("A popup, modal, overlay, or dialog may have blocked the expected action.")
    if any(x in text_low for x in ["401", "403", "500", "net::", "econnrefused", "api"]):
        suspected.append("A backend/API, auth, VPN, proxy, or environment issue may be involved. Do not patch UI code until this is checked.")
    if any(x in text_low for x in ["expected", "received", "tohave", "assert"]):
        suspected.append("The failure may be an assertion difference. Changing the expected value should require manual approval unless evidence proves it is a harmless copy update.")
    if not suspected:
        suspected.append("The available evidence is not enough to classify the failure confidently. Run with trace, screenshot, DOM, HAR, and telemetry enabled.")
    report = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "failed_specs": failed_specs,
        "test_case_outcomes": _plain_test_case_rows(rca),
        "plain_english_summary": f"{len(failed_specs)} spec(s) failed. Primary RCA category: {category}. See the test-by-test outcome table for exact passed/failed tests and reasons.",
        "what_likely_happened": suspected,
        "safe_next_action": "Apply self-healing only if the policy gate allows it; otherwise raise manual review/product/environment issue.",
        "auto_heal_status": "allowed_by_current_rca_gate" if heal_allowed else "blocked_or_requires_manual_review",
        "recommended_human_steps": [
            "Open the Playwright trace and screenshot for the failed spec.",
            "Check whether the failed locator belongs in pageObjects rather than the spec file.",
            "Check API status/auth/session/test data before patching UI flow.",
            "Review Codex patch diff; reject assertion weakening, test skips, hard waits, and force clicks.",
            "Rerun failed specs only, then merge the retry result into the original report.",
        ],
        "evidence_links": {
            "rca_json": "generated-playwright/reports/existing-framework/root-cause-report.json",
            "auditable_rca_chain": "generated-playwright/reports/existing-framework/robust-rca/auditable-rca-chain.html",
            "framework_intelligence_v2": "generated-playwright/reports/existing-framework/framework-intelligence-v2.html",
        },
    }
    PLAIN_FAILURE_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_plain_failure_html(report)
    return report


def _write_plain_failure_html(report: dict[str, Any]) -> None:
    bullets = "".join(f"<li>{_h(x)}</li>" for x in report.get("what_likely_happened", []))
    steps = "".join(f"<li>{_h(x)}</li>" for x in report.get("recommended_human_steps", []))
    rows = []
    for rec in report.get('test_case_outcomes') or []:
        cls = 'ok' if rec.get('status') == 'passed' else ('bad' if rec.get('status') == 'failed' else 'warn')
        rows.append(f"<tr><td><code>{_h(rec.get('spec'))}</code></td><td>{_h(rec.get('line'))}</td><td>{_h(rec.get('test'))}</td><td class='{cls}'>{_h(rec.get('status'))}</td><td>{_h(rec.get('plain_english_reason'))}</td><td>{_h(rec.get('suggested_fix_area'))}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Plain English RCA</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}.warn{{color:#b45309;font-weight:800}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}</style></head><body>
<h1>Plain English RCA Report</h1><section class='card'><h2>Summary</h2><p>{_h(report.get('plain_english_summary'))}</p><p class='warn'>{_h(report.get('auto_heal_status'))}</p></section>
<section class='card'><h2>Test-by-test outcome and RCA</h2><p>Format: spec file → test case → passed/failed → plain English reason → safest fix area.</p><table><thead><tr><th>Spec</th><th>Line</th><th>Test</th><th>Status</th><th>Reason</th><th>Safe fix area</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No test-case level evidence found. Open the native Playwright shard report.</td></tr>'}</tbody></table></section>
<section class='card'><h2>What likely happened</h2><ul>{bullets}</ul></section>
<section class='card'><h2>Safe next steps</h2><p>{_h(report.get('safe_next_action'))}</p><ol>{steps}</ol></section></body></html>"""
    PLAIN_FAILURE_HTML.write_text(html, encoding="utf-8")
