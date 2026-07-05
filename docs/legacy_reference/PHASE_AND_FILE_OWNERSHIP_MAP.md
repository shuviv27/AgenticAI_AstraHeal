# Phase and File Ownership Map

This map helps users identify which file belongs to which feature and phase.

## Phase 1 — Foundation

```text
qa_pipeline/agents/phase1_foundation/doctor.py
qa_pipeline/core/paths.py
qa_pipeline/core/config.py
qa_pipeline/core/commands.py
infra/docker/docker-compose.yml
```

Purpose: environment checks, repo folders, cross-platform command handling, Docker infrastructure.

## Phase 2 — Source Intake and Functional Testcases

```text
qa_pipeline/parsers/source_parser.py
qa_pipeline/agents/phase2_source_intake_rag/ingest.py
testcases/jira_epics/<feature>/<feature>.scenarios.json
testcases/srs/<feature>/<feature>.scenarios.json
testcases/pdf_docs/<feature>/<feature>.scenarios.json
```

Purpose: turn Jira/SRS/PDF/DOCX/pasted steps into functional testcases first.

## Phase 3 — Reuse-Aware Code Generation

```text
qa_pipeline/rag/framework_inventory.py
qa_pipeline/agents/phase3_reuse_aware_codegen/reuse_generator.py
qa_pipeline/agents/phase3_reuse_aware_codegen/locator_strategy.py
qa_pipeline/agents/phase3_reuse_aware_codegen/codex_prompt.py
```

Generated output:

```text
generated-playwright/pageObjects/<PageName>Page.objects.ts
generated-playwright/pages/<PageName>Page.ts
generated-playwright/tests/generated/<feature>.spec.ts
```

Purpose: generate Playwright TypeScript without isolated scripts.

## Phase 4 — Review, Execution and Playwright MCP

```text
qa_pipeline/agents/phase4_review_execution/reviewer.py
qa_pipeline/agents/phase4_review_execution/executor.py
qa_pipeline/mcp/playwright_mcp.py
mcp/playwright-mcp.json
.vscode/mcp.json
```

Purpose: static review, Playwright execution, MCP readiness.

## Phase 5 — Failure Intelligence

```text
qa_pipeline/agents/phase5_failure_healing/failure_classifier.py
```

Purpose: classify failure messages into actionable categories.

## Phase 6 — Reporting and Governance

```text
qa_pipeline/agents/phase6_reporting_governance/reporter.py
generated-playwright/reports/
```

Purpose: summary reports, reuse decision report, quality review report.
