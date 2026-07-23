# Header Navigation Click Fix

## Problem
Some generated Playwright scripts treated a Jira step like `Click <Shop> button available on navigation bar` as a generic text click. On Acima this could hit a similarly named body/hero/store page control such as `Shop In-store`, which navigated to `/find-a-store`. The script then tried to verify menu text such as `Shop Marketplace` on the wrong page and failed.

## Fix
The parser and generator now distinguish header/navigation actions from body actions:

- `Click <Shop> button available on navigation bar` becomes `click_nav_option`, not a generic `click` or body-wide `click_navigate`.
- The generated method uses `clickHeaderNavigationOption`, scoped to `nav`, `header`, `[role="navigation"]`, exact accessible name, and expected href hints.
- The generator no longer converts expected menu options into separate body-wide text assertions.
- The expected option list becomes one business-aware verification: `verify_nav_menu_or_page_options`.
- For Acima, the verifier accepts real site wording such as `Near Me` / `Online` as equivalents for `Shop Nearby Stores` / `Shop Online stores`.
- If the click lands on `/find-a-store` while the target is top navigation `Shop`, the framework raises a clear wrong-control-click error.

## Generated POM behavior
The click remains in `HomePage` because it is a header navigation control. The landing page or menu verification is also handled using reusable Page Object methods rather than testcase-specific page files.

Example:

```ts
await homePage.clickNavShopAndVerifyNavigationOrMenu();
await homePage.verifyShopNavigationOptionsMenuOrPageOptions();
```

## Why this matters
This prevents duplicate or ambiguous locators and fixes cases where exact nav items such as `Shop` were confused with page-body CTAs such as `Shop In-store`.
