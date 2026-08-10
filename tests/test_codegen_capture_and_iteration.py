from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from qa_pipeline.agents.existing_framework_control.controller import ensure_plain_english_rca_report
from qa_pipeline.core.io import write_json
from qa_pipeline.core.paths import feature_testcase_path
from qa_pipeline.gui.app import app
from qa_pipeline.modules.playwright_ts_generator.codegen_capture import (
    _build_enhanced_payload,
    _mask_source,
    align_actions_to_scenario,
    parse_codegen_source,
)
from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import generate_existing_framework_tests
from qa_pipeline.modules.playwright_ts_generator.controller import generate_existing_framework_extension_enterprise


class CodegenCaptureAndIterationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.feature = f"codegen_{uuid.uuid4().hex[:8]}"
        (self.root / "package.json").write_text(json.dumps({"name": "fixture", "scripts": {"test": "playwright test"}, "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (self.root / "playwright.config.ts").write_text("export default { testDir: './tests' };\n", encoding="utf-8")
        self.write("tests/existing.spec.ts", "import { test } from '@playwright/test'; test('existing', async () => {});\n")
        self.write("pages/BasePage.ts", "import type { Page } from '@playwright/test';\nimport { resolveSmartLocator, type LocatorDefinition } from '../utils/locatorFactory';\nexport class BasePage { constructor(protected readonly page: Page) {} protected getSmartLocator(d: LocatorDefinition){ return resolveSmartLocator(this.page,d); } async goto(url:string){await this.page.goto(url)} async verifyPageLoadedSuccessfully(){} }\n")
        self.write("utils/locatorFactory.ts", "export type LocatorDefinition = { strategy: string; value: string; role?: string; description?: string; fallbacks?: LocatorDefinition[] }; export function resolveSmartLocator(page:any,d:any){return {fill:async()=>{},click:async()=>{},firstReachable:async()=>page.locator('body'),expectVisible:async()=>page.locator('body')}}\n")
        (self.root / "pageObjects").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(feature_testcase_path("module2_uploaded", self.feature).parent, ignore_errors=True)
        self.temp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save(self, scenarios: list[dict]) -> None:
        path = feature_testcase_path("module2_uploaded", self.feature)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"feature": self.feature, "scenarios": scenarios, "scenario_count": len(scenarios)})

    def scenario(self, sid: str, target: str = "Click Submit button") -> dict:
        return {
            "id": sid,
            "title": f"Scenario {sid}",
            "page": "Salesforce",
            "steps": [
                {"step_number": "1", "action": "goto", "target": "Open application", "value": "https://example.test"},
                {"step_number": "2", "action": "click", "target": target},
            ],
        }

    def test_codegen_parser_keeps_real_playwright_locators_and_masks_credentials(self) -> None:
        source = """
        await page.getByRole('textbox', { name: 'Username' }).fill('person@example.test');
        await page.getByRole('button', { name: 'Log In to Sandbox' }).click();
        await page.getByLabel('Password').fill('Secret-123!');
        await page.locator('#Login').click();
        await expect(page.getByText('Home')).toBeVisible();
        """
        masked = _mask_source(source)
        self.assertNotIn("person@example.test", masked)
        self.assertNotIn("Secret-123!", masked)
        actions = parse_codegen_source(masked)
        self.assertEqual([x["action"] for x in actions], ["fill", "click", "fill", "click", "verify"])
        self.assertEqual(actions[1]["locator"]["role"], "button")
        self.assertEqual(actions[1]["locator"]["value"], "Log In to Sandbox")
        self.assertEqual(actions[3]["locator"], {"playwright_expression": "page.locator('#Login')", "verified_by": "playwright_codegen", "confidence": 0.99, "strategy": "css", "value": "#Login"})

    def test_codegen_alignment_inserts_real_intermediate_login_transition(self) -> None:
        scenario = {
            "id": "TC_01",
            "steps": [
                {"action": "fill", "target": "Enter username"},
                {"action": "fill", "target": "Enter password"},
                {"action": "click", "target": "Click Login button"},
            ],
        }
        actions = parse_codegen_source("""
        await page.getByRole('textbox', { name: 'Username' }).fill('');
        await page.getByRole('button', { name: 'Log In to Sandbox' }).click();
        await page.getByLabel('Password').fill('');
        await page.locator('#Login').click();
        """)
        enhanced = align_actions_to_scenario(scenario, actions)
        targets = [step["target"] for step in enhanced["steps"]]
        self.assertEqual(targets, ["Enter username", "Log In to Sandbox", "Enter password", "Click Login button"])
        inserted = enhanced["steps"][1]
        self.assertTrue(inserted["generated_by_codegen"])
        self.assertEqual(inserted["walkthrough"]["status"], "codegen_verified")

    def test_multiple_codegen_captures_preserve_evidence_for_earlier_scenarios(self) -> None:
        scenarios = [self.scenario("TC_01", "Click Login button"), self.scenario("TC_02", "Click Continue button")]
        self.save(scenarios)
        capture_root = self.root / ".aiqa-history" / "codegen-captures" / self.feature
        capture_root.mkdir(parents=True, exist_ok=True)
        first_actions = parse_codegen_source("await page.getByRole('button', { name: 'Login' }).click();")
        first = _build_enhanced_payload(str(self.root), self.feature, "TC_01", first_actions)
        write_json(capture_root / "latest-enhanced.scenarios.json", first)
        second_actions = parse_codegen_source("await page.getByRole('button', { name: 'Continue' }).click();")
        second = _build_enhanced_payload(str(self.root), self.feature, "TC_02", second_actions)
        by_id = {item["id"]: item for item in second["scenarios"]}
        self.assertEqual(by_id["TC_01"]["codegen_capture"]["captured_action_count"], 1)
        self.assertEqual(by_id["TC_02"]["codegen_capture"]["captured_action_count"], 1)
        self.assertEqual(second["codegen_capture"]["captured_scenario_count"], 2)

    def test_iterative_generation_preserves_earlier_scenarios_and_updates_in_place(self) -> None:
        self.save([self.scenario("TC_01")])
        first = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=False, placement_mode="auto_reuse", use_codegen_capture=False)
        self.assertTrue(first["ok"], first)
        first_spec = self.root / first["generated_specs"][0]
        self.assertTrue(first_spec.exists())

        self.save([self.scenario("TC_02", "Click Continue button")])
        second = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=False, placement_mode="auto_reuse", use_codegen_capture=False)
        self.assertTrue(second["ok"], second)
        data_text = (self.root / second["test_data_file"]).read_text(encoding="utf-8")
        self.assertIn('"TC_01"', data_text)
        self.assertIn('"TC_02"', data_text)
        self.assertTrue(first_spec.exists())
        self.assertTrue((self.root / second["generated_specs"][0]).exists())

        third = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=False, placement_mode="auto_reuse", use_codegen_capture=False)
        self.assertTrue(third["ok"], third)
        self.assertFalse(any("-2.spec.ts" in str(path) for path in self.root.rglob("*.spec.ts")))
        self.assertEqual(third["scenario_outputs"][0]["spec_update_mode"], "updated_existing")

    def test_authoritative_codegen_capture_skips_duplicate_live_grounding(self) -> None:
        self.save([self.scenario("TC_01")])
        capture = {"ok": True, "recorded_action_count": 2, "scenario_id": "TC_01"}
        generated = {"ok": True, "message": "generated"}
        with patch("qa_pipeline.modules.playwright_ts_generator.codegen_capture.latest_codegen_capture", return_value=capture), \
             patch("qa_pipeline.agentic.browser_grounded_generation.ground_testcases_for_generation") as grounding, \
             patch("qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests.generate_existing_framework_tests", return_value=generated) as generator:
            result = generate_existing_framework_extension_enterprise(
                str(self.root), self.feature, placement_mode="auto_reuse", browser_grounded_generation=True, use_codegen_capture=True
            )
        grounding.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["browser_grounding"]["reason"], "authoritative_codegen_capture_available")
        self.assertTrue(generator.call_args.kwargs["use_codegen_capture"])

    def test_plain_english_rca_report_endpoint_and_fallback_are_stable(self) -> None:
        reports = self.root / "reports"
        html_path = reports / "plain-english-failure-report.html"
        json_path = reports / "plain-english-failure-report.json"
        inventory = reports / "failed-test-inventory.json"
        rca_json = reports / "root-cause-report.json"
        html_dir = reports / "html"
        with patch.multiple(
            "qa_pipeline.agents.existing_framework_control.controller",
            EXISTING_REPORTS_DIR=reports,
            EXISTING_PLAIN_FAILURE_HTML=html_path,
            EXISTING_PLAIN_FAILURE_JSON=json_path,
            EXISTING_INVENTORY_JSON=inventory,
            EXISTING_RCA_JSON=rca_json,
            EXISTING_HTML_DIR=html_dir,
        ):
            result = ensure_plain_english_rca_report(str(self.root))
        self.assertTrue(result["ok"])
        self.assertTrue(html_path.exists())
        self.assertIn("No Playwright execution evidence", html_path.read_text(encoding="utf-8"))
        routes = {route.path for route in app.routes}
        self.assertIn("/api/existing-framework/rca/plain-english/report", routes)
        self.assertIn("/api/module2/playwright/codegen/start", routes)
        self.assertIn("/api/module2/playwright/codegen/stop", routes)


if __name__ == "__main__":
    unittest.main()
