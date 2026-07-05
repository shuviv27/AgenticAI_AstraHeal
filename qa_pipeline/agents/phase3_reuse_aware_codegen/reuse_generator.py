from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from qa_pipeline.agents.phase3_reuse_aware_codegen.locator_strategy import infer_locator, locator_key, method_name
from qa_pipeline.agents.phase3_reuse_aware_codegen.page_source_analyzer import locator_hint_from_page_source, analyze_page_source
from qa_pipeline.core.io import read_json
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, feature_testcase_path, ensure_dirs
from qa_pipeline.core.text import pascal_case, camel_case, words
from qa_pipeline.rag.framework_inventory import scan_framework, FrameworkInventory


@dataclass
class ReuseDecision:
    kind: str
    page: str
    name: str
    action: str
    file: str


@dataclass
class GenerationResult:
    feature: str
    created: list[ReuseDecision] = field(default_factory=list)
    reused: list[ReuseDecision] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class StepPlan:
    scenario_index: int
    step_index: int
    action: str
    target: str
    value: str
    page: str
    method: str = ""
    locator_key: str = ""


class ReuseAwarePlaywrightGenerator:
    """Guardrail generator that prevents isolated Playwright script creation.

    Python scans the existing TypeScript framework first. Then it reuses pageObjects and
    page methods when possible, creates missing locators/methods only in their correct
    files, and keeps specs locator-free.
    """

    NO_LOCATOR_ACTIONS = {
        "verify_page_loaded",
        "verify_url",
        "verify_responsive",
        "verify_keyboard_accessible",
        "verify_text_or_status",
        "handle_location_permission",
        "handle_browser_permission",
        "handle_geolocation",
        "verify_store_list_populated",
        "verify_nav_menu_or_page_options",
    }
    BASE_PAGE_METHODS = {"verifyPageLoadedSuccessfully", "verifyResponsiveLayoutSmoke", "handleLocationPermissionIfRequested", "verifyStoreListPopulated"}

    def _is_page_level_verification(self, action: str, target: str) -> bool:
        action = (action or "").lower()
        if action not in ["verify", "assert", "expect", "validate", "verify_text_or_status"]:
            return False
        value = " ".join(words(str(target or ""))).lower()
        page_concepts = {"home page", "homepage", "page", "web page", "website", "site", "application", "page loaded successfully"}
        return value in page_concepts or ("home page" in value and any(w in value for w in ["load", "loaded", "loads", "content", "available", "displayed"]))

    def __init__(self) -> None:
        ensure_dirs()

    # ---------------------------------------------------------------------
    # Enterprise Page Object Model resolver
    # ---------------------------------------------------------------------
    # The generator must never create pageObjects.Testcase1.ts or pages.Scrum6Page.ts
    # merely because a testcase/story is named Testcase1 or SCRUM-6.  A testcase is
    # a flow; a Page Object represents an application page/screen.  These helpers
    # map Jira/SRS steps to stable application pages such as HomePage, FindStorePage,
    # ShopOnlinePage, HowItWorksPage, LoginPage, etc.  This keeps duplicate locators
    # and duplicate page methods out of the framework.

    _NON_PAGE_NAMES = {
        "testcase", "test case", "scenario", "story", "scrum", "jira", "issue",
        "acima", "application", "app", "feature", "flow", "generated", "default",
    }

    def _canonical_page_name(self, value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "Home"
        name = pascal_case(raw)
        if name.endswith("Page") and len(name) > 4:
            name = name[:-4]
        # Never use testcase/story ids as page object names.
        lowered = " ".join(words(name)).lower()
        if re.match(r"^(testcase|test case|tc|scenario|story|scrum|jira|issue)\s*\d*$", lowered):
            return "Home"
        if lowered in self._NON_PAGE_NAMES:
            return "Home"
        return name or "Home"

    def _page_from_url(self, url: str | None) -> str | None:
        value = str(url or "").lower()
        if not value:
            return None
        if any(x in value for x in ["/find-a-store", "find-a-store", "nearby-store", "store-locator", "stores", "locations"]):
            return "FindStore"
        if any(x in value for x in ["/shop-online", "shop-online", "online-stores"]):
            return "ShopOnline"
        if any(x in value for x in ["/how-it-works", "how-it-works"]):
            return "HowItWorks"
        if any(x in value for x in ["/mobile-app", "get-the-app", "app-download"]):
            return "MobileApp"
        if any(x in value for x in ["/marketplace", "shop-marketplace"]):
            return "Marketplace"
        if any(x in value for x in ["/login", "signin", "sign-in"]):
            return "Login"
        if value.startswith("http://") or value.startswith("https://") or value in {"/", "/en", "/home"}:
            return "Home"
        return None

    def _page_from_business_context(self, action: str, target: str, value: str = "", current_page: str | None = None) -> str:
        action_l = str(action or "").lower()
        target_l = str(target or "").lower()
        value_l = str(value or "").lower()
        hay = f"{action_l} {target_l} {value_l}"

        # Post-navigation destination pages.
        if action_l == "click_nav_option":
            return current_page or "Home"
        if action_l == "verify_nav_menu_or_page_options":
            target_value = f"{target_l} {value_l}"
            if "shop" in target_value:
                return current_page or "Home"
            if "how it works" in target_value:
                return "HowItWorks"
            if "get the app" in target_value or "mobile" in target_value:
                return "MobileApp"
            return current_page or "Home"
        if any(x in hay for x in ["find-a-store", "store list", "stores", "shop list", "nearby", "partner locations", "location permission", "geolocation", "zip", "postal", "miles", "address", "directions"]):
            # The click action itself belongs to the current/source page; after that the
            # following verification/permission steps belong to FindStore.
            if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
                if "shop in" in target_l or "nearby" in target_l or "store" in target_l:
                    return current_page
            return "FindStore"
        if any(x in hay for x in ["shop-online", "shop online", "online stores"]):
            # Verifying the Home hero button/text "Shop Online" belongs to HomePage.
            # Only post-navigation destination checks belong to ShopOnlinePage.
            if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
                return current_page
            if action_l in {"verify", "assert", "expect", "validate"} and not any(x in value_l for x in ["/shop-online", "shop-online"]):
                return current_page or "Home"
            return "ShopOnline"
        if any(x in hay for x in ["how it works", "how-it-works", "shop now", "within reach"]):
            if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
                return current_page
            return "HowItWorks"
        if any(x in hay for x in ["get the app", "mobile app", "app store", "google play"]):
            if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
                return current_page
            return "MobileApp"
        if any(x in hay for x in ["marketplace", "amazon", "best buy", "walmart"]):
            if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
                return current_page
            return "Marketplace"
        if any(x in hay for x in ["login", "sign in", "username", "password"]):
            return "Login"
        if any(x in hay for x in ["shop with acima leasing", "shop in-store", "shop instore", "shop online", "hero", "home page", "homepage", "navigation bar", "navbar", "footer", "logo", "help", "en"]):
            return current_page or "Home"
        return current_page or "Home"

    def _destination_page_after_step(self, action: str, target: str, value: str = "", current_page: str | None = None) -> str:
        action_l = str(action or "").lower()
        if action_l not in {"click_navigate", "click_external", "navigate", "goto", "launch", "open"}:
            return current_page or "Home"
        return self._page_from_url(value) or self._page_from_business_context("verify", target, value, current_page=current_page) or current_page or "Home"

    def _planned_pages_for_scenario(self, scenario: dict[str, Any], fallback_page: str) -> tuple[list[StepPlan], str]:
        start_url = str(scenario.get("start_url") or "")
        current_page = self._page_from_url(start_url) or self._canonical_page_name(scenario.get("page") or fallback_page)
        if current_page == self._canonical_page_name(fallback_page) and current_page not in {"Home", "Login"}:
            # Story/Testcase names are not application pages.  With a web start URL, start on Home.
            if start_url:
                current_page = "Home"
        plans: list[StepPlan] = []
        primary_page = current_page or "Home"
        for step_index, step in enumerate(scenario.get("steps", [])):
            action = str(step.get("action", "verify")).lower()
            target = str(step.get("target") or "page")
            value = str(step.get("value") or "")
            if action in ["goto", "launch", "open", "navigate"]:
                current_page = self._page_from_url(value) or current_page or "Home"
                primary_page = primary_page or current_page
                continue
            step_page = self._page_from_business_context(action, target, value, current_page=current_page)
            plans.append(StepPlan(-1, step_index, action, target, value, step_page))
            current_page = self._destination_page_after_step(action, target, value, current_page=step_page)
        return plans, primary_page or "Home"

    def _describe_page_plan(self, plans: list[StepPlan]) -> dict[str, list[str]]:
        by_page: dict[str, list[str]] = {}
        for plan in plans:
            by_page.setdefault(plan.page, []).append(f"{plan.action}:{plan.target}")
        return by_page

    def generate(self, feature: str, source_type: str = "jira") -> GenerationResult:
        testcase_path = feature_testcase_path(source_type, feature)
        if not testcase_path.exists():
            raise FileNotFoundError(f"Functional testcase file not found: {testcase_path}")
        testcase_set = read_json(testcase_path)
        result = GenerationResult(feature=feature)
        scenarios = testcase_set.get("scenarios", [])

        raw_fallback_page = testcase_set.get("page") or (scenarios[0].get("page", feature) if scenarios else feature)
        fallback_page = self._canonical_page_name(raw_fallback_page)

        # Static page-source knowledge is optional but highly valuable for modern apps where
        # visible buttons are rendered as links/spans and classes are generated dynamically.
        try:
            analyze_page_source(feature=feature, base_url=str(testcase_set.get('start_url') or ''))
        except Exception:
            pass

        inventory = scan_framework()
        scenario_step_methods: dict[tuple[int, int], tuple[str, str]] = {}
        all_plans: list[StepPlan] = []
        scenario_primary_pages: dict[int, str] = {}

        for scenario_index, scenario in enumerate(scenarios):
            plans, primary_page = self._planned_pages_for_scenario(scenario, fallback_page)
            scenario_primary_pages[scenario_index] = primary_page
            for plan in plans:
                plan.scenario_index = scenario_index
                all_plans.append(plan)

        for plan in all_plans:
            page = self._canonical_page_name(plan.page)
            plan.page = page
            page_name = page
            object_path = GENERATED_PLAYWRIGHT_DIR / "pageObjects" / f"{page_name}Page.objects.ts"
            page_path = GENERATED_PLAYWRIGHT_DIR / "pages" / f"{page_name}Page.ts"
            self._ensure_object_file(object_path, page_name)
            self._ensure_page_file(page_path, page_name)

            action = plan.action
            target = plan.target
            if self._is_page_level_verification(action, str(target)):
                action = "verify_page_loaded"
                target = "page loaded successfully"
                plan.action = action
                plan.target = target
            desired_method = method_name(action, target)
            loc_key = ""

            if action not in self.NO_LOCATOR_ACTIONS:
                loc_key = locator_key(action, target)
                existing_locator = self._find_reusable_locator(inventory, page, loc_key, target, action)
                if existing_locator:
                    loc_key = existing_locator
                    result.reused.append(ReuseDecision("locator", page, loc_key, action, str(object_path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
                else:
                    self._add_locator(object_path, loc_key, self._infer_locator(feature, action, target), target)
                    result.created.append(ReuseDecision("locator", page, loc_key, action, str(object_path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
                    inventory = scan_framework()

            if desired_method in self.BASE_PAGE_METHODS:
                plan.method = desired_method
                plan.locator_key = loc_key
                scenario_step_methods[(plan.scenario_index, plan.step_index)] = (page, desired_method)
                result.reused.append(ReuseDecision("method", page, desired_method, action, "pages/BasePage.ts"))
                continue

            existing_method = self._find_reusable_method(inventory, page, desired_method, action, target)
            if existing_method:
                plan.method = existing_method
                plan.locator_key = loc_key
                scenario_step_methods[(plan.scenario_index, plan.step_index)] = (page, existing_method)
                result.reused.append(ReuseDecision("method", page, existing_method, action, str(page_path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
            else:
                # Pass a copy with the resolved page/action/target so method generation uses
                # the canonical Page Object file, not the testcase/story name.
                step_copy = dict(scenarios[plan.scenario_index].get("steps", [])[plan.step_index])
                step_copy["action"] = action
                step_copy["target"] = target
                step_copy["page"] = page
                self._add_method(page_path, page_name, desired_method, action, loc_key, step_copy)
                plan.method = desired_method
                plan.locator_key = loc_key
                scenario_step_methods[(plan.scenario_index, plan.step_index)] = (page, desired_method)
                result.created.append(ReuseDecision("method", page, desired_method, action, str(page_path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
                inventory = scan_framework()

        # Composite scenario methods are created only when a scenario stays on one page.
        # Multi-page business flows should remain explicit in the spec and call page methods
        # on each relevant Page Object, e.g. HomePage -> FindStorePage.
        for scenario_index, scenario in enumerate(scenarios):
            pages_in_scenario = {p for (si, _), (p, _) in scenario_step_methods.items() if si == scenario_index}
            primary = scenario_primary_pages.get(scenario_index) or fallback_page
            if len(pages_in_scenario) <= 1:
                page_name = next(iter(pages_in_scenario), primary)
                page_path = GENERATED_PLAYWRIGHT_DIR / "pages" / f"{page_name}Page.ts"
                one_scenario_methods = {
                    (0, idx): method for (si, idx), (_page, method) in scenario_step_methods.items() if si == scenario_index
                }
                self._add_composite_methods(page_path, page_name, [scenario], result, one_scenario_methods)

        spec_path = GENERATED_PLAYWRIGHT_DIR / "tests" / "generated" / f"{feature}.spec.ts"
        self._write_spec(spec_path, feature, scenarios, scenario_step_methods, scenario_primary_pages)

        touched_pages = sorted({plan.page for plan in all_plans} | set(scenario_primary_pages.values()))
        for page in touched_pages:
            result.files.extend([
                str((GENERATED_PLAYWRIGHT_DIR / "pageObjects" / f"{page}Page.objects.ts").relative_to(GENERATED_PLAYWRIGHT_DIR)),
                str((GENERATED_PLAYWRIGHT_DIR / "pages" / f"{page}Page.ts").relative_to(GENERATED_PLAYWRIGHT_DIR)),
            ])
        result.files.append(str(spec_path.relative_to(GENERATED_PLAYWRIGHT_DIR)))
        # Deduplicate file list while preserving order.
        result.files = list(dict.fromkeys(result.files))
        self._write_report(result)
        self._write_pom_page_plan_report(feature, all_plans, scenario_primary_pages)
        scan_framework()
        return result

    def _important_words(self, value: str) -> set[str]:
        noise = {
            "the", "a", "an", "and", "or", "to", "of", "on", "in", "is", "are",
            "given", "when", "then", "should", "must", "shall", "user", "page",
            "field", "button", "input", "link", "text", "value", "data", "with", "for",
            "successfully", "displayed", "visible", "opens", "navigates", "section",
        }
        return {w.lower() for w in words(value) if len(w) > 2 and w.lower() not in noise}

    def _action_fits_name(self, action: str, name: str) -> bool:
        action = (action or "").lower()
        n = name.lower()
        fill_terms = ["input", "field", "textbox", "box", "username", "password", "email", "search", "name"]
        click_terms = ["button", "link", "tab", "menu", "submit", "login", "save", "continue", "next", "search", "shop", "download"]
        verify_terms = ["heading", "message", "toast", "banner", "result", "label", "title", "text", "dashboard", "section", "logo", "footer"]
        if action in ["fill", "enter", "type"]:
            return any(t in n for t in fill_terms)
        if action in ["click", "tap", "select", "click_navigate", "click_external"]:
            return any(t in n for t in click_terms)
        if action in ["verify", "assert", "expect", "validate"]:
            return any(t in n for t in verify_terms) or not any(t in n for t in fill_terms + click_terms)
        return True

    def _semantic_match(self, target_words: set[str], candidate_words: set[str]) -> bool:
        if not target_words or not candidate_words:
            return False
        if target_words.issubset(candidate_words):
            # Do not reuse a huge or combined method/locator for a short specific target.
            # Example: "Shop In-store" must not reuse "Shop In-store and Shop Online buttons".
            if len(target_words) <= 2 and len(candidate_words) > len(target_words) + 1:
                return False
            if len(candidate_words) > max(len(target_words) * 3, 6):
                return False
            sibling_conflicts = [
                ({"store"}, {"online"}),
                ({"online"}, {"store"}),
                ({"app", "store"}, {"google", "play"}),
                ({"google", "play"}, {"app", "store"}),
            ]
            for target_side, conflict_side in sibling_conflicts:
                if target_words & target_side and candidate_words & conflict_side and not (target_words & conflict_side):
                    return False
            return True
        overlap = target_words & candidate_words
        if len(target_words) == 1 and overlap:
            return True
        if len(overlap) < 2:
            return False
        return len(overlap) / max(len(target_words), 1) >= 0.6

    def _find_reusable_locator(self, inventory: FrameworkInventory, page: str, desired_key: str, target: str, action: str = "verify") -> str | None:
        if inventory.has_locator(page, desired_key):
            return desired_key
        target_words = self._important_words(target)
        for locator in inventory.locators:
            if locator.page != page:
                continue
            candidate = locator.key + " " + locator.value
            if not self._action_fits_name(action, candidate):
                continue
            if self._semantic_match(target_words, self._important_words(candidate)):
                return locator.key
        return None

    def _find_reusable_method(self, inventory: FrameworkInventory, page: str, desired_name: str, action: str, target: str) -> str | None:
        if inventory.has_method(page, desired_name):
            return desired_name
        action = (action or "").lower()
        target_words = self._important_words(target)
        action_prefixes = {
            "fill": ["fill", "enter", "type"],
            "enter": ["fill", "enter", "type"],
            "type": ["fill", "enter", "type"],
            "click": ["click", "tap", "select"],
            "click_navigate": ["click"],
            "click_external": ["click"],
            "tap": ["click", "tap", "select"],
            "verify": ["verify", "assert", "expect", "validate"],
            "verify_page_loaded": ["verifyPageLoaded"],
            "verify_responsive": ["verifyResponsive"],
            "verify_keyboard_accessible": ["verifyKeyboardAccessible"],
            "verify_text_or_status": ["verify"],
            "handle_location_permission": ["handleLocationPermission"],
            "handle_browser_permission": ["handleLocationPermission"],
            "handle_geolocation": ["handleLocationPermission"],
            "verify_store_list_populated": ["verifyStoreList"],
        }.get(action, [action])
        for method in inventory.methods:
            if method.page != page:
                continue
            name_lower = method.name.lower()
            if not any(name_lower.startswith(prefix.lower()) for prefix in action_prefixes):
                continue
            if not self._action_fits_name(action, method.name):
                continue
            if self._semantic_match(target_words, self._important_words(method.name)):
                return method.name
        return None

    def _ensure_object_file(self, path: Path, page_name: str) -> None:
        if path.exists():
            return
        path.write_text(f'''import type {{ LocatorDefinition }} from '../utils/locatorFactory';

export const {page_name}PageObjects = {{
}} satisfies Record<string, LocatorDefinition>;
''', encoding='utf-8')

    def _ensure_page_file(self, path: Path, page_name: str) -> None:
        if path.exists():
            return
        path.write_text(f'''import type {{ Page }} from '@playwright/test';
import {{ expect }} from '@playwright/test';
import {{ BasePage }} from './BasePage';
import {{ {page_name}PageObjects }} from '../pageObjects/{page_name}Page.objects';

export class {page_name}Page extends BasePage {{
  constructor(page: Page) {{
    super(page);
  }}
}}
''', encoding='utf-8')

    def _infer_locator(self, feature: str, action: str, target: str) -> dict:
        # Header/navigation actions must stay scoped to nav/header.  Do not let
        # page-source keyword hints replace the exact nav "Shop" link with a
        # body/hero "Shop In-store" CTA.
        if str(action or '').lower() == "click_nav_option":
            return infer_locator(action, target)
        hint = locator_hint_from_page_source(feature, str(target or ''), str(action or 'verify'))
        if hint:
            return hint
        return infer_locator(action, target)

    def _locator_literal(self, locator: dict, description: str | None = None) -> str:
        strategy = locator.get("strategy", "testId")
        parts: list[str] = [f"strategy: '{self._esc(strategy)}'"]
        if strategy == "role":
            parts.append(f"role: '{self._esc(locator.get('role', 'button'))}'")
        parts.append(f"value: '{self._esc(locator.get('value', ''))}'")
        desc = locator.get("description") or description
        if desc:
            parts.append(f"description: '{self._esc(str(desc))}'")
        fallbacks = locator.get("fallbacks") or []
        if isinstance(fallbacks, list) and fallbacks:
            fb = ", ".join(self._locator_literal(f, None) for f in fallbacks if isinstance(f, dict))
            if fb:
                parts.append(f"fallbacks: [{fb}]")
        return "{ " + ", ".join(parts) + " }"

    def _add_locator(self, path: Path, key: str, locator: dict, description: str) -> None:
        text = path.read_text(encoding='utf-8')
        if f"{key}:" in text:
            return
        entry = f"  {key}: {self._locator_literal(locator, description)},\n"
        text = text.replace("} satisfies Record<string, LocatorDefinition>;", entry + "} satisfies Record<string, LocatorDefinition>;")
        path.write_text(text, encoding='utf-8')

    def _add_method(self, path: Path, page_name: str, name: str, action: str, loc_key: str, step: dict[str, Any]) -> None:
        text = path.read_text(encoding='utf-8')
        if f"async {name}(" in text:
            return
        action_lower = action.lower()
        target_for_guard = str(step.get("target") or step.get("expected") or name)
        if self._is_page_level_verification(action_lower, target_for_guard):
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyPageLoadedSuccessfully();
  }}
'''
        elif action_lower in ["fill", "enter", "type"]:
            body = f'''
  async {name}(value: string): Promise<void> {{
    await this.getLocator({page_name}PageObjects.{loc_key}).fill(value);
  }}
'''
        elif action_lower in ["click", "tap", "select"]:
            target = self._esc(step.get("target") or name)
            body = f'''
  async {name}(): Promise<void> {{
    await this.healAwareClick(this.getLocator({page_name}PageObjects.{loc_key}), '{target}').catch(async () => {{
      await this.smartClickByTextOrHref('{target}');
    }});
  }}
'''
        elif action_lower == "click_nav_option":
            expected = self._esc(step.get("value") or "")
            target = self._esc(step.get("target") or name)
            body = f'''
  async {name}(): Promise<void> {{
    await this.clickHeaderNavigationOption(this.getLocator({page_name}PageObjects.{loc_key}), '{target}', '{expected}');
  }}
'''
        elif action_lower == "click_navigate":
            expected = self._esc(step.get("value") or "")
            target = self._esc(step.get("target") or name)
            body = f'''
  async {name}(): Promise<void> {{
    await this.clickAndVerifyNavigation(this.getLocator({page_name}PageObjects.{loc_key}), '{expected}').catch(async () => {{
      await this.smartClickByTextOrHref('{target}', '{expected}');
    }});
  }}
'''
        elif action_lower == "click_external":
            expected = self._esc(step.get("value") or "")
            target = self._esc(step.get("target") or name)
            body = f'''
  async {name}(): Promise<void> {{
    await this.clickAndVerifyMaybeNewTab(this.getLocator({page_name}PageObjects.{loc_key}), '{expected}').catch(async () => {{
      await this.smartClickByTextOrHref('{target}', '{expected}');
    }});
  }}
'''
        elif action_lower in ["handle_location_permission", "handle_browser_permission", "handle_geolocation"]:
            body = f'''
  async {name}(): Promise<void> {{
    await this.handleLocationPermissionIfRequested();
  }}
'''
        elif action_lower == "verify_store_list_populated":
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyStoreListPopulated();
  }}
'''
        elif action_lower == "verify_nav_menu_or_page_options":
            expected = self._esc(step.get("expected") or "")
            target = self._esc(step.get("value") or step.get("target") or "Shop")
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyHeaderNavigationMenuOrPageOptions('{target}', `{expected}`);
  }}
'''
        elif action_lower == "verify_page_loaded":
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyPageLoadedSuccessfully();
  }}
'''
        elif action_lower == "verify_url":
            expected = self._esc(step.get("value") or step.get("expected") or "")
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyUrlContains('{expected}');
  }}
'''
        elif action_lower == "verify_responsive":
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyResponsiveLayoutSmoke();
  }}
'''
        elif action_lower == "verify_keyboard_accessible":
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyPageLoadedSuccessfully();
    // Extend with app-specific tab order assertions after Playwright-MCP exploration.
  }}
'''
        elif action_lower == "verify_text_or_status":
            expected = self._esc(step.get("expected") or step.get("target") or "")
            body = f'''
  async {name}(): Promise<void> {{
    await this.verifyTextVisible('{expected}');
  }}
'''
        else:
            target = self._esc(step.get("target") or step.get("expected") or name)
            body = f'''
  async {name}(): Promise<void> {{
    await this.healAwareVerifyVisible(this.getLocator({page_name}PageObjects.{loc_key}), '{target}').catch(async () => {{
      await this.smartVerifyTextOrAction('{target}');
    }});
  }}
'''
        text = self._insert_before_final_class_brace(text, body)
        path.write_text(text, encoding='utf-8')

    def _add_composite_methods(self, path: Path, page_name: str, scenarios: list[dict[str, Any]], result: GenerationResult, step_methods: dict[tuple[int, int], str]) -> None:
        text = path.read_text(encoding='utf-8')
        for scenario_index, scenario in enumerate(scenarios):
            scenario_method = camel_case(scenario.get("title", "scenario"))
            if f"async {scenario_method}(" in text:
                result.reused.append(ReuseDecision("method", page_name, scenario_method, "scenario", str(path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
                continue
            lines = []
            start_url = scenario.get("start_url")
            if not start_url:
                for step in scenario.get("steps", []):
                    if str(step.get("action", "")).lower() in ["goto", "launch", "open", "navigate"] and step.get("value"):
                        start_url = step.get("value")
                        break
            lines.append(f"    await this.goto({self._value_expr(str(start_url))});" if start_url else "    await this.goto();")
            for step_index, step in enumerate(scenario.get("steps", [])):
                action = str(step.get("action", "")).lower()
                if action in ["goto", "launch", "open", "navigate"]:
                    continue
                name = step_methods.get((scenario_index, step_index))
                if not name:
                    continue
                if action in ["fill", "enter", "type"]:
                    lines.append(f"    await this.{name}({self._value_expr(step.get('value'))});")
                else:
                    lines.append(f"    await this.{name}();")
            body = f'''
  async {scenario_method}(): Promise<void> {{
{chr(10).join(lines)}
  }}
'''
            text = self._insert_before_final_class_brace(text, body)
            result.created.append(ReuseDecision("method", page_name, scenario_method, "scenario", str(path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
        path.write_text(text, encoding='utf-8')

    def _write_spec(self, path: Path, feature: str, scenarios: list[dict[str, Any]], step_methods: dict[tuple[int, int], tuple[str, str]], scenario_primary_pages: dict[int, str]) -> None:
        pages_used = sorted({page for page, _method in step_methods.values()} | set(scenario_primary_pages.values()))
        if not pages_used:
            pages_used = ["Home"]
        lines = ["import { test } from '@playwright/test';"]
        for page_name in pages_used:
            lines.append(f"import {{ {page_name}Page }} from '../../pages/{page_name}Page';")
        lines.extend(["", f"test.describe('{feature} generated scenarios', () => {{"])
        for scenario_index, scenario in enumerate(scenarios):
            title = scenario.get("title", "generated scenario")
            scenario_id = scenario.get("id", "SCENARIO")
            lines.extend([
                f"  test('{scenario_id} - {self._esc(title)}', async ({{ page }}) => {{",
                f"    // Source traceability: {scenario.get('source_ref', scenario_id)}",
            ])
            page_vars: dict[str, str] = {}
            for page_name in pages_used:
                var = f"{camel_case(page_name)}Page"
                page_vars[page_name] = var
                lines.append(f"    const {var} = new {page_name}Page(page);")
            start_url = scenario.get("start_url")
            if not start_url:
                for step in scenario.get("steps", []):
                    if str(step.get("action", "")).lower() in ["goto", "launch", "open", "navigate"] and step.get("value"):
                        start_url = step.get("value")
                        break
            primary_page = scenario_primary_pages.get(scenario_index) or pages_used[0]
            primary_var = page_vars.get(primary_page) or next(iter(page_vars.values()))
            lines.append(f"    await {primary_var}.goto({self._value_expr(str(start_url))});" if start_url else f"    await {primary_var}.goto();")
            current_page = primary_page
            for step_index, step in enumerate(scenario.get("steps", [])):
                action = str(step.get("action", "")).lower()
                if action in ["goto", "launch", "open", "navigate"]:
                    continue
                resolved = step_methods.get((scenario_index, step_index))
                if not resolved:
                    continue
                page_name, method = resolved
                page_var = page_vars.get(page_name, primary_var)
                if page_name != current_page:
                    lines.append(f"    // Page context switched to {page_name}Page after navigation/action.")
                    current_page = page_name
                if action in ["fill", "enter", "type"]:
                    lines.append(f"    await {page_var}.{method}({self._value_expr(step.get('value'))});")
                else:
                    lines.append(f"    await {page_var}.{method}();")
            lines.extend(["  });", ""])
        lines.append("});")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding='utf-8')

    def _write_pom_page_plan_report(self, feature: str, plans: list[StepPlan], primary_pages: dict[int, str]) -> None:
        lines = [
            f"# Page Object Model page plan — {feature}",
            "",
            "This report explains how the generator mapped testcase/story steps to real application Page Objects.",
            "Testcase/story names are never used as Page Object names. Reusable locators and methods are stored by application page.",
            "",
            "## Scenario primary pages",
            "",
        ]
        if not primary_pages:
            lines.append("No scenarios were planned.")
        for idx, page in sorted(primary_pages.items()):
            lines.append(f"- Scenario {idx + 1}: `{page}Page`")
        lines.extend(["", "## Step ownership", ""])
        if not plans:
            lines.append("No step-level page ownership was required.")
        for plan in plans:
            method = plan.method or "<pending>"
            lines.append(f"- Scenario {plan.scenario_index + 1}, step {plan.step_index + 1}: `{plan.action}` `{plan.target}` -> `{plan.page}Page.{method}()`")
        lines.extend([
            "",
            "## Guardrails",
            "",
            "- Specs call page methods only; no raw locators in spec files.",
            "- Page methods call locators from matching pageObjects files.",
            "- Existing page locators/methods are reused before creating new ones.",
            "- Cross-page flows are modeled as multiple Page Objects in one spec, for example `HomePage` then `FindStorePage`.",
        ])
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "pom-page-plan-report.md").write_text("\n".join(lines) + "\n", encoding='utf-8')

    def _write_report(self, result: GenerationResult) -> None:
        lines = [
            f"# Reuse decision report — {result.feature}",
            "",
            "This report proves that generation was not isolated. The generator scanned the existing framework and static/live page-source evidence first, then reused or created items only when required.",
            "",
            "## Reused items",
            "",
        ]
        if not result.reused:
            lines.append("No reusable items were found during this run.")
        for d in result.reused:
            lines.append(f"- {d.kind}: `{d.page}.{d.name}` from `{d.file}`")
        lines.extend(["", "## Created items", ""])
        if not result.created:
            lines.append("No new items were required during this run.")
        for d in result.created:
            lines.append(f"- {d.kind}: `{d.page}.{d.name}` in `{d.file}`")
        lines.extend(["", "## Generated/updated files", ""])
        for f in result.files:
            lines.append(f"- `{f}`")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "reuse-decision-report.md").write_text("\n".join(lines) + "\n", encoding='utf-8')

    def _insert_before_final_class_brace(self, text: str, body: str) -> str:
        idx = text.rfind("}")
        if idx == -1:
            return text + body
        return text[:idx].rstrip() + "\n" + body + "\n" + text[idx:]

    def _value_expr(self, value: str | None) -> str:
        if not value:
            return "''"
        if str(value).startswith("env:"):
            env_key = str(value).split(":", 1)[1]
            return f"process.env.{env_key} ?? ''"
        return f"'{self._esc(value)}'"

    def _esc(self, value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("'", "\\'")
