# Phases and Responsibilities

## Phase 1 — Foundation and Runtime Platform

**Folder:** `qa_pipeline/agents/phase1_foundation/`

Does:

- validates Python/Node/Codex/Ollama availability
- creates required folder structure
- owns event envelope and core configuration
- prepares Docker/local runtime contracts

Does not:

- generate Playwright scripts
- classify failures
- modify source systems

## Phase 2 — Source Intake, Requirement Quality, and RAG/Testcase Preparation

**Folder:** `qa_pipeline/agents/phase2_source_intake_rag/`

Does:

- ingests Jira, SRS, PDF-extracted JSON, Confluence, or Test Management exports
- normalizes them into functional testcase JSON
- stores generated functional testcases under `testcases/<source_type>/<feature>/`
- prepares data for RAG/context retrieval

Output example:

```text
testcases/jira_epics/login/login.scenarios.json
```

## Phase 3 — Reuse-Aware Playwright Code Generation

**Folder:** `qa_pipeline/agents/phase3_reuse_aware_codegen/`

Does:

- scans existing Playwright framework
- checks existing locators in `pageObjects`
- checks existing page methods in `pages`
- reuses what exists
- creates only missing locators/methods
- writes specs into `generated-playwright/tests/generated/`

Critical rule:

```text
spec.ts -> pages.<PageName>.ts -> pageObjects.<PageName>.objects.ts
```

## Phase 4 — Review, Validation, Execution, and CI/CD

**Folder:** `qa_pipeline/agents/phase4_review_execution/`

Does:

- checks folder structure
- blocks inline locators in generated specs
- runs TypeScript build when dependencies are installed
- provides Playwright smoke/execution wrapper

## Phase 5 — Failure Intelligence and Self-Healing

**Folder:** `qa_pipeline/agents/phase5_failure_healing/`

Does:

- classifies execution failures
- identifies locator/wait-related failures
- prepares the repair flow for Codex/Ollama/manual review

## Phase 6 — Reporting, Governance, and Traceability

**Folder:** `qa_pipeline/agents/phase6_reporting_governance/`

Does:

- summarizes testcase, page, pageObject, and generated-spec counts
- writes enterprise summary reports
- supports audit and management traceability
