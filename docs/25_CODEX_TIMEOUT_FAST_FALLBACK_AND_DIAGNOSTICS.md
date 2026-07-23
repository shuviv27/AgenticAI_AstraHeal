# Codex Timeout Fast Fallback and Diagnostics

## Problem fixed

AstraHeal could show this message during **Fix failed tests safely** even when the user had already approved the popup:

> No framework files were changed because Codex patch execution did not complete successfully. Codex CLI timed out after 300s

This did **not** mean the user approval was missing, and it did **not** always mean Codex login was bad. It meant the Codex CLI command was started but did not finish before the backend timeout.

## Why this can happen

Codex login only confirms authentication. The actual patch command can still take too long when:

- the repo is large,
- the patch scope contains many files,
- the prompt contains too much failure/RAG/history context,
- the VM/VDI is slow,
- enterprise proxy/network slows Codex reasoning,
- Codex decides to analyze but not edit.

## Fix added

AstraHeal now:

1. Uses a smaller default Codex patch prompt scope.
2. Lowers prompt excerpt size and RAG hits for faster apply attempts.
3. Clearly identifies timeout as a Codex execution timeout, not a fresh-login or missing-human-approval issue.
4. If the user already approved the popup and Codex times out, AstraHeal runs a bounded deterministic locator/actionability fallback under the same backup, policy validation and rollback controls.
5. The self-healing report shows Codex diagnostics, attempt status, timeout details and deterministic fallback details.

## Runtime tuning

For large repositories, users can increase the timeout:

```bat
set ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS=420
```

For faster attempts on slow VMs, keep the defaults and grant exact pageObject/helper files in the Human Update section.

## Safety unchanged

AstraHeal still blocks or rolls back unsafe changes such as:

- `test.skip`, `test.only`, `test.fixme`
- out-of-scope file edits
- blind long waits
- force click by default
- assertion weakening without evidence

