# Simple Acima Homepage RCA Fix

## Root cause

The failing script asked the framework to verify the visible text `home page`.
That text is not displayed on the Acima page. `home page` is a page concept, not a UI label.
The actual visible hero evidence is:

- `Shop with Acima Leasing`
- `Shop In-store`
- `Shop Online`
- `Our flexible lease-to-own solutions...`

Therefore `verifyHomePage()` must verify page readiness and real hero elements, not literal text `home page`.

## Fixes included

1. Added `AcimaPage.verifyHomePage()` as a concrete page-level method:
   - verifies page loaded
   - verifies hero heading
   - verifies `Shop In-store`
   - verifies `Shop Online`

2. Added aliases for generated/simple scripts:
   - `verifyShopInStoreButton()`
   - `verifyShopOnlineButton()`
   - `verifyHeroContent()`

3. Updated parser/generator guardrails:
   - generic `home page` verification no longer generates `verifyVisibleText('home page')`
   - `Verify Acima home page hero content loads correctly` generates page-loaded + concrete hero assertions

4. Updated `BasePage.ts` behavior:
   - no hard `networkidle`
   - no full-page scroll before every action/assertion
   - scroll only after the normal role/text/body checks fail

## Expected generated simple scenario

```ts
await acimaPage.goto('https://www.acima.com/en');
await acimaPage.verifyHomePage();
await acimaPage.verifyShopWithAcimaLeasingHeading();
await acimaPage.verifyShopInStoreButton();
await acimaPage.verifyShopOnlineButton();
```

## Validation performed

- Python parser compile: PASS
- Reuse generator compile: PASS
- Locator strategy compile: PASS
- Parser check for `Verify Acima home page hero content loads correctly`: PASS
- Guardrail check for generic `home page`: PASS
- Static grep check: no generated `verifyVisibleText('home page')` or `smartVerifyTextOrAction('home page')`

Playwright browser execution should be run on the user's machine because the sandbox cannot access the live Acima website and does not have npm dependencies installed.
