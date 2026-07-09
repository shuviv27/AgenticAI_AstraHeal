# AstraHeal Deterministic MCP RCA Repair Strategy

This enhancement strengthens RCA/self-healing for the three recurring failure groups seen on VM/VDI and BrowserStack-style execution:

1. **Locator missing, hidden, or not available in DOM**
   - RCA now creates a test-level repair recipe.
   - The recipe tells AstraHeal/Codex to use Playwright MCP/codegen/accessibility snapshot on the failed page state.
   - If a stable locator is found, the patch target is the pageObject/locator repository first, then the page method/BasePage helper only when DOM re-render requires re-query.

2. **Slow AUT, navigation/state wait, or blocked locator/action**
   - RCA now separates timeout caused by slow AUT from locator or blocker issues.
   - Safe plan points to shared navigation/action/blocker helpers instead of raw spec sleeps.
   - Deterministic fallback can patch common BasePage/action helper patterns with bounded DOM-ready and actionability guards.

3. **Trace/screenshot review required**
   - RCA marks evidence as insufficient and points the user to native Playwright shard artifacts.
   - It avoids blind patching until trace/screenshot/MCP evidence identifies the failed element or state.

The visible RCA output is an auditable checklist, not hidden chain-of-thought. Existing Playwright execution, report routing, failed-only rerun, BrowserStack execution adapter, and AI provider flows are preserved.
