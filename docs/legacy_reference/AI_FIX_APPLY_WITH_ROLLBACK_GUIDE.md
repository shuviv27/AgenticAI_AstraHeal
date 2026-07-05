# AI Fix Apply with Rollback Guide

This build changes the self-healing behavior from strict auto-revert to an enterprise validation workflow.

## Previous behavior

When Codex/Ollama produced a patch and the confidence or policy review required human approval, the system could automatically restore the backup and show:

`A patch was attempted but reverted by confidence/policy guard.`

This protected the framework, but it also prevented users from validating a useful patch.

## New behavior

When the patch stays inside the resolved failed-test scope and does not contain severe blocked patterns, the system:

1. Creates a backup of allowed files.
2. Applies the AI patch.
3. Records changed files.
4. Runs deterministic policy/confidence review.
5. Keeps the patch for user validation even if review warnings exist.
6. Asks the user to run failed tests again.
7. Provides a rollback button if validation is bad.

## Still blocked or rolled back

The system still protects against severe issues such as:

- Files outside failed-test scope.
- Files outside the selected framework root.
- `test.skip`, `test.only`, `test.fixme`.
- Blind `waitForTimeout`.
- Raw locator additions directly in spec files when policy blocks them.
- `force:true` as default strategy.

## Granting additional files for AI patching

Use the Human Intervention section:

1. Set Decision = `Approved files for AI patching`.
2. Add exact framework files under `Files/folders human approves as safe for AI to patch`.
3. Save human update to AI memory.
4. Click `Fix failed tests safely` again.

Only exact files inside the selected framework root are accepted.

## Rollback

Click `Rollback last AI fix` to restore changed files from the backup root shown in the self-healing report.

