# Executable Named-Data Playwright Generation

## Problem corrected

Earlier generated specs used an opaque helper:

```ts
stepValue("TC_01", "step_8_expected")
```

That helper mapped synthetic step numbers to values and required users to configure environment variables manually. It also treated prose outcomes such as "Customer Central home page is successfully loaded" as literal UI text.

## Generated structure in v0.6.7

Each generated testcase now imports one named scenario object:

```ts
import {
  newFeatureData,
  newFeatureDataRequiredEnvironment,
  assertRequiredEnvironment,
} from '../../testData/new_feature.data';

assertRequiredEnvironment(newFeatureDataRequiredEnvironment['TC_01']);

const data = newFeatureData['TC_01'];
```

The spec uses readable properties:

```ts
await screen.gotoApplication(data.applicationUrl);
await screen.fillValidStoreCoWorkerHenrySMS(data.username);
await screen.fillValidPassword(data.password);
await screen.fillFirstName(data.firstName);
await screen.verifyLeadStatusIsNew(data.expectedLeadStatus);
```

Every call is checked by the Page Object contract validator:

```text
spec call -> page method -> locator reference -> locator definition
```

## Runtime credentials

Credentials extracted from the uploaded workbook are transferred through the volatile backend credential vault and, at generation time, written to:

```text
<selected-framework>/.env.astraheal.local
```

The generator automatically adds this file to `.gitignore` and creates:

```text
testData/astraheal.runtime-env.ts
```

The runtime loader reads `.env.astraheal.local` before scenario data is validated. Each generated spec validates only its own required variables at module load, before Playwright launches a browser.

The local file is intended for the selected developer/QA machine only. It must not be committed, shared in reports, or copied into CI. CI should provide the same variable names through its secret manager.

## Assertion behaviour

The generator separates concrete values from prose outcomes.

| Testcase instruction | Generated assertion input |
|---|---|
| Verify Customer Central home page is displayed | Visibility only |
| Verify Lead Name is `Testlead Simsamta` | `data.expectedLeadName` |
| Verify Lead Status is `New` | `data.expectedLeadStatus` |
| Verify Lead Source is `Web` | `data.expectedLeadSource` |

Generic phrases such as "successfully loaded", "is displayed", or "matches expected value" are not passed as UI text.

## Browser grounding and locator generation

The generation route still attempts browser grounding first when enabled. It uses the selected AI provider, Playwright accessibility/DOM evidence, MCP readiness, and verified locator capture. AI-discovered prerequisite actions such as `Log In to Sandbox` are inserted into the ordered scenario when verified.

If the private AUT is inaccessible, generation remains non-blocking and uses existing framework locators first, followed by SmartLocator candidate bundles. Such provisional locators remain visible in the generation report for MCP/codegen refinement.

## Missing non-credential data

Some workbooks contain labels rather than values, for example `Appointment Type`, `Date`, or `Product`. AstraHeal does not invent these values. They are listed in the generated `.env.example` and the report as missing runtime data. The browser-grounding agent may replace them with verified live selections when the AUT is available.
