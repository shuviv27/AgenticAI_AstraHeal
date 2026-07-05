# Gaps Fixed in This Build

## Gap 1: Playwright scripts generated in isolation

**Fix:** Added Python reuse-aware generator that scans page objects and page methods before generation.

## Gap 2: Inline locators in specs

**Fix:** Specs now call page methods only. Review phase blocks inline locator APIs in generated specs.

## Gap 3: Mixed Playwright files across repo

**Fix:** All framework files are under `generated-playwright/`.

## Gap 4: Functional testcases mixed with automation code

**Fix:** Functional testcase JSON is stored separately under `testcases/` by source type.

## Gap 5: No visibility into reuse decisions

**Fix:** Each generation run creates `generated-playwright/reports/reuse-decision-report.md`.

## Gap 6: RAG unclear or tied to TypeScript

**Fix:** RAG/inventory logic is Python-only under `qa_pipeline/rag/`.

## Remaining future enhancements

- Add real PDF/DOCX parser adapters.
- Add real Jira/Confluence/Test Management API clients.
- Add Qdrant/Chroma-backed vector search for large framework repositories.
- Add Codex-driven DOM inspection/capture mode for unknown locators.
- Add PR creation using GitHub CLI after review passes.
- Add human approval screen in the GUI before writing new locators.
