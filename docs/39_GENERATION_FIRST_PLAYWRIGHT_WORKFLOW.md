# Generation-First Playwright Workflow — v0.6.4

## Purpose

Playwright script generation from approved functional testcases is the primary workflow. The optional browser walkthrough is no longer exposed in the GUI and is never required before generation.

## GUI sequence

1. Load / normalize testcase source.
2. Preview placement.
3. Generate & add tests.

Post-generation execution is optional and disabled by default.

## Locator decision order

For every executable testcase step, AstraHeal uses this order:

1. Reuse an existing page method.
2. Reuse an existing locator.
3. Reuse optional verified locator evidence when explicitly supplied through the API.
4. Create a SmartLocator candidate bundle from the functional instruction.
5. Record the new locator in the generation report for optional MCP/codegen refinement.

Missing live-browser evidence never blocks generation.

## SmartLocator candidate generation

Generated candidates prefer accessible user-facing selectors:

- `getByRole`
- `getByLabel`
- `getByPlaceholder`
- `getByText`
- existing framework-specific locator repositories

Manual wording is normalised into likely accessible names. For example:

- `valid Store Co-worker username` → `Username`
- `valid password` → `Password`
- `Login button` → `Login`
- `App Launcher (waffle icon)` → `App Launcher`
- `Customer Central from search results` → `Customer Central`

The original instruction remains as a fallback and as report context.

## Validation and rollback

Structural validation includes TypeScript parsing and Playwright test discovery when the local dependencies are available.

- Structural generation failure: rollback generated changes.
- Live AUT execution failure after successful structural generation: retain generated files for grounded RCA and self-healing.
- Missing locator evidence: report as a review item; do not rollback or block generation.

## Backward compatibility

The legacy walkthrough API and agent implementation remain available for existing integrations, but they are hidden from the GUI. The legacy `require_walkthrough_evidence=true` input is accepted and deliberately ignored so older clients cannot block generation.
