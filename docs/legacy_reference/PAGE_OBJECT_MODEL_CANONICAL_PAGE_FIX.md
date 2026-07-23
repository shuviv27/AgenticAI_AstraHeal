# Page Object Model canonical page fix

## Problem fixed

The generator previously used the testcase/story feature name as the Page Object name. For example, `testcase1` created `Testcase1Page` and `testcase2` created `Testcase2Page`, even when both touched the same Home page. This duplicated locators and methods and weakened the Page Object Model.

## New rule

A testcase is a business flow. A Page Object is an application page/screen.

The generator now resolves each step to a canonical application page before creating locators or methods:

- Home-page hero and navigation checks -> `HomePage` / `HomePage.objects`
- Shop In-store click from the hero -> `HomePage.clickShopInStoreAndVerifyNavigation()`
- Store list, location permission, nearby partner locations -> `FindStorePage`
- Shop Online destination checks -> `ShopOnlinePage`
- How It Works destination checks -> `HowItWorksPage`
- Login fields/actions -> `LoginPage`

## Example

Testcase 1 checks the Acima home hero:

```text
Shop with Acima Leasing
Shop In-store
Shop Online
```

The generator creates/reuses:

```text
generated-playwright/pageObjects/HomePage.objects.ts
generated-playwright/pages/HomePage.ts
generated-playwright/tests/generated/testcase1.spec.ts
```

Testcase 2 also checks the same Home hero and then clicks Shop In-store:

```text
Shop with Acima Leasing
Shop In-store
click Shop In-store
verify store list
```

The generator reuses the existing Home page artifacts and only adds the new destination page:

```text
generated-playwright/pageObjects/HomePage.objects.ts   reused/updated
generated-playwright/pages/HomePage.ts                 reused/updated
generated-playwright/pageObjects/FindStorePage.objects.ts
generated-playwright/pages/FindStorePage.ts
generated-playwright/tests/generated/testcase2.spec.ts
```

## Guardrails

- Specs call page methods only.
- Page methods call locators from matching pageObjects files.
- Locator reuse is attempted before new locator creation.
- Method reuse is attempted before new method creation.
- Testcase/story identifiers such as `Testcase1`, `SCRUM-6`, `Story1`, or `jira_epic_child` are not used as Page Object names.
- Cross-page flows instantiate multiple Page Objects in the same spec, for example `HomePage` then `FindStorePage`.

## Report

Every generation writes a Page Object ownership report:

```text
generated-playwright/reports/pom-page-plan-report.md
```

This explains which step was assigned to which Page Object and which method was reused/created.

## Additional self-learning rule: header navigation disambiguation
- If a requirement says "available on navigation bar", "navbar", "header", or "top menu", scope the click to `nav`, `header`, or `[role="navigation"]` and use an exact accessible name. Do not use generic body text clicks.
- Do not assert dropdown/menu labels as plain page text after a nav click. Use a scoped menu/page business verification with synonym mapping.

