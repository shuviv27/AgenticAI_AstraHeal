# Runtime Human Approval Popup for AI Fixes

This build adds a human-in-the-loop approval layer before applying AI fixes to an existing Playwright framework.

## Why this was added

Earlier, strict policy decisions could block or rollback AI patches without asking the user at runtime. In local PC, VM, or approved VDI workspaces, users often want the AI to apply the patch, show impacted files, rerun failed tests, and rollback only if validation fails.

## What happens now

When the user clicks **Fix failed tests safely**, the GUI first opens a runtime approval popup.

The popup shows:

- failed test count
- safe files/folders currently resolved
- policy risks
- questions AI needs from the user
- best-practice recommendation
- editable guidance box
- editable safe files/folders box

The user can choose:

- **Approve & Apply Fix**: AI applies the patch with backup, records changed files, and keeps rollback available.
- **Deny / Do not change files**: no files are changed; denial is logged.
- **Cancel**: closes the popup without applying the fix.

## Best practice

Prefer approving pageObject/page/page method/helper updates before spec edits. Do not approve patches that hide failures using `test.skip`, `test.fixme`, or `.only` unless you intentionally want to quarantine tests outside the self-healing flow.

## Runtime approval memory

User guidance from the popup is saved into project memory and reused by later RCA/self-healing attempts.

Memory location:

```text
.qa-cache/existing-framework/human-intervention/human-intervention-memory.jsonl
```

Report location:

```text
generated-playwright/reports/existing-framework/human-intervention-report.html
```

## Enterprise VM/VDI behavior

This approval popup works in Local PC, VM Control Plane, and VM + VDI Agent modes. The popup appears in the GUI browser session. The actual patch is applied on the machine where the selected existing framework path is accessible.
