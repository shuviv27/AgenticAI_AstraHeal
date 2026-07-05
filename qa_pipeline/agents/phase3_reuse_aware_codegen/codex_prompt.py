from __future__ import annotations

import json
from qa_pipeline.rag.framework_inventory import FrameworkInventory
from qa_pipeline.agents.phase3_reuse_aware_codegen.page_source_analyzer import load_page_source_map


def build_codex_prompt(feature: str, testcase_set: dict, inventory: FrameworkInventory) -> str:
    page_source_map = load_page_source_map(feature)
    return f"""
You are working inside an enterprise Playwright TypeScript repository.

STRICT RULES:
1. All Playwright framework files must stay inside generated-playwright/.
2. Specs must call page methods only.
3. Page methods must call locators from pageObjects only.
4. Never inline selectors in spec files.
5. Before adding any locator, check generated-playwright/pageObjects/<PageName>Page.objects.ts.
6. Before adding any method, check generated-playwright/pages/<PageName>Page.ts.
7. Reuse existing locators and functions wherever available.
8. If a locator is missing, add it to the matching pageObjects file.
9. If a method is missing, add it to the matching pages file.
10. Run npm --prefix generated-playwright run build and fix TypeScript issues.
11. Never use http://127.0.0.1, localhost, or the GUI URL as application URL. Use each scenario start_url or BASE_URL.
12. For dynamic web pages, prefer user-facing locators: getByRole, getByText, getByLabel, href-based CSS only as fallback.
13. Handle location/notification permissions through Playwright context/config, not manual user interaction. Never generate a visible-text assertion for phrases like "location permission handled", "browser permission handled", or "permission popup handled"; these are instructions, not UI text.
14. For store-finder/location flows, grant geolocation and, if the site still asks for location/ZIP, use a configurable zip code (TEST_ZIP_CODE, default 84101) and verify the store/list/results container, not the literal permission instruction.
15. Scroll elements into view before clicking or asserting when needed.
15. When page-source evidence is available, prefer its aria-label/href/heading/text hints over guessed selectors.
16. For Chakra/React marketing buttons implemented as <a class="chakra-button">, generate link/aria/href based locators rather than button-only locators.
17. Do not create generic targets like "Shop In-store and Shop Online buttons" as one locator; split into individual visible elements.

Feature: {feature}

Functional testcases:
{json.dumps(testcase_set, indent=2)}

Existing framework inventory:
{json.dumps(inventory.to_dict(), indent=2)}

Static page-source locator evidence, when uploaded/provided:
{json.dumps(page_source_map, indent=2)[:12000]}

Expected flow:
Spec -> Page class -> PageObjects locator file.
"""
