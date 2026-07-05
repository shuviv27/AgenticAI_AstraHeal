# Page-source-aware Playwright generation

This build keeps the original concept intact: Python agents perform RAG/orchestration, and TypeScript Playwright framework files stay under `generated-playwright/`.

## What changed

The pipeline can now use an optional website page-source/DOM text file during generation. This is useful for modern web applications built with React/Chakra/Next.js where visible buttons may be `<a>` tags, spans, generated classes, or aria-labelled components.

For Acima-like pages, the analyzer extracts:

- headings such as `Shop with Acima Leasing`
- CTA links such as `Shop In-store`, `Shop Online`, `Shop now`, `Start Shopping`
- aria labels and hrefs such as `/en/find-a-store`, `/en/shop-online`, `/en/marketplace`
- footer/navigation links
- image alt text
- important marketing copy

The generated locator priority becomes:

1. existing pageObjects locator
2. uploaded/static page-source locator hint
3. live dynamic crawl evidence
4. role/text/label fallback
5. guarded self-healing suggestion after failure

## GUI usage

1. Project Setup: set the website URL, for example `https://www.acima.com/en`.
2. Requirement Input: upload SRS/PDF/DOCX/TXT or paste requirements.
3. Optional but recommended: upload website page source / saved DOM HTML/TXT.
4. Generate functional testcases.
5. Review Markdown testcases.
6. Generate reusable Playwright.
7. Open the `Page-source map` tab to verify extracted DOM evidence.
8. Run Static Review and then execute tests.

## Generated files

- `generated-playwright/reports/page-source-map.json`
- `.qa-cache/page_source_maps/<feature>.json`
- `testcases/<source>/<feature>/<feature>.scenarios.md`
- `generated-playwright/pageObjects/<Feature>Page.objects.ts`
- `generated-playwright/pages/<Feature>Page.ts`
- `generated-playwright/tests/generated/<feature>.spec.ts`

## Important rule

Specs remain locator-free. The flow remains:

```text
spec.ts -> pages/<Feature>Page.ts -> pageObjects/<Feature>Page.objects.ts
```

