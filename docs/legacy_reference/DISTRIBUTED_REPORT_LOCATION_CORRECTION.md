# Distributed Report Location Correction

## Why this change was made

When the existing Playwright framework is outside the AI/RAG solution repo, the distributed execution report must not be treated as a generated-playwright-only artifact.

The framework should carry its own execution history because different users/VDIs may run the same framework from different machines.

## Correct primary location

For an external framework path like:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

The primary distributed execution report is now written here:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework\.aiqa-history\reports\distributed-execution-report.html
D:\AI_QA_WORKSPACE\client-playwright-framework\.aiqa-history\reports\distributed-execution-report.json
D:\AI_QA_WORKSPACE\client-playwright-framework\.aiqa-history\reports\distributed-execution-plan.json
```

## Central GUI mirror

The AI solution still keeps a mirror for GUI convenience:

```text
<AI-solution-repo>\generated-playwright\reports\existing-framework\distributed-execution-report.html
```

This mirror is not the source of truth. It is only used to make opening reports from the VM-hosted GUI easier.

## GUI behavior

The **Open framework-local distributed report** button opens the report from the existing framework path using this safe server route:

```text
/api/module2/framework-artifact/distributed-report?framework_path=<existing-framework-path>
```

This route serves only:

```text
<existing-framework>\.aiqa-history\reports\distributed-execution-report.html
```

It does not expose arbitrary files from the machine.

## Recommended enterprise rule

Use hybrid report storage:

1. Framework-local `.aiqa-history/reports` = durable source of truth.
2. Central VM AI/RAG cache = cross-framework index and GUI mirror.
3. Large Playwright artifacts such as screenshots, traces, videos may remain in normal Playwright report/test-results folders.
4. Commit only lightweight `.aiqa-history` summaries to Git if client policy allows it. Do not commit screenshots, secrets, tokens, videos, or large trace files.
