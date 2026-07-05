# Human Intervention and Combined Report Guide

## Why human intervention exists

The AI will ask for human intervention when it has evidence of a failure but cannot safely decide the next change by itself. This usually means one of the following:

- The safe patch scope is empty or unclear.
- The framework import chain is unusual and the AI cannot confidently map `spec -> page -> pageObject -> helper`.
- The issue looks like environment, VPN, proxy, certificate, auth/session, test data or AUT/product behavior instead of automation code.
- Codex/Ollama did not produce a patch.
- A patch was created but failed the enterprise confidence or policy gate.

Human intervention does not mean the pipeline stops permanently. It means the user must add review context so AI can continue safely.

## How the human provides updates

Go to **Run & Fix Tests -> Human intervention / manual update memory**.

Use **Show what human input is needed** to generate a request from the latest RCA/self-healing state.

Then fill the relevant fields:

- **Framework code / POM / locator / helper**: when you know which files or locator/page method should change.
- **Environment**: when VPN, proxy, base URL, certificates, browser permission, login session or VM/VDI access is the issue.
- **Test data**: when username, password, order, customer, product, account or fixture data is invalid.
- **AUT/product behavior**: when the application changed or expected behavior must be clarified.
- **Manual fix**: when you already changed files manually and want AI memory to remember it.

Click **Save human update to AI memory**. The update is stored in:

```text
.qa-cache/existing-framework/human-intervention/human-intervention-memory.jsonl
generated-playwright/reports/existing-framework/human-intervention-report.html
```

The next RCA/self-healing prompt includes this memory.

## Framework-level vs environment-level updates

Framework-level examples:

```text
Approved safe files:
pages/LoginPage.ts
pageObjects/LoginPage.objects.ts
utils/BasePage.ts

Instruction:
Login button text changed from Login to Sign in. Update the LoginPage reusable locator only. Do not edit the spec.
```

Environment-level examples:

```text
AUT works only from Horizon VDI, not from VM.
Use base URL https://qa.example.internal.
Certificate must be accepted before first run.
VPN must be connected.
```

Test-data examples:

```text
Use QA user automation.user@example.com.
OTP disabled for this user.
Order ID must be created before running checkout specs.
```

## Combined first-run + failed-only rerun report

The native Playwright HTML report generated after failed-only rerun usually contains only the rerun tests. This build now creates a separate combined report that preserves both stages:

```text
generated-playwright/reports/existing-framework/consolidated-report.html
generated-playwright/reports/existing-framework/consolidated-report.json
```

It shows:

- All tests from the first selected-script run.
- Which tests failed in the first run.
- Which failed tests were rerun.
- Which tests passed after fix/rerun.
- Which tests are still failing.
- Links to the archived first-run Playwright report and the current failed-only Playwright report.

Open it from GUI: **Logs & Reports -> Open combined first-run + rerun report**.
