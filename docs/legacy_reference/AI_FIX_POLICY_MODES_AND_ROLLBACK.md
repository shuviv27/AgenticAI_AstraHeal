# AI Fix Policy Modes and Rollback

This build changes the AI self-healing behavior so local PC and VM/VDI users can keep AI patches for validation instead of seeing repeated severe-policy rollback.

## Modes

### Approved local/VM workspace
Recommended for a user-owned local PC or approved VM workspace. The system creates a backup, applies Codex changes, records every changed file, keeps the patch for failed-only rerun validation, and provides rollback. Normal locator/page/helper/spec changes become review warnings instead of automatic rollback.

### VM/VDI approved workspace
Same practical behavior for Horizon/VDI execution where the framework folder is approved for automated patching.

### Strict enterprise
Use this for shared protected branches or environments where the AI must rollback whenever any strict guardrail violation is detected.

## What is still blocked in all modes

The system still rolls back destructive test-disabling edits such as `test.skip`, `test.fixme`, and `.only`.

## Recommended flow

1. Select **Approved local/VM workspace**.
2. Run chosen tests.
3. Explain failures and check MCP evidence.
4. Create safe fix plan.
5. Fix failed tests safely.
6. Review `changed_files` in the self-healing report.
7. Run failed tests again.
8. If the patch is bad, click **Rollback last AI fix**.
