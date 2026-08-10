# AI Functional Walkthrough Execution and Playwright Generation Fix — v0.6.2

## Reported behaviour

The browser opened, but most scenarios stopped at the first username or password step. The generation workflow then treated the whole walkthrough as unusable and blocked all script generation.

## Root causes

1. Excel normalisation correctly removed raw credentials from persisted testcase JSON, but the values were not handed to the next walkthrough request.
2. Provider failure or an unusable provider response caused immediate human takeover even when the live DOM already contained a strong, unique accessible element.
3. Authenticated browser sessions were not reused by credential profile across the ten scenarios.
4. Data-changing QA steps were disabled by default, so submit/save/create/transfer steps could not complete.
5. The generator used an all-or-nothing walkthrough gate rather than retaining verified evidence from partially completed scenarios.
6. Walkthrough and generation diagnostics were mainly visible as raw JSON instead of readable HTML reports.

## Implemented design

### Volatile Excel credential bridge

- Scenario credentials are extracted only for the process-memory vault.
- Normalised testcase JSON receives role-specific environment-variable names but never the raw values.
- The load operation stores a short-lived feature credential map.
- The walkthrough start operation copies the map to a one-time run-ID vault.
- The agent consumes the run vault once.
- Nothing is written to SQLite, LangSmith, generated source, reports, screenshots or test-data modules.

Supported roles include:

- `store_coworker`
- `off_hour_agent`
- `admin_user`
- `default`

### Sequential authenticated execution

- Scenarios remain in source order.
- One browser context is created per unique credential profile.
- Login is completed once per profile.
- Later scenarios using the same account reuse the authenticated session and verified login locators.
- MFA or identity verification remains a supervised human step; AstraHeal resumes automatically after the authenticated page is detected.

### Live DOM fallback

The selected AI provider may reason over the visible DOM, but it is no longer a single point of failure. If the provider returns invalid JSON, no element, or an unusable choice, the agent ranks the actual visible elements using:

- accessible name
- role
- label
- placeholder
- test ID
- stable ID
- expected action type
- unique locator verification

High-confidence login fields and buttons can therefore execute without unnecessary human takeover.

### QA mutation safety

The GUI now enables approved testcase mutations by default for URLs visibly marked as:

- QA
- test
- sandbox
- staging/stage
- dev
- UAT
- localhost

Production-like URLs remain blocked even when the checkbox is selected.

### Partial-evidence generation

The generator now loads all verified walkthrough evidence even when one or more scenarios remain incomplete. It checks each required locator independently:

1. Reuse an existing framework locator when available.
2. Use a verified walkthrough locator when available.
3. Block only the unresolved new locator when strict evidence is enabled.

No file is changed before this gate passes.

### Generated test-data and immediate execution

- Newly generated specs import `stepValue` from a feature-specific TypeScript data module.
- Ordinary workbook values are stored in that module.
- Credentials are represented only by scenario-specific environment-variable names.
- An `.env.example` file contains names only.
- The GUI can execute the newly generated specs once, sequentially, using the still-volatile workbook credential profiles.
- Structural load failures roll back generated changes. Live application failures retain the generated files and evidence for RCA/self-healing.
- Runtime logs are redacted against every volatile credential before being written to reports.

### Reports

The **Logs & Reports** tab now includes:

- Open latest functional walkthrough report
- Open latest Playwright generation report

The walkthrough HTML report shows scenario progress, completed steps, verified locators and blockers. The generation HTML report lists unresolved live-locator evidence by scenario and step.

## Operational sequence

1. Load and normalise the Excel/document source.
2. Confirm that the GUI reports the expected number of volatile credential profiles.
3. Start **AI walkthrough application (no code)**.
4. Complete MFA/CAPTCHA manually when requested.
5. Review the HTML walkthrough report.
6. Preview placement.
7. Generate and add tests.
8. Review the HTML generation report and validation evidence.

## Validation

- Attached workbook: 10 scenarios and 10 complete volatile credential profiles detected.
- Raw credential values in normalised JSON: none.
- Role-specific environment bindings: present.
- Automated tests: 66 passed.
- Python compilation: passed.
- GUI JavaScript syntax: passed.
- FastAPI report routes: registered once.

A live Salesforce run could not be performed in the build sandbox because outbound/local browser navigation is blocked by administrator policy. The code does not claim live Salesforce locator success without evidence from the target Central VM/VDI environment.
