# AstraHeal AI v0.6.3 — Adaptive Goal-Driven Walkthrough Fix Report

## Requested behaviour

The functional walkthrough must intelligently reconcile high-level testcase steps with the real application flow. A source step such as “enter password” may require an unlisted browser transition, for example clicking “Log In to Sandbox” after entering the username.

## Root limitation in v0.6.2

The walkthrough used a mostly literal one-step/one-action mapping. When the direct target was absent, it moved quickly to supervised human guidance. Any human-discovered prerequisite was not guaranteed to become a first-class step for later Playwright generation.

## Implemented correction

- Added an adaptive observe-plan-act-verify loop for every source step.
- Added an AI prerequisite-action planner with strict structured output and live DOM element validation.
- Added deterministic safe transition fallback.
- Added page-state loop detection and per-step action limits.
- Added safe transition filters for destructive actions.
- Persisted inserted prerequisite steps and verified locators into the enhanced testcase payload.
- Updated the generator to accept `adaptive_intermediate_verified` evidence.
- Added readable adaptive actions to walkthrough HTML/JSON reports.
- Added GUI configuration for maximum prerequisite actions.
- Fixed missing `placeholder` support in the bundled generated Playwright locator factory.

## Two-stage login result

```text
Excel goal: Enter valid password
Current page: username page; password target unavailable
Adaptive action: Click Log In to Sandbox
New page: password page
Original goal retried: password target verified and filled
Generated sequence: clickLogInToSandbox() → fillPassword(...)
```

## Safety

The planner may insert only a verified click on a supplied live element. It cannot invent locators, insert destructive business actions, or claim the source goal succeeded before the original target is verified.

## Validation

- Full automated repository tests: 73 passed
- Adaptive transition selection test: passed
- End-to-end fake browser state transition test: passed
- Enhanced testcase expansion test: passed
- Playwright generation ordering test: passed
- Python compilation: passed
- GUI JavaScript syntax: passed
- FastAPI import and route registration: passed

A real external browser navigation test could not run in the build sandbox because Chromium returned `ERR_BLOCKED_BY_ADMINISTRATOR`. The adaptive browser loop was validated with deterministic stateful browser doubles and generator integration tests. Final AUT validation should run on the Central VM/VDI with application network access.
