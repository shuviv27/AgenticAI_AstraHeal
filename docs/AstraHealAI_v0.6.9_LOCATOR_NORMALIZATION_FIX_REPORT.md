# AstraHeal AI v0.6.9 — Locator normalisation and Salesforce login resilience

## Reported failure

A generated locator repository stored the literal accessible name `<Log In to sandbox>`. The angle brackets came from manual testcase notation and do not exist in the AUT. SmartLocator therefore tried valid Playwright strategies with an invalid value and found no element.

## Root cause

The generator correctly recognised the action as a button click, but the final locator-value pipeline did not distinguish documentation wrappers from real UI text. Browser-grounding evidence could also carry the same wrapper into the generated locator repository. The runtime then escaped the angle brackets and searched for them literally.

## Implemented corrections

1. **Testcase UI-label normalisation**
   - `<Log In to sandbox>` becomes `Log In to Sandbox`.
   - `[Submit]`, smart quotes and HTML entities are normalised.
   - Gherkin example placeholders remain protected until scenario-outline substitution.

2. **Verified-evidence normalisation**
   - Browser-walkthrough locator values and fallback values are normalised before TypeScript is generated.
   - Generated descriptions may retain the human instruction, but locator values contain only actual candidate text.

3. **Salesforce login locator bundle**
   - role button by accessible name
   - role link and visible-text alternatives
   - `#Login`
   - `input[name="Login"]`
   - `input[type="submit"][value*="sandbox" i]`
   - submit/button value, title and ARIA-label selectors

4. **Runtime compatibility for already-generated files**
   - SmartLocator normalises each candidate before resolution.
   - `Log In`, `Login`, `Sign In` and spacing/case variants are matched semantically.
   - Existing values accidentally wrapped in `<...>` can resolve after replacing the runtime utility.

5. **Stronger diagnostics**
   - SmartLocator reports normalised candidates, match count and visibility for each candidate.
   - Blank `Last error` is replaced by useful evidence even when a locator simply matches zero elements.

6. **Generation quality gate**
   - The POM contract validator reports `malformed_locator_value` when any generated locator value still contains documentation angle brackets.
   - Invalid source is rejected before live browser execution.

## Example generated definition

```ts
logInToSandboxButtonLocator: {
  strategy: 'role',
  role: 'button',
  value: 'Log In to Sandbox',
  description: 'Log In to sandbox button',
  fallbacks: [
    { strategy: 'role', role: 'link', value: 'Log In to Sandbox' },
    { strategy: 'text', value: 'Log In to Sandbox' },
    {
      strategy: 'css',
      value: '#Login, input[name="Login"], input[type="submit"][value*="sandbox" i]'
    }
  ]
}
```

## Validation

- 89 automated tests passed.
- Attached workbook: 10 scenarios and 10 generated specs.
- 91 page methods and 89 locator definitions generated.
- Zero POM contract issues.
- Zero TypeScript parse diagnostics.
- Zero angle-wrapped generated locator values.
- Local Chromium fixture confirmed both accessible-role and Salesforce CSS candidates resolve the `Log In to Sandbox` submit control.

## Deployment note

Regenerate the affected tests after installing v0.6.9. To repair already-generated source without regeneration, copy the updated `generated-playwright/utils/SmartLocator.ts` and `generated-playwright/utils/locatorFactory.ts`, then remove angle brackets from any locator repository values.

A live Salesforce session was unavailable in the build environment. Final DOM verification must be run on the Central VM/VDI with AUT access.
