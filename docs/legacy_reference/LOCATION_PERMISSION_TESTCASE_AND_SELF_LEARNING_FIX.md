# Location Permission Testcase + Self-Learning Fix

## Problem fixed

Some Jira stories use natural language such as:

```text
Click <Shop In-Store> button & handle the location permission by browser
```

The earlier parser treated `location permission handled` as visible application text and generated a failing assertion such as:

```ts
await this.smartVerifyTextOrAction('location permission handled');
```

That is wrong. Browser permissions are capabilities handled by Playwright context, not text displayed on the page.

## New generation behavior

The Jira/SRS parser now converts permission instructions into action semantics:

```json
{ "action": "handle_location_permission", "target": "browser location permission" }
```

For store finder outcomes such as `Shop list will populate`, it now adds:

```json
{ "action": "verify_store_list_populated", "target": "store list" }
```

## New Playwright behavior

Generated specs/pages now call inherited BasePage methods:

```ts
await page.handleLocationPermissionIfRequested();
await page.verifyStoreListPopulated();
```

`handleLocationPermissionIfRequested()` grants geolocation/notification permissions, handles app-level location buttons when present, and uses a configurable ZIP/postal fallback if the application still asks for location data.

Default ZIP:

```env
TEST_ZIP_CODE=84101
```

Override it in `.env` or PowerShell for your application test data:

```powershell
$env:TEST_ZIP_CODE="10001"
```

## Self-learning guardrail

The failure-learning matrix now records this pattern and recommends:

```text
Treat permission-handling phrases as browser actions, not visible text assertions; use handle_location_permission and ZIP/geolocation fallback.
```

This prevents the same mistake from being repeated in future Jira/SRS generation.
