# BrowserStack Execution-Only Adapter

This build adds an optional BrowserStack execution lane without moving AstraHeal's AI brain out of the client VM.

## What moves to BrowserStack

Only browser execution moves to BrowserStack Automate:

- Playwright browser sessions
- shard execution
- BrowserStack dashboard session evidence

## What stays on the VM

The following remain on the same VM/Central VM:

- AI provider connectivity
- existing framework learning and RAG/cache
- Playwright MCP assist preparation
- RCA and self-healing
- safe fix plan and approval workflow
- code patching, backup and rollback
- failed-only inventory
- combined first-run + rerun reports
- AstraHeal report routing and history

## Required setup

Set credentials before starting AstraHeal GUI:

```bat
setx BROWSERSTACK_USERNAME "your_browserstack_username"
setx BROWSERSTACK_ACCESS_KEY "your_browserstack_access_key"
```

Close CMD/PowerShell and open a fresh terminal.

For a private client application reachable only from the VM/VDI network, keep BrowserStack Local enabled in the GUI. AstraHeal writes a per-run `browserstack.yml` under the selected external framework:

```text
<framework>/.astraheal/browserstack/<run-id>/<shard-id>/browserstack.yml
```

AstraHeal sets `BROWSERSTACK_CONFIG_FILE` for the SDK so it does not overwrite the user's root `browserstack.yml`.

## GUI path

```text
Run & Fix Tests
→ Local PC / Central VM execution
→ Optional: Local/VM parallel browser sharding
→ Execution provider for selected tests
→ BrowserStack Automate cloud browsers only
```

Use **Check BrowserStack readiness** before execution.

## Reports

BrowserStack execution writes local artifacts into the selected external framework:

```text
<framework>/reports/existing-framework/browserstack-runs/<run-id>/<shard-id>/
<framework>/.aiqa-history/reports/browserstack-execution-report.html
```

A central GUI mirror is also written:

```text
generated-playwright/reports/existing-framework/browserstack-execution-report.html
```

Native Playwright HTML/JSON, failed inventory, RCA, self-healing and combined reports continue using AstraHeal's existing report pipeline.

## Important enterprise note

BrowserStack Local tunnel must be approved by the client's security/network team because BrowserStack browsers need a secure path back to the internal application from the VM/VDI network.
