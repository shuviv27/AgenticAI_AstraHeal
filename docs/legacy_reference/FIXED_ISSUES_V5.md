# Fixed Issues in v5

## Issue 1: pasted steps generated incomplete login spec

Earlier output only called:

```ts
await loginPage.goto();
await loginPage.validateLoginBusinessFlow();
```

This looked incomplete for demos and did not show the URL/username/password supplied by the user.

### Fix

The parser now extracts:

- application URL;
- username value;
- password value;
- button text;
- source traceability.

The generated spec now shows readable business actions while still using the page-object pattern.

## Issue 2: your application locators

your application uses `data-test` attributes. The base framework now maps Playwright test IDs to `data-test` through `playwright.config.ts`:

```ts
testIdAttribute: process.env.PLAYWRIGHT_TEST_ID_ATTRIBUTE ?? 'data-test'
```

The default `LoginPage.objects.ts` uses:

```ts
usernameInput -> data-test=username
passwordInput -> data-test=password
loginButton -> data-test=login-button
```

## Issue 3: Codex connection unclear

The GUI now has **Check Codex/Ollama**. It reports:

- Codex CLI availability;
- Codex login-status result;
- Ollama host/model status;
- exact setup commands.

## Issue 4: GUI demo readability

The GUI now includes:

- your application sample button;
- generated spec preview tab;
- generated page class preview tab;
- AI status/message tab;
- clearer provider choices;
- clearer output locations.
