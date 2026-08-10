# Adaptive Goal-Driven Functional Walkthrough — v0.6.3

## Problem solved

Manual testcases often describe the business intention but omit browser-specific transitions.

Example source:

1. Enter username.
2. Enter password.
3. Log in.

Actual application flow:

1. Enter username.
2. Click **Log In to Sandbox**.
3. Wait for the password page.
4. Enter password.
5. Click the final **Login** button.

A literal executor fails because the password field is not present when source step 2 begins.

## New execution model

The walkthrough agent now treats each source step as a **goal** rather than one fixed UI action.

```text
Source goal
   ↓
Observe current page and visible accessible elements
   ↓
Can the intended target be uniquely verified?
   ├─ Yes → execute the source goal
   └─ No  → ask the adaptive planner for one safe prerequisite action
                 ↓
          verify the prerequisite locator
                 ↓
          execute the prerequisite
                 ↓
          observe the new page and retry the original goal
```

The loop is bounded by `walkthrough_max_intermediate_actions`, which defaults to 6 per source step.

## Planning layers

### AI adaptive planner

When Codex, OpenAI, DeepSeek, Perplexity or Ollama is selected, the provider receives:

- Current URL and page title
- Sanitised visible clickable elements
- The source testcase goal
- Previously inserted prerequisite actions
- The permitted action contract

It may select one supplied element for a safe prerequisite click. It cannot invent an element.

### Deterministic safe fallback

If the provider is unavailable, returns malformed output, or selects an invalid element, AstraHeal applies deterministic accessible-DOM matching.

It recognises common transitions such as:

- Continue / Next / Proceed
- Log In to Sandbox / Sign In to tenant
- Identity-provider or SSO selection
- Use another account
- Wizard section opening
- Cookie and consent acceptance

It rejects intermediate controls indicating destructive or business-changing actions such as delete, purchase, transfer, approval or sending a message.

## Goal execution evidence

Every inserted prerequisite records:

- Parent source step
- Actual action
- Verified locator and fallbacks
- Page URL/title before and after
- Confidence
- AI or deterministic reason
- Decision source

The walkthrough report includes a dedicated **AI-discovered prerequisite actions** table.

## Playwright generation hand-off

Discovered prerequisites are inserted into the enhanced testcase before the original source step.

```text
Original step 3: Enter password

Enhanced sequence:
3.1 Click Log In to Sandbox
3.2 Enter password
```

Both steps carry verified browser locator evidence. The Playwright generator therefore creates the required page method and call in the correct order.

## Safety and loop prevention

- Maximum inserted actions per source step
- Page-state fingerprints prevent repeated loops
- The same intermediate target is not selected twice
- Only supplied DOM element IDs are accepted from the AI provider
- Destructive intermediate actions are rejected
- Credential values never enter prompts, SQLite, LangSmith inputs, reports or generated source
- MFA, CAPTCHA and insufficient evidence still use supervised human guidance
- Production data-changing actions remain blocked

## GUI configuration

Under **Add New Tests into Existing Framework → Adaptive AI functional walkthrough**:

- Minimum locator confidence
- Human-guidance timeout
- Action timeout
- Maximum AI-inserted prerequisite actions per testcase step
- Headed browser
- Supervised guidance
- QA mutation approval
- Cross-origin navigation approval

## Example result

```text
TC_01 step 3: Enter valid password
AI inserted prerequisite action — Click Log In to Sandbox before continuing with the testcase goal.
Observed page: Password
Verified locator: getByLabel("Password")
Executed original goal: Enter valid password
```

## Scope

The adaptive model is application-independent and is intended for multi-stage login, onboarding wizards, tenant selection, consent dialogs, dynamic SPA transitions, new tabs and open shadow DOM. No browser agent can safely guarantee autonomous completion of every possible application. Unresolvable CAPTCHA, closed shadow DOM, inaccessible cross-origin frames, hardware tokens and unclear business decisions correctly pause for human guidance instead of guessing.
