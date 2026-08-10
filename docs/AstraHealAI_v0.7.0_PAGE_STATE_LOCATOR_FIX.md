# AstraHeal AI v0.7.0 — Page-State-Aware Locator Fix

## Problem addressed

A multi-stage Salesforce login can reuse the same native submit control in more than one application state:

1. Username page: `Log In to Sandbox`
2. Password page: `Log In`

The earlier browser collector inferred the element role as `button`, but for native `<input type="submit">` controls it did not read the HTML `value` attribute. The result could contain a valid role with an empty or undefined accessible name. The generator then produced guessed role/name locators for each occurrence.

A second issue was found during validation: verified CSS selectors were passed through UI-label normalisation, which could remove closing quotes or brackets from selectors such as `input[name="Login"]`.

## Fixes

### Native button accessible names

The live DOM collector now derives button names from the `value` attribute only for button-like input types:

- `button`
- `submit`
- `reset`
- `image`

It does not read entered values from username, password, email, phone, or ordinary text inputs.

### Stable control identity across page states

Live evidence now retains a stable control signature generated from:

- test ID
- DOM ID
- `name` attribute
- element tag
- input type
- frame URL

The username and password login stages can therefore be recognised as the same control when the stable attributes remain unchanged even though the displayed accessible name changes.

### Candidate hierarchy

Verified candidates now include, where available:

1. test ID
2. role and accessible name
3. associated label
4. placeholder
5. stable DOM ID
6. stable `name` attribute
7. native input type and `value`
8. visible text

For Salesforce login controls, both stages receive stable fallbacks such as:

```ts
#Login
input[name="Login"]
button[name="Login"]
```

plus observed/compatible names:

```text
Log In to Sandbox
Log In
Login
Sign In
Continue
```

### Invalid locator rejection

The following are no longer accepted as verified evidence:

- missing role for a role locator
- empty accessible name
- `undefined`
- `null`
- `none`
- unsupported ARIA role
- ambiguous locator matching more than one visible element

The Page Object contract validator rejects these before source changes are accepted.

### Strategy-aware normalisation

UI labels are normalised, but CSS and XPath values are preserved exactly. This prevents selector corruption.

### SmartLocator diagnostics

On failure, SmartLocator now reports:

- current URL
- normalised candidates
- candidate match count
- visibility
- whether the candidate was unique
- a sanitised list of visible controls

SmartLocator does not silently choose `.first()` when multiple elements match.

## Validation performed

### Automated repository tests

```text
93 passed
```

### Live two-stage browser simulation

A local Chromium simulation used the same native input control twice:

```html
<input id="Login" name="Login" type="submit" value="Log In to Sandbox">
```

After the first click, the page replaced it with:

```html
<input id="Login" name="Login" type="submit" value="Log In">
```

Results:

```text
Stage 1 role:                button
Stage 1 accessible name:    Log In to Sandbox
Stage 1 exact locator:       verified
Stage 2 role:                button
Stage 2 accessible name:    Log In
Stage 2 exact locator:       verified
Stable control signature:   identical across both stages
```

### Attached workbook generation

```text
Scenarios:                   10
Generated specs:             10
POM contract issues:          0
Undefined role values:        0
Undefined locator values:     0
Stable login selector:       present
```

## Files changed

- `qa_pipeline/agentic/functional_walkthrough.py`
- `qa_pipeline/agentic/browser_grounded_generation.py`
- `qa_pipeline/modules/playwright_ts_generator/enterprise_add_new_tests.py`
- `generated-playwright/utils/SmartLocator.ts`
- `generated-playwright/utils/locatorFactory.ts`
- `qa_pipeline/agents/existing_framework_control/controller.py`
- `qa_pipeline/agents/phase5_failure_healing/self_healing_agent.py`
- `tests/test_functional_walkthrough_agent.py`

## Deployment note

The private Salesforce AUT was not available in the build environment. The local two-state browser flow and attached-workbook generation were validated. Final application-specific execution must be performed from the Central VM/VDI that can access the sandbox.
