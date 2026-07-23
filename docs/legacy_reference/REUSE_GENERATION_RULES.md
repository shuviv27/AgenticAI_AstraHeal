# Reuse-Aware Generation Rules

## Mandatory generation flow

```text
Spec file -> Page class -> PageObjects locator file
```

## Spec file rules

Generated specs must:

- import page classes from `generated-playwright/pages`
- call reusable methods only
- avoid `page.locator`, `page.getByRole`, `page.getByTestId`, `page.getByText`, and XPath directly
- include source traceability comments

## Page class rules

Page classes must:

- extend `BasePage`
- expose reusable business methods
- use `this.getLocator(PageObjects.locatorKey)`
- avoid direct selectors where possible

## PageObjects rules

PageObjects files must:

- contain locator definitions only
- prefer strategies in this order:
  1. `testId`
  2. `role`
  3. `label`
  4. `text`
  5. `css`
  6. `xpath` only with justification

## RAG/inventory rule

Before generating code, the Python agent must run inventory over:

```text
generated-playwright/pageObjects/
generated-playwright/pages/
generated-playwright/tests/
generated-playwright/testData/
```

The inventory is written to:

```text
.qa-cache/framework-inventory.json
generated-playwright/reports/framework-inventory.json
```
