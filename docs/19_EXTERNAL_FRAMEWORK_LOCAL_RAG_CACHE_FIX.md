# External Framework Local RAG Cache Fix

## Why this change exists

AstraHeal supports user-owned Playwright frameworks that live outside the AstraHeal AI solution folder. The selected external framework is the source of truth for tests, pages, pageObjects, fixtures, helpers, and framework memory.

Earlier builds indexed the correct external framework content, but stored the RAG chunk/cache source of truth inside the AstraHeal repo cache. That worked for simple single-framework demos, but it could confuse users and could create stale memory when switching between multiple external frameworks.

## New behavior

When the user clicks **Deep learn this framework with AI** or any existing-framework learning action, AstraHeal now stores framework-owned RAG/cache under the exact framework path provided by the user:

```text
<your-existing-framework>/.qa-cache/existing-framework/rag/framework-chunks.jsonl
<your-existing-framework>/.qa-cache/existing-framework/rag/framework-rag-summary.json
<your-existing-framework>/.qa-cache/existing-framework/reports/framework-intelligence-v2.json
<your-existing-framework>/.qa-cache/existing-framework/reports/framework-intelligence-v2.html
<your-existing-framework>/.qa-cache/existing-framework/agentic-memory/framework-understanding-memory.json
<your-existing-framework>/.qa-cache/existing-framework/agentic-memory/framework-understanding-memory.jsonl
```

The AstraHeal repo still keeps central GUI mirror files so existing report buttons and older endpoints continue to work:

```text
<AstraHeal>/generated-playwright/reports/existing-framework/framework-intelligence-v2.html
<AstraHeal>/.qa-cache/existing-framework/active-framework-cache.json
```

Those central files are compatibility mirrors/pointers only. The selected framework's `.qa-cache` is now the source of truth.

## Existing features preserved

- Existing framework learning
- RAG search for RCA/self-healing
- AI full-control framework fix
- Playwright MCP assist
- Local PC / Central VM / worker VM execution
- Playwright report generation
- Failed-only rerun
- Combined first-run + rerun report
- RCA and self-healing

## Important note

The cache is hidden under `.qa-cache`. If your organization does not want generated cache files committed to Git, add this to the external framework `.gitignore`:

```text
.qa-cache/
```
