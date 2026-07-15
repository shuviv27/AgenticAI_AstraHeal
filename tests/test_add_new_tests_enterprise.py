from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import openpyxl

from qa_pipeline.core.io import write_json
from qa_pipeline.core.paths import REPO_ROOT, feature_testcase_path
from qa_pipeline.gui.app import app
from qa_pipeline.integrations.atlassian_mcp import AtlassianCredentials, fetch_atlassian_source, prepare_atlassian_mcp_config
from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import (
    extract_and_normalize_source,
    generate_existing_framework_tests,
    parse_gherkin,
    preview_generation_placement,
)


class AddNewTestsEnterpriseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mcp_env = patch.dict(os.environ, {"ASTRAHEAL_PREFER_ATLASSIAN_MCP": "false"})
        self.mcp_env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.feature = f"addnew_{uuid.uuid4().hex[:10]}"
        (self.root / "package.json").write_text(
            json.dumps({"name": "fixture", "scripts": {"test": "playwright test"}, "devDependencies": {"@playwright/test": "1.50.0"}}),
            encoding="utf-8",
        )
        (self.root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };\n", encoding="utf-8")
        self.write("src/test/specs/existing.spec.ts", "import { test } from '@playwright/test'; test('existing', async () => {});\n")

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.mcp_env.stop()
        testcase = feature_testcase_path("module2_uploaded", self.feature)
        shutil.rmtree(testcase.parent, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save_payload(self, payload: dict) -> Path:
        path = feature_testcase_path("module2_uploaded", self.feature)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload)
        return path

    def test_plain_document_splits_multiple_testcases(self) -> None:
        raw = """Test Case ID: TC-1
Title: Valid login
Page: Login
Steps:
1. Open application
2. Enter username
3. Click Login button
Expected Result: Dashboard is displayed
---
Test Case ID: TC-2
Title: Invalid login
Page: Login
Steps:
1. Open application
2. Enter invalid username
3. Click Login button
Expected Result: Error message is displayed
"""
        payload = extract_and_normalize_source(self.feature, pasted_json_or_steps=raw)
        self.assertEqual(payload["scenario_count"], 2)
        self.assertEqual([x["id"] for x in payload["scenarios"]], ["TC-1", "TC-2"])
        self.assertTrue(all(any(step["action"] == "verify" for step in x["steps"]) for x in payload["scenarios"]))

    def test_gherkin_scenarios_and_outline_examples_expand(self) -> None:
        raw = """Feature: Checkout
Background:
  Given the user is logged in
Scenario: Pay by card
  When the user clicks Pay
  And confirms the order
  Then a success message is displayed
Scenario Outline: Invalid card
  When the user enters <card>
  Then <message> is displayed
Examples:
  | card | message |
  | 1111 | Declined |
  | 2222 | Invalid |
"""
        payload = parse_gherkin(raw, self.feature)
        self.assertEqual(payload["scenario_count"], 3)
        first = payload["scenarios"][0]
        self.assertEqual(first["steps"][2]["gherkin_keyword"], "And")
        self.assertEqual(first["steps"][2]["action"], "click")
        self.assertIn("1111", json.dumps(payload["scenarios"][1]))
        self.assertIn("2222", json.dumps(payload["scenarios"][2]))

    def test_excel_rows_group_into_multiple_testcases(self) -> None:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Test Case ID", "Title", "Page", "Step", "Expected Result"])
        sheet.append(["XL-1", "Search product", "Search", "Enter product name", "Results are displayed"])
        sheet.append(["XL-1", "Search product", "Search", "Click Search button", "Results are displayed"])
        sheet.append(["XL-2", "Empty search", "Search", "Click Search button", "Validation error is displayed"])
        data = io.BytesIO()
        workbook.save(data)
        payload = extract_and_normalize_source(self.feature, uploaded_bytes=data.getvalue(), uploaded_name="cases.xlsx")
        self.assertEqual(payload["scenario_count"], 2)
        self.assertEqual(len(payload["scenarios"][0]["steps"]), 3)
        self.assertEqual(payload["scenarios"][1]["id"], "XL-2")

    def test_generation_creates_one_spec_per_scenario_in_configured_testdir(self) -> None:
        self.write(
            "src/main/pages/LoginPage.ts",
            "import { Page } from '@playwright/test';\nexport class LoginPage {\n  constructor(private readonly page: Page) {}\n}\n",
        )
        payload = extract_and_normalize_source(
            self.feature,
            pasted_json_or_steps="""Test Case ID: A-1
Title: Valid login
Page: Login
Steps:
1. Open application
2. Enter username
Expected Result: Dashboard is displayed
---
Test Case ID: A-2
Title: Invalid login
Page: Login
Steps:
1. Open application
2. Enter invalid username
Expected Result: Error is displayed
""",
        )
        self.save_payload(payload)
        result = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["generated_spec_count"], 2)
        self.assertTrue(all(path.startswith("src/test/specs/") for path in result["generated_specs"]))
        self.assertIn("src/main/pages/LoginPage.ts", result["changed_files"])
        self.assertFalse((self.root / "pages/LoginPage.ts").exists())
        page_text = (self.root / "src/main/pages/LoginPage.ts").read_text(encoding="utf-8")
        self.assertIn("fillUsername", page_text)
        self.assertIn("verifyDashboard", page_text)
        self.assertEqual(len(list((self.root / "src/test/specs").glob(f"{self.feature}-*.spec.ts"))), 2)

    def test_failed_playwright_validation_rolls_back_all_source_changes(self) -> None:
        original_page = "import { Page } from '@playwright/test';\nexport class LoginPage {\n  constructor(private readonly page: Page) {}\n}\n"
        self.write("src/main/pages/LoginPage.ts", original_page)
        payload = extract_and_normalize_source(
            self.feature,
            pasted_json_or_steps="Test Case ID: RB-1\nTitle: Login rollback\nPage: Login\nSteps:\n1. Enter username\nExpected Result: Dashboard is displayed",
        )
        self.save_payload(payload)
        failed_validation = {"ok": False, "skipped": False, "returncode": 1, "stderr": "synthetic validation failure"}
        with patch("qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests._validate_specs", return_value=failed_validation):
            result = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["rollback"]["performed"])
        self.assertEqual(result["generated_specs"], [])
        self.assertEqual(result["changed_files"], [])
        self.assertTrue(result["attempted_generated_specs"])
        self.assertEqual((self.root / "src/main/pages/LoginPage.ts").read_text(encoding="utf-8"), original_page)
        self.assertFalse(list((self.root / "src/test/specs").glob(f"{self.feature}-*.spec.ts")))

    def test_ambiguous_page_placement_stops_before_source_changes(self) -> None:
        self.write("src/main/pages/LoginAlphaPage.ts", "import { Page } from '@playwright/test'; export class LoginAlphaPage { constructor(private page: Page) {} }\n")
        self.write("src/main/pages/LoginBetaPage.ts", "import { Page } from '@playwright/test'; export class LoginBetaPage { constructor(private page: Page) {} }\n")
        payload = extract_and_normalize_source(self.feature, pasted_json_or_steps="Scenario: Login user\n1. Enter username\nExpected Result: Dashboard is displayed")
        self.save_payload(payload)
        preview = preview_generation_placement(str(self.root), self.feature)
        self.assertTrue(preview["needs_user_confirmation"])
        result = generate_existing_framework_tests(str(self.root), self.feature, validate_generated=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_user_input"])
        self.assertFalse(list((self.root / "src/test/specs").glob(f"{self.feature}-*.spec.ts")))

    def test_explicit_linked_locator_repository_is_updated_without_new_file(self) -> None:
        self.write(
            "src/main/pageObjects/LoginObjects.ts",
            "import { Page } from '@playwright/test';\nexport class LoginObjects {\n  constructor(private readonly page: Page) {}\n}\n",
        )
        self.write(
            "src/main/pages/LoginPage.ts",
            "import { Page } from '@playwright/test';\nimport { LoginObjects } from '../pageObjects/LoginObjects';\nexport class LoginPage {\n  private readonly obj: LoginObjects;\n  constructor(private readonly page: Page) { this.obj = new LoginObjects(page); }\n}\n",
        )
        payload = extract_and_normalize_source(self.feature, pasted_json_or_steps="Test Case ID: L-1\nTitle: Login\nSteps:\n1. Click Login button\nExpected Result: Dashboard is displayed")
        self.save_payload(payload)
        result = generate_existing_framework_tests(
            str(self.root),
            self.feature,
            target_page_file="src/main/pages/LoginPage.ts",
            target_locator_file="src/main/pageObjects/LoginObjects.ts",
            validate_generated=False,
        )
        self.assertTrue(result["ok"])
        objects = (self.root / "src/main/pageObjects/LoginObjects.ts").read_text(encoding="utf-8")
        page = (self.root / "src/main/pages/LoginPage.ts").read_text(encoding="utf-8")
        self.assertIn("loginButtonLocator", objects)
        self.assertIn("this.obj.loginButtonLocator", page)
        self.assertNotIn("readonly loginButtonLocator", page)

    def test_mcp_transport_is_preferred_when_local_server_is_available(self) -> None:
        creds = AtlassianCredentials.from_values("https://example.atlassian.net", "", "person@example.com", "token", "")
        mcp_result = {
            "ok": True,
            "source_kind": "jira_issue",
            "source_text": "Jira Key: ABC-7\nIssue Type: Story\nTitle: MCP story\nDescription / Acceptance Criteria:\nThen success is displayed",
            "item_count": 1,
            "items": [{"key": "ABC-7", "title": "MCP story", "type": "Story"}],
            "transport_used": "atlassian_mcp_stdio",
            "mcp_tool_calls": ["jira_get_issue"],
            "message": "Fetched through MCP",
        }
        with patch.dict(os.environ, {"ASTRAHEAL_PREFER_ATLASSIAN_MCP": "true"}), patch("qa_pipeline.integrations.atlassian_mcp.shutil.which", return_value="/usr/bin/uvx"), patch("qa_pipeline.integrations.atlassian_mcp._fetch_via_mcp", return_value=mcp_result) as mocked:
            fetched = fetch_atlassian_source(creds, "jira_issue", issue_key="ABC-7")
        self.assertEqual(fetched["transport_used"], "atlassian_mcp_stdio")
        self.assertTrue(fetched["mcp_attempt"]["ok"])
        self.assertEqual(fetched["mcp_attempt"]["tool_calls"], ["jira_get_issue"])
        mocked.assert_called_once()

    def test_jira_epic_children_become_independent_testcases(self) -> None:
        epic = {"key": "ABC-100", "fields": {"summary": "Checkout epic", "issuetype": {"name": "Epic"}, "description": "Checkout business flow"}}
        children = [
            {"key": "ABC-101", "fields": {"summary": "Card payment", "issuetype": {"name": "Story"}, "priority": {"name": "High"}, "description": "Given user is on checkout\nWhen user pays by card\nThen payment succeeds"}},
            {"key": "ABC-102", "fields": {"summary": "Declined card", "issuetype": {"name": "Bug"}, "priority": {"name": "Medium"}, "description": "Given user is on checkout\nWhen card is declined\nThen an error is displayed"}},
        ]
        creds = AtlassianCredentials.from_values("https://example.atlassian.net", "", "person@example.com", "token", "")
        with patch("qa_pipeline.integrations.atlassian_mcp.JiraClient.fetch_epic_with_children", return_value={"epic": epic, "children": children, "search_attempts": []}):
            fetched = fetch_atlassian_source(creds, "jira_epic", epic_key="ABC-100")
        payload = extract_and_normalize_source(self.feature, pasted_json_or_steps=fetched["source_text"], source_mode="jira")
        self.assertEqual(fetched["item_count"], 2)
        self.assertEqual(payload["scenario_count"], 2)
        self.assertEqual([x["id"] for x in payload["scenarios"]], ["ABC-101", "ABC-102"])
        self.assertNotIn("ABC-100", [x["id"] for x in payload["scenarios"]])

    def test_atlassian_mcp_config_never_contains_supplied_secret(self) -> None:
        marker = "SECRET_TOKEN_MUST_NOT_BE_WRITTEN"
        config = prepare_atlassian_mcp_config()
        text = Path(config["config_file"]).read_text(encoding="utf-8")
        self.assertNotIn(marker, text)
        self.assertIn("${JIRA_API_TOKEN}", text)
        password_marker = "PASSWORD_VALUE_MUST_NOT_BE_WRITTEN"
        creds = AtlassianCredentials.from_values("https://example.atlassian.net", "", "person@example.com", marker, password_marker)
        with patch("qa_pipeline.integrations.atlassian_mcp.JiraClient.get_issue", return_value={"key": "ABC-1", "fields": {"summary": "Story", "issuetype": {"name": "Story"}, "description": "Given user opens app"}}):
            fetched = fetch_atlassian_source(creds, "jira_issue", issue_key="ABC-1")
        self.assertTrue(fetched["ok"])
        self.assertNotIn(marker, json.dumps(fetched))
        self.assertNotIn(password_marker, json.dumps(fetched))

    def test_new_routes_are_available_without_removing_existing_routes(self) -> None:
        paths = {route.path for route in app.routes}
        required = {
            "/api/module2/testcases/load",
            "/api/module2/playwright/preview-placement",
            "/api/module2/playwright/generate-existing",
            "/api/module2/atlassian/status",
            "/api/module2/atlassian/fetch",
            "/api/existing-framework/failure/analyze",
            "/api/existing-framework/self-heal/apply",
            "/api/browserstack/readiness",
        }
        self.assertTrue(required.issubset(paths), required - paths)


if __name__ == "__main__":
    unittest.main()
