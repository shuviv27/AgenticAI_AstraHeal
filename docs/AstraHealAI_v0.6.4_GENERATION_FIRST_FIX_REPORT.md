# AstraHeal AI v0.6.4 — Generation-First Playwright Fix Report

## Reported problem

Playwright generation stopped before changing files because hundreds of new locators did not have verified AI functional walkthrough evidence. The browser walkthrough was therefore acting as an all-or-nothing prerequisite for the higher-priority script-generation workflow.

## Resolution

- Removed the no-code walkthrough controls and report button from the GUI.
- Reduced the Add New Tests workflow to Load → Preview → Generate.
- Disabled walkthrough evidence by default in the GUI, API route and generator controller.
- Removed the hard generation gate for missing walkthrough evidence.
- Kept the old strict request parameter for compatibility, but it is ignored.
- Added a provisional locator review list to HTML and JSON generation reports.
- Improved generated locator labels and fallback candidates.
- Selected automatic strongest-match placement by default.
- Made post-generation live execution optional and unchecked by default.
- Separated structural generation success from optional live execution failure.

## Attached workbook validation

The supplied workbook normalised to 10 scenarios and produced 10 individual Playwright TypeScript specs. It produced 247 provisional locator review items, but none blocked generation. TypeScript parse validation returned zero diagnostics for all changed TypeScript files.

## Limitations

Without access to the private AUT, no offline generator can guarantee that every newly inferred locator exactly matches the live DOM. v0.6.4 prioritises code generation and produces robust accessible candidate bundles; optional Playwright MCP/codegen or evidence-grounded RCA can refine locators after generation without preventing source creation.
