# AstraHeal AI v0.6.8 — Playwright Validation Rollback Fix

## Reported failure

The GUI reported that all ten attempted Playwright specs failed validation and were rolled back after browser grounding completed partially.

## Confirmed root cause

The generated specs called `assertRequiredEnvironment(...)` at module scope. `playwright test --list` imports every spec while discovering tests, so it executed runtime-data checks before any test ran.

The workbook contained executable credentials, but also generic non-secret labels such as:

- `Appointment Type`
- `Date`
- `Time`
- `Product`
- `Activity Date`

v0.6.7 converted those labels into mandatory environment variables such as `APPOINTMENT_TYPE` and `APPOINTMENT_DATE`. Since the workbook did not provide concrete values for them, Playwright discovery stopped at import time. The TypeScript syntax, generated page methods, and locator contract could all be valid while the discovery command still failed.

## Corrections

1. Credential preflight is now declared inside `test.beforeAll(...)`, not at spec-module scope. Playwright `--list` can discover tests without executing runtime credentials.
2. Only sensitive username/password bindings are mandatory runtime inputs.
3. Generic non-sensitive workbook labels are optional overrides with deterministic QA defaults:
   - dates use today/tomorrow in `MM/DD/YYYY`
   - time uses `10:00 AM`
   - product reuses scenario product context, otherwise `Computer`
   - appointment type uses `In Store` unless browser evidence or an override supplies a better value
   - notes use a unique generated QA value
4. Optional defaults remain overridable through the generated `.env.example` variables.
5. If an older generated spec still raises a missing-runtime-data error during `--list`, AstraHeal classifies it as runtime-data preflight, retains generated files, and does not roll back structurally valid page methods/locators/specs.
6. Playwright validation now receives volatile workbook credentials in its validation environment for backward compatibility.
7. The generation response includes the first concrete validation diagnostic instead of only a generic rollback message.
8. HTML/JSON generation reports separate missing required credentials from optional data overrides and list every generated default.

## Generated spec pattern

```ts
test.describe('new_feature', () => {
  test.beforeAll(() => {
    assertRequiredEnvironment(
      newFeatureDataRequiredEnvironment['TC_01'],
    );
  });

  test('TC_01 - Verify web lead creation', async ({ page }) => {
    const data = newFeatureData['TC_01'];
    const screen = new SalesforcePage(page);
    // ...
  });
});
```

## Runtime data pattern

```ts
get username() {
  return requiredSecret(
    'SALESFORCE_STORE_COWORKER_TC_01_USERNAME',
  );
},

get appointmentDate() {
  return optionalRuntime('APPOINTMENT_DATE', futureDate(1));
},

get appointmentTime() {
  return optionalRuntime('APPOINTMENT_TIME', '10:00 AM');
},
```

## Safety and compatibility

- Existing framework analysis, LangGraph workflows, LangSmith, SQLite memory, AI providers, MCP, codegen support, distributed execution, RCA, self-healing, and operation cancellation remain unchanged.
- Credentials remain in the volatile backend vault and the Git-ignored `.env.astraheal.local` runtime file only.
- No raw workbook credential is written to generated TypeScript, reports, SQLite, or LangSmith.
- Browser grounding remains optional and non-blocking.
