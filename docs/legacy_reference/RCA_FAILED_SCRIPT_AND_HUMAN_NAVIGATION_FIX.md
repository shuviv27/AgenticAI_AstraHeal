# RCA Failed-Script Proposals and Human Navigation Click Fix

## Why this build exists

Two enterprise-quality issues were addressed:

1. RCA must not treat the full suite as one large failure. It now reads the failed-test inventory and analyzes each failed spec one-by-one, writing a human-readable fix proposal for each failed script.
2. Header/navigation clicks must mimic a user action. The generator must not replace a nav click with a direct route such as `page.goto('/marketplace')`. It must click the visible nav item and then verify the resulting dropdown/menu/page outcome.

## RCA behavior

After a failed Playwright execution, `Analyze Root Cause` reads:

```text
generated-playwright/reports/failed-tests.json
```

Then it writes:

```text
generated-playwright/reports/root-cause-failed-scripts-report.json
generated-playwright/reports/root-cause-failed-scripts-report.md
```

Each failed script receives:

- likely problem
- confidence
- current URL captured from the error
- failed target/action
- human-readable explanation
- proposed patch order
- guardrails

Runtime logs also show the script-by-script RCA progress.

## Navigation click behavior

For Jira/SRS steps like:

```text
Click <Shop> button available on navigation bar
Expected result: dropdown/menu options are populated
```

The parser now generates:

```json
{ "action": "click_nav_option", "target": "Shop", "value": "", "navigation_behavior": "human_click_then_dropdown_or_menu_verification" }
{ "action": "verify_nav_menu_or_page_options", "target": "Shop navigation options", "value": "Shop" }
```

The generated Playwright method calls:

```ts
await this.clickHeaderNavigationOption(this.getLocator(HomePageObjects.navShopLink), 'Shop', '');
await this.verifyHeaderNavigationMenuOrPageOptions('Shop', expectedOptionsText);
```

The base page helper resolves the exact header/nav item first, hovers, clicks, and waits for a dropdown/menu/page outcome. It does not perform direct navigation through `page.goto()`.
