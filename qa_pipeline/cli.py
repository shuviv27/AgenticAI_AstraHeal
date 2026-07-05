from __future__ import annotations

import argparse
import json
from pathlib import Path

from qa_pipeline.agents.phase1_foundation.doctor import run_doctor
from qa_pipeline.agents.phase2_source_intake_rag.ingest import ingest_source
from qa_pipeline.agents.phase3_reuse_aware_codegen.codex_prompt import build_codex_prompt
from qa_pipeline.agents.phase3_reuse_aware_codegen.reuse_generator import ReuseAwarePlaywrightGenerator
from qa_pipeline.agents.phase4_review_execution.executor import execute_feature
from qa_pipeline.agents.phase4_review_execution.reviewer import run_review, run_smoke
from qa_pipeline.agents.phase5_failure_healing.failure_classifier import classify_failure
from qa_pipeline.agents.phase6_reporting_governance.reporter import generate_summary
from qa_pipeline.agents.existing_framework_control.controller import (
    analyze_existing_framework,
    execute_existing_framework,
    analyze_existing_failure,
    self_heal_existing_framework,
    execute_existing_failed_only,
    generate_existing_selector_health_report,
    install_existing_framework_robust_harness,
    read_existing_framework_intelligence_v2,
    search_existing_framework_rag,
)
from qa_pipeline.agents.api_framework_control.controller import (
    generate_api_framework,
    analyze_api_framework,
    execute_api_framework,
    analyze_api_failure,
    self_heal_api_framework,
    read_api_failed_inventory,
    search_api_framework_rag,
)
from qa_pipeline.core.io import read_json
from qa_pipeline.core.api_docker_runtime import api_docker_runtime_status, api_docker_pull_images, api_docker_start_tools
from qa_pipeline.core.paths import REPO_ROOT, ensure_dirs, feature_testcase_path
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.mcp.playwright_mcp import mcp_status, write_playwright_mcp_configs
from qa_pipeline.parsers.source_parser import normalize_source_to_json
from qa_pipeline.rag.framework_inventory import scan_framework


def cmd_doctor(args: argparse.Namespace) -> None:
    print(json.dumps(run_doctor(), indent=2))


def cmd_inventory(args: argparse.Namespace) -> None:
    inv = scan_framework()
    print(json.dumps(inv.to_dict(), indent=2))


def cmd_generate_testcases(args: argparse.Namespace) -> None:
    ensure_dirs()
    normalized = normalize_source_to_json(Path(args.source), args.source_type, args.feature, base_url=getattr(args, "base_url", ""))
    out = ingest_source(normalized, args.source_type, args.feature)
    print(f"Functional testcase file generated: {out}")
    print(json.dumps(read_json(out), indent=2))


def cmd_ingest(args: argparse.Namespace) -> None:
    out = ingest_source(Path(args.source), args.source_type, args.feature)
    print(f"Functional testcase file generated: {out}")


def _generate_with_provider(feature: str, source_type: str, provider: str, model: str) -> dict:
    ensure_dirs()
    testcase_path = feature_testcase_path(source_type, feature)
    testcase_set = read_json(testcase_path)
    inv = scan_framework()

    if provider == "codex":
        codex = CodexCliProvider(REPO_ROOT)
        prompt = build_codex_prompt(feature, testcase_set, inv)
        result = codex.run(prompt)
        llm_message = result.stdout if result.ok else result.stderr
        # Always run deterministic guardrail after Codex to enforce folder/reuse contract.
        gen_result = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
        return {"llm_ok": result.ok, "llm_message": llm_message[-4000:], "created": [d.__dict__ for d in gen_result.created], "reused": [d.__dict__ for d in gen_result.reused], "files": gen_result.files}
    if provider == "ollama":
        ollama = OllamaProvider(model=model)
        prompt = build_codex_prompt(feature, testcase_set, inv)
        result = ollama.chat(prompt)
        gen_result = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
        return {"llm_ok": result.ok, "llm_message": (result.text if result.ok else result.error)[-4000:], "created": [d.__dict__ for d in gen_result.created], "reused": [d.__dict__ for d in gen_result.reused], "files": gen_result.files}
    gen_result = ReuseAwarePlaywrightGenerator().generate(feature, source_type)
    return {"llm_ok": True, "llm_message": "deterministic reuse-aware generator", "created": [d.__dict__ for d in gen_result.created], "reused": [d.__dict__ for d in gen_result.reused], "files": gen_result.files}


def cmd_generate(args: argparse.Namespace) -> None:
    print(json.dumps(_generate_with_provider(args.feature, args.source_type, args.provider, args.model), indent=2))


def cmd_review(args: argparse.Namespace) -> None:
    report = run_review(skip_npm=args.skip_npm)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


def cmd_execute(args: argparse.Namespace) -> None:
    report = execute_feature(feature=args.feature, project=args.project, use_mcp=not args.no_mcp, headed=args.headed)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_mcp_status(args: argparse.Namespace) -> None:
    write_playwright_mcp_configs(headless=not args.headed)
    print(json.dumps(mcp_status(), indent=2))


def cmd_smoke(args: argparse.Namespace) -> None:
    raise SystemExit(run_smoke())


def cmd_classify(args: argparse.Namespace) -> None:
    print(json.dumps(classify_failure(args.error), indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    out = generate_summary()
    print(f"Report generated: {out}")


def cmd_run_e2e(args: argparse.Namespace) -> None:
    print("Step 1/7: doctor")
    print(json.dumps(run_doctor(), indent=2))
    print("Step 2/7: framework inventory scan")
    scan_framework()
    print("Step 3/7: generate functional testcases from source")
    normalized = normalize_source_to_json(Path(args.source), args.source_type, args.feature, base_url=getattr(args, "base_url", ""))
    out = ingest_source(normalized, args.source_type, args.feature)
    print(out)
    print("Step 4/7: review generated functional testcases")
    print(json.dumps(read_json(out), indent=2))
    print("Step 5/7: generate reuse-aware Playwright TypeScript")
    print(json.dumps(_generate_with_provider(args.feature, args.source_type, args.provider, args.model), indent=2))
    print("Step 6/7: static review")
    report = run_review(skip_npm=args.skip_npm)
    print(json.dumps(report, indent=2))
    print("Step 7/7: execution")
    if args.execute:
        exec_report = execute_feature(feature=args.feature, project=args.project, use_mcp=not args.no_mcp, headed=args.headed)
        print(json.dumps(exec_report, indent=2))
    else:
        print("Execution skipped. Run with --execute or use GUI Execute step.")
    generate_summary()
    raise SystemExit(0 if report["ok"] else 1)




def cmd_existing_framework_analyze(args: argparse.Namespace) -> None:
    print(json.dumps(analyze_existing_framework(args.framework_path, provider=args.provider, model=args.model, base_url=args.base_url), indent=2))


def cmd_existing_framework_execute(args: argparse.Namespace) -> None:
    report = execute_existing_framework(
        args.framework_path,
        project=args.project,
        headed=args.headed,
        base_url=args.base_url,
        execution_mode=args.execution_mode,
        shards=args.shards,
        targets=args.targets,
        test_command=args.test_command,
        auto_install=not args.no_install,
    )
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_existing_framework_rca(args: argparse.Namespace) -> None:
    print(json.dumps(analyze_existing_failure(args.framework_path, provider=args.provider, model=args.model, base_url=args.base_url), indent=2))


def cmd_existing_framework_heal(args: argparse.Namespace) -> None:
    report = self_heal_existing_framework(args.framework_path, provider=args.provider, model=args.model, base_url=args.base_url, apply_patch=args.apply)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_existing_framework_rerun_failed(args: argparse.Namespace) -> None:
    report = execute_existing_failed_only(args.framework_path, project=args.project, headed=args.headed, base_url=args.base_url, execution_mode=args.execution_mode, shards=args.shards, test_command=args.test_command)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_existing_framework_install_harness(args: argparse.Namespace) -> None:
    print(json.dumps(install_existing_framework_robust_harness(args.framework_path), indent=2))


def cmd_existing_framework_selector_health(args: argparse.Namespace) -> None:
    print(json.dumps(generate_existing_selector_health_report(args.framework_path), indent=2))


def cmd_existing_framework_intelligence_v2(args: argparse.Namespace) -> None:
    print(json.dumps(read_existing_framework_intelligence_v2(), indent=2))


def cmd_existing_framework_rag_search(args: argparse.Namespace) -> None:
    print(json.dumps(search_existing_framework_rag(args.query, top_k=args.top_k), indent=2))



def cmd_api_framework_generate(args: argparse.Namespace) -> None:
    print(json.dumps(generate_api_framework(feature=args.feature, source_type=args.source_type, flavor=args.flavor, base_url=args.base_url, provider=args.provider, model=args.model), indent=2))


def cmd_api_framework_analyze(args: argparse.Namespace) -> None:
    print(json.dumps(analyze_api_framework(framework_path=args.framework_path, flavor=args.flavor, base_url=args.base_url), indent=2))



def cmd_api_docker_status(args: argparse.Namespace) -> None:
    print(json.dumps(api_docker_runtime_status(), indent=2))


def cmd_api_docker_pull(args: argparse.Namespace) -> None:
    report = api_docker_pull_images()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_api_docker_start_tools(args: argparse.Namespace) -> None:
    report = api_docker_start_tools()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)

def cmd_api_framework_execute(args: argparse.Namespace) -> None:
    report = execute_api_framework(framework_path=args.framework_path, flavor=args.flavor, base_url=args.base_url, targets=args.targets, test_command=args.test_command, auto_install=not args.no_install, use_docker=args.use_docker)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_api_framework_rca(args: argparse.Namespace) -> None:
    print(json.dumps(analyze_api_failure(framework_path=args.framework_path, flavor=args.flavor, provider=args.provider, model=args.model, base_url=args.base_url), indent=2))


def cmd_api_framework_heal(args: argparse.Namespace) -> None:
    report = self_heal_api_framework(framework_path=args.framework_path, flavor=args.flavor, provider=args.provider, model=args.model, base_url=args.base_url, apply_patch=args.apply)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


def cmd_api_framework_failed_inventory(args: argparse.Namespace) -> None:
    print(json.dumps(read_api_failed_inventory(), indent=2))


def cmd_api_framework_rag_search(args: argparse.Namespace) -> None:
    print(json.dumps(search_api_framework_rag(args.query, top_k=args.top_k), indent=2))

def cmd_serve_gui(args: argparse.Namespace) -> None:
    try:
        import uvicorn  # type: ignore
    except Exception as exc:
        raise SystemExit("GUI dependencies missing. Run: python -m pip install -r requirements.txt") from exc
    uvicorn.run(
        "qa_pipeline.gui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=bool(getattr(args, "access_log", False)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python Agentic AI QA Pipeline CLI")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("inventory")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("generate-testcases")
    p.add_argument("--source", required=True)
    p.add_argument("--source-type", default="jira", choices=["jira", "srs", "pdf", "confluence", "test_management"])
    p.add_argument("--feature", required=True)
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_generate_testcases)

    p = sub.add_parser("ingest")
    p.add_argument("--source", required=True)
    p.add_argument("--source-type", default="jira", choices=["jira", "srs", "pdf", "confluence", "test_management"])
    p.add_argument("--feature", required=True)
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("generate")
    p.add_argument("--feature", required=True)
    p.add_argument("--source-type", default="jira")
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("review")
    p.add_argument("--skip-npm", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("execute")
    p.add_argument("--feature", default="login")
    p.add_argument("--project", default="chromium")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--no-mcp", action="store_true")
    p.set_defaults(func=cmd_execute)

    p = sub.add_parser("mcp-status")
    p.add_argument("--headed", action="store_true")
    p.set_defaults(func=cmd_mcp_status)

    p = sub.add_parser("smoke")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("classify-failure")
    p.add_argument("--error", required=True)
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("report")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("existing-framework-analyze")
    p.add_argument("--framework-path", required=True, help="Root folder of the existing Playwright framework")
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_existing_framework_analyze)

    p = sub.add_parser("existing-framework-execute")
    p.add_argument("--framework-path", required=True)
    p.add_argument("--project", default="chromium")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--base-url", default="")
    p.add_argument("--execution-mode", default="sequential", choices=["sequential", "distributed"])
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--targets", default="", help="Optional comma/newline separated spec paths/patterns inside the existing framework")
    p.add_argument("--test-command", default="", help="Optional custom command. Use {targets} placeholder to inject selected specs.")
    p.add_argument("--no-install", action="store_true")
    p.set_defaults(func=cmd_existing_framework_execute)

    p = sub.add_parser("existing-framework-rca")
    p.add_argument("--framework-path", default="")
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_existing_framework_rca)

    p = sub.add_parser("existing-framework-heal")
    p.add_argument("--framework-path", default="")
    p.add_argument("--provider", default="codex", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--base-url", default="")
    p.add_argument("--apply", action="store_true", help="Apply the Codex patch. Without this, only a proposal is produced.")
    p.set_defaults(func=cmd_existing_framework_heal)

    p = sub.add_parser("existing-framework-rerun-failed")
    p.add_argument("--framework-path", default="")
    p.add_argument("--project", default="chromium")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--base-url", default="")
    p.add_argument("--execution-mode", default="sequential", choices=["sequential", "distributed"])
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--test-command", default="")
    p.set_defaults(func=cmd_existing_framework_rerun_failed)

    p = sub.add_parser("existing-framework-install-harness")
    p.add_argument("--framework-path", required=True)
    p.set_defaults(func=cmd_existing_framework_install_harness)

    p = sub.add_parser("existing-framework-selector-health")
    p.add_argument("--framework-path", default="")
    p.set_defaults(func=cmd_existing_framework_selector_health)

    p = sub.add_parser("existing-framework-intelligence-v2")
    p.set_defaults(func=cmd_existing_framework_intelligence_v2)

    p = sub.add_parser("existing-framework-rag-search")
    p.add_argument("--query", default="page object locators fixtures api db test data execution flows")
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(func=cmd_existing_framework_rag_search)


    p = sub.add_parser("api-docker-status")
    p.set_defaults(func=cmd_api_docker_status)

    p = sub.add_parser("api-docker-pull")
    p.set_defaults(func=cmd_api_docker_pull)

    p = sub.add_parser("api-docker-start-tools")
    p.set_defaults(func=cmd_api_docker_start_tools)

    p = sub.add_parser("api-framework-generate")
    p.add_argument("--feature", default="api")
    p.add_argument("--source-type", default="srs")
    p.add_argument("--flavor", default="playwright", choices=["playwright", "restassured"] )
    p.add_argument("--base-url", default="")
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.set_defaults(func=cmd_api_framework_generate)

    p = sub.add_parser("api-framework-analyze")
    p.add_argument("--framework-path", default="")
    p.add_argument("--flavor", default="auto", choices=["auto", "playwright", "restassured"])
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_api_framework_analyze)

    p = sub.add_parser("api-framework-execute")
    p.add_argument("--framework-path", default="")
    p.add_argument("--flavor", default="auto", choices=["auto", "playwright", "restassured"])
    p.add_argument("--base-url", default="")
    p.add_argument("--targets", default="")
    p.add_argument("--test-command", default="")
    p.add_argument("--no-install", action="store_true")
    p.add_argument("--use-docker", action="store_true", help="Run API tests in Docker-managed runtime so Java/Maven/Node are not required on host.")
    p.set_defaults(func=cmd_api_framework_execute)

    p = sub.add_parser("api-framework-rca")
    p.add_argument("--framework-path", default="")
    p.add_argument("--flavor", default="auto", choices=["auto", "playwright", "restassured"])
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--base-url", default="")
    p.set_defaults(func=cmd_api_framework_rca)

    p = sub.add_parser("api-framework-heal")
    p.add_argument("--framework-path", default="")
    p.add_argument("--flavor", default="auto", choices=["auto", "playwright", "restassured"])
    p.add_argument("--provider", default="codex", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--base-url", default="")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_api_framework_heal)

    p = sub.add_parser("api-framework-failed-inventory")
    p.set_defaults(func=cmd_api_framework_failed_inventory)

    p = sub.add_parser("api-framework-rag-search")
    p.add_argument("--query", default="api request response schema auth endpoint payload testData")
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(func=cmd_api_framework_rag_search)

    p = sub.add_parser("serve-gui")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--access-log", action="store_true", help="Show every HTTP request in the terminal. Disabled by default so GUI runtime polling does not flood the console.")
    p.set_defaults(func=cmd_serve_gui)

    p = sub.add_parser("run-e2e")
    p.add_argument("--source", default="samples/jira/login_epic.json")
    p.add_argument("--source-type", default="jira")
    p.add_argument("--feature", default="login")
    p.add_argument("--base-url", default="")
    p.add_argument("--provider", default="deterministic", choices=["deterministic", "codex", "ollama"])
    p.add_argument("--model", default="llama3")
    p.add_argument("--skip-npm", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--project", default="chromium")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--no-mcp", action="store_true")
    p.set_defaults(func=cmd_run_e2e)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
