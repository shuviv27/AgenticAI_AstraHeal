# Human Approval, RCA Gate Override and Robust Self-Healing

This build fixes a confusing self-healing blocker where the runtime approval popup was accepted by the user, but the backend multi-signal RCA gate still stopped the AI patch step with a second generic "human review required" message.

## Correct behavior

The runtime approval popup is now the human approval signal for approved Local PC / VM / VDI workspaces. When the user approves **Fix failed tests safely**, AstraHeal proceeds with a minimal patch attempt while preserving these safeguards:

- Backup is created before patching.
- Patch scope stays limited to failed specs and related page/pageObject/helper files.
- Severe policy violations such as `test.skip`, `test.fixme`, `test.only`, destructive out-of-scope edits, or blocked patterns still rollback.
- The user validates by running failed tests again.
- Rollback remains available from the GUI.

## Strict Enterprise mode

Strict Enterprise mode remains strict. If evidence suggests environment/API/data/assertion drift, AstraHeal can still require manual review or block destructive changes.

## GUI visibility

The GUI/self-healing report now records:

- whether multi-signal RCA allowed the patch automatically,
- whether runtime human approval overrode a low-confidence gate,
- the selected RCA evidence chain,
- the exact failed tests in scope,
- expected patch area,
- files changed,
- backup/rollback details.

This keeps the pipeline deterministic while avoiding a second hidden human-review block after the user already approved the runtime popup.
