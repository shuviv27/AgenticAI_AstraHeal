# Execution Mode and Progress Fix

This build fixes the Generated Playwright execution flow only.

## What changed

1. The Generated Playwright panel now has an **Execution mode** selector:
   - **Sequential / safe headed debug**: default and recommended for headed execution. It runs all active generated specs in one Playwright process with one worker.
   - **Distributed / sharded parallel**: optional. It runs selected specs across the user-provided shard count and merges blob reports.

2. The Distributed Shards field is controlled by the user.

3. Active Jira/SRS source scoping is unchanged. If an active Jira Epic context exists, both sequential and distributed execution run only that active batch.

4. Sequential mode avoids the earlier Windows/Docker/Playwright merge delay where browsers could close and reports could exist while the GUI still showed the progress bar around 88-92%.

5. Distributed report merge now has a bounded timeout and `PLAYWRIGHT_HTML_OPEN=never`, so it should not wait indefinitely for report UI behavior.

## Recommended usage

For demo/debugging:

```text
Generated Playwright -> Execution mode: Sequential / safe headed debug
Generated Playwright -> Execute Generated Test - Headed
```

For large suites:

```text
Generated Playwright -> Execution mode: Distributed / sharded parallel
Generated Playwright -> Distributed shards: 5 or 10
Generated Playwright -> Execute Generated Test - Headless
```

For enterprise-only distributed execution, the existing Enterprise Stack distributed run buttons are preserved.
