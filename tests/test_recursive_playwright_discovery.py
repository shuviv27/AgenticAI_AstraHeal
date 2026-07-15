from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa_pipeline.agents.existing_framework_control.controller import (
    _build_command as build_sequential_command,
    _discover_playwright_test_targets,
    _is_tests_folder_executable_spec,
    preview_existing_framework_tests,
)
from qa_pipeline.agents.existing_framework_control.deep_framework_agents import (
    build_deep_framework_understanding,
)
from qa_pipeline.agents.existing_framework_control.structure_discovery import (
    build_structure_profile,
    discover_configured_test_dirs,
)
from qa_pipeline.core.browserstack_adapter import (
    browserstack_credentials_status,
    build_browserstack_command,
    write_browserstack_config,
)
from qa_pipeline.core.commands import CommandResult
from qa_pipeline.core.distributed_history import (
    _build_command as build_distributed_command,
    _read_selected_tests,
)
from qa_pipeline.mcp.framework_full_control_fix import (
    _build_full_control_prompt,
    _impacted_files_from_preflight,
)
from qa_pipeline.mcp.mcp_readiness_preflight import run_mcp_readiness_preflight
from qa_pipeline.gui.app import _confirmed_provider_connection, app


SPEC_BODY = """import { test, expect } from '@playwright/test';
test('works', async ({ page }) => {
  await page.goto('https://example.com');
  await expect(page).toHaveTitle(/Example/);
});
"""


class RecursivePlaywrightDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "package.json").write_text(
            json.dumps({"name": "fixture", "scripts": {"test": "playwright test"}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, rel: str, text: str = "") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_exact_src_main_and_src_test_specs_layout_is_discovered(self) -> None:
        self.write("playwright.config.ts", "export default { testDir: './src/test/specs' };\n")
        self.write("src/main/api/client.ts", "export class ApiClient {}\n")
        self.write("src/main/config/environment.ts", "export const env = {};\n")
        self.write("src/main/pages/LoginPage.ts", "export class LoginPage {}\n")
        self.write("src/main/ui_base/BasePage.ts", "export class BasePage {}\n")
        self.write("src/test/specs/account/test1.spec.ts", SPEC_BODY)

        profile = build_structure_profile(self.root)

        self.assertEqual(profile["executable_specs"], ["src/test/specs/account/test1.spec.ts"])
        self.assertIn("src/test/specs", profile["configured_test_dirs"])
        self.assertIn("src/test/specs", profile["discovered_test_roots"])
        model = profile["component_directory_model"]
        self.assertIn("src/main/api", model["api_dirs"])
        self.assertIn("src/main/config", model["config_dirs"])
        self.assertIn("src/main/pages", model["page_dirs"])
        self.assertIn("src/main/ui_base", model["ui_base_dirs"])

    def test_find_scripts_uses_lightweight_recursive_discovery(self) -> None:
        self.write("src/test/specs/module/test1.spec.ts", SPEC_BODY)

        result = preview_existing_framework_tests(str(self.root))

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["framework_intelligence"]["stage"],
            "lightweight_recursive_structure_discovery",
        )
        self.assertEqual(
            result["selected_execution_scope"]["targets"],
            ["src/test/specs/module/test1.spec.ts"],
        )
        self.assertNotIn("agentic_framework_understanding", result["framework_intelligence"])

    def test_root_tests_legacy_layout_remains_supported(self) -> None:
        self.write("tests/login.spec.ts", SPEC_BODY)
        scope = _discover_playwright_test_targets(self.root)
        self.assertTrue(scope["ok"])
        self.assertEqual(scope["targets"], ["tests/login.spec.ts"])

    def test_monorepo_nested_config_and_src_specs_are_discovered(self) -> None:
        self.write(
            "apps/web/playwright.config.ts",
            "export default { testDir: './src/test/specs' };\n",
        )
        self.write("apps/web/src/test/specs/orders/order.spec.ts", SPEC_BODY)
        profile = build_structure_profile(self.root)
        self.assertIn("apps/web/src/test/specs", profile["configured_test_dirs"])
        self.assertIn("apps/web/src/test/specs/orders/order.spec.ts", profile["executable_specs"])

    def test_parent_relative_test_dir_is_resolved_safely(self) -> None:
        self.write(
            "configs/playwright.config.ts",
            "export default { testDir: '../src/automation/scenarios' };\n",
        )
        self.write("src/automation/scenarios/payments.spec.ts", "// configured executable target\n")
        self.assertEqual(discover_configured_test_dirs(self.root), ["src/automation/scenarios"])
        self.assertIn(
            "src/automation/scenarios/payments.spec.ts",
            build_structure_profile(self.root)["executable_specs"],
        )

    def test_path_join_test_dir_is_understood(self) -> None:
        self.write(
            "playwright.config.ts",
            "import path from 'path'; export default { testDir: path.join(__dirname, 'src', 'automation', 'scenarios') };\n",
        )
        self.write("src/automation/scenarios/custom.test.tsx", "// configured target\n")
        profile = build_structure_profile(self.root)
        self.assertIn("src/automation/scenarios", profile["configured_test_dirs"])
        self.assertIn("src/automation/scenarios/custom.test.tsx", profile["executable_specs"])


    def test_process_cwd_variable_test_dir_is_understood(self) -> None:
        self.write(
            "configs/playwright.config.ts",
            "import path from 'path'; const TEST_ROOT = path.resolve(process.cwd(), 'src', 'test', 'specs'); export default { testDir: TEST_ROOT };\n",
        )
        self.write("src/test/specs/process-cwd.spec.ts", "// configured target\n")
        self.assertIn("src/test/specs", discover_configured_test_dirs(self.root))

    def test_provider_gate_and_critical_routes_remain_available(self) -> None:
        rule_based = _confirmed_provider_connection("rule_based", live_probe=False)
        self.assertTrue(rule_based["ok"])
        self.assertTrue(rule_based["backend_validated"])
        self.assertFalse(rule_based["uses_api_key"])
        with patch.dict(os.environ, {}, clear=True):
            openai = _confirmed_provider_connection("openai", live_probe=False)
        self.assertFalse(openai["ok"])
        self.assertEqual(openai["connection_status"], "missing_configuration")
        self.assertNotIn("api_key", openai)
        self.assertNotIn("access_key", openai)
        self.assertFalse(openai.get("key_present"))
        paths = {route.path for route in app.routes}
        required = {
            "/api/module2/existing/prepare-ai-rag",
            "/api/module2/existing/discover-selectable-tests",
            "/api/module2/existing/run-selected",
            "/api/module2/distributed/plan",
            "/api/module2/distributed/run",
            "/api/existing-framework/failure/analyze",
            "/api/existing-framework/self-heal/propose",
            "/api/existing-framework/self-heal/apply",
            "/api/existing-framework/execute/failed-only",
            "/api/existing-framework/mcp/prepare",
            "/api/existing-framework/mcp/full-control-fix",
            "/api/browserstack/readiness",
            "/api/module2/testcases/load",
            "/api/module2/playwright/generate-new",
            "/api/module2/playwright/generate-existing",
            "/api/existing-framework/selector-health",
            "/api/existing-framework/self-heal/approval-request",
            "/api/existing-framework/self-heal/rollback-last",
            "/api/module2/framework-artifact/playwright-report",
            "/api/module2/framework-artifact/combined-report",
        }
        self.assertTrue(required.issubset(paths), required - paths)

    def test_unusual_path_requires_executable_content_proof(self) -> None:
        self.write("automation_flows/smoke/login.spec.js", SPEC_BODY)
        self.write("random/archive.spec.ts", "export const value = 1;\n")
        profile = build_structure_profile(self.root)
        self.assertIn("automation_flows/smoke/login.spec.js", profile["executable_specs"])
        self.assertNotIn("random/archive.spec.ts", profile["executable_specs"])
        rejected = {item["path"]: item["reason"] for item in profile["rejected_spec_candidates"]}
        self.assertEqual(
            rejected["random/archive.spec.ts"],
            "spec_named_file_without_test_root_or_executable_content_proof",
        )

    def test_generated_dependency_cache_and_history_paths_are_ignored(self) -> None:
        for rel in (
            "node_modules/pkg/tests/fake.spec.ts",
            "playwright-report/tests/fake.spec.ts",
            "test-results/tests/fake.spec.ts",
            ".qa-cache/tests/fake.spec.ts",
            ".aiqa-history/tests/fake.spec.ts",
        ):
            self.write(rel, SPEC_BODY)
        self.write("src/test/specs/real.spec.ts", SPEC_BODY)
        profile = build_structure_profile(self.root)
        self.assertEqual(profile["executable_specs"], ["src/test/specs/real.spec.ts"])

    def test_line_selector_for_deep_spec_is_accepted_for_execution(self) -> None:
        self.write("src/test/specs/module/test1.spec.ts", SPEC_BODY)
        self.assertTrue(
            _is_tests_folder_executable_spec(
                "src/test/specs/module/test1.spec.ts:17", root=self.root
            )
        )

    def test_deep_learning_maps_dependency_chain_and_structure(self) -> None:
        self.write("src/main/pages/LoginPage.ts", "export class LoginPage { async login() {} }\n")
        self.write(
            "src/test/specs/auth/login.spec.ts",
            "import { test } from '@playwright/test';\nimport { LoginPage } from '../../../main/pages/LoginPage';\ntest('login', async () => { new LoginPage(); });\n",
        )
        report = build_deep_framework_understanding(self.root)
        self.assertEqual(report["inventory_summary"]["spec_count"], 1)
        self.assertIn("src/test/specs", report["inventory_summary"]["discovered_test_roots"])
        chains = report["dependency_graph"]["spec_dependency_chains"]
        self.assertIn("src/test/specs/auth/login.spec.ts", chains)

    def test_mcp_preflight_falls_back_to_explicit_recursive_specs(self) -> None:
        self.write("src/test/specs/module/test1.spec.ts", SPEC_BODY)
        calls: list[list[str]] = []

        def fake_run(args, cwd=None, timeout=120, extra_env=None):
            calls.append(list(args))
            if args[:4] == ["npx", "playwright", "test", "--list"]:
                return CommandResult(False, " ".join(args), 1, stdout="Error: No tests found")
            if args[:3] == ["npx", "playwright", "test"] and "--list" in args:
                return CommandResult(True, " ".join(args), 0, stdout="Listing tests:\n  test1.spec.ts:1:1 › works\nTotal: 1 test")
            raise AssertionError(f"Unexpected command: {args}")

        with patch("qa_pipeline.mcp.mcp_readiness_preflight.resolve_command", return_value="tool"), patch(
            "qa_pipeline.mcp.mcp_readiness_preflight.run_command", side_effect=fake_run
        ):
            result = run_mcp_readiness_preflight(
                str(self.root), run_build=False, run_test_list=True, check_browser=False
            )

        self.assertTrue(result["ok"])
        check = result["checks"]["playwright_test_list"]
        self.assertFalse(check["default_config_ok"])
        self.assertTrue(check["recursive_discovery_fallback"]["ok"])
        self.assertTrue(any("src/test/specs/module/test1.spec.ts" in call for call in calls))

    def test_full_control_prompt_receives_structure_and_reuse_layers(self) -> None:
        self.write("playwright.config.ts", "export default { testDir: './src/test/specs' };\n")
        self.write("src/main/pages/LoginPage.ts", "export class LoginPage {}\n")
        self.write("src/test/specs/login.spec.ts", SPEC_BODY)
        structure = build_structure_profile(self.root)
        preflight = {
            "framework_structure": structure,
            "deep_framework_understanding": {
                "inventory_summary": {"spec_count": 1},
                "component_directory_model": structure["component_directory_model"],
                "dependency_graph": {"spec_dependency_chains": {}, "unresolved_imports": {}},
                "locator_strategy": {},
            },
            "checks": {},
            "typescript_errors": [],
        }
        prompt = _build_full_control_prompt(self.root, preflight, "preserve reuse", "framework_safe_scope")
        self.assertIn("src/test/specs/login.spec.ts", prompt)
        self.assertIn("src/main/pages", prompt)
        self.assertIn("Search the dependency chain before adding a locator or function", prompt)

    def test_test_list_failure_marks_config_files_as_safe_impact_scope(self) -> None:
        preflight = {
            "typescript_errors": [],
            "checks": {
                "deep_test_discovery": {"ok": True},
                "playwright_test_list": {"ok": False},
            },
        }
        impacted = _impacted_files_from_preflight(preflight)
        self.assertIn("playwright.config.ts", impacted)
        self.assertIn("tsconfig.json", impacted)
        self.assertIn("package.json", impacted)


    def test_sequential_and_distributed_commands_preserve_deep_paths(self) -> None:
        target = "src/test/specs/account/test1.spec.ts"
        self.write(target, SPEC_BODY)
        sequential = build_sequential_command(
            self.root, "chromium", True, [target]
        )
        distributed = build_distributed_command(
            self.root, [target], "chromium", True
        )
        self.assertIn(target, sequential)
        self.assertIn(target, distributed)
        self.assertIn("--headed", sequential)
        self.assertIn("--headed", distributed)

    def test_distributed_selection_accepts_custom_configured_test_dir(self) -> None:
        target = "src/automation/scenarios/payments.spec.ts"
        self.write("playwright.config.ts", "export default { testDir: './src/automation/scenarios' };\n")
        self.write(target, "// accepted through configured testDir\n")
        root, selected = _read_selected_tests(str(self.root), target)
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(selected, [target])

    def test_browserstack_adapter_preserves_deep_selected_test_path(self) -> None:
        selected = ["src/test/specs/account/test1.spec.ts"]
        cfg = write_browserstack_config(
            self.root,
            run_id="run-1",
            shard_id="shard-1",
            selected_tests=selected,
        )
        command = build_browserstack_command(self.root, cfg, selected)
        self.assertIn("src/test/specs/account/test1.spec.ts", command)
        cfg_text = cfg.read_text(encoding="utf-8")
        self.assertIn("${BROWSERSTACK_USERNAME}", cfg_text)
        self.assertIn("${BROWSERSTACK_ACCESS_KEY}", cfg_text)
        self.assertNotIn("secret", cfg_text.lower())

    def test_browserstack_credentials_are_read_from_environment_only(self) -> None:
        with patch.dict(
            os.environ,
            {"BROWSERSTACK_USERNAME": "user", "BROWSERSTACK_ACCESS_KEY": "key"},
            clear=False,
        ):
            status = browserstack_credentials_status()
        self.assertTrue(status["ok"])
        self.assertNotIn("user", status)
        self.assertNotIn("key", status)


if __name__ == "__main__":
    unittest.main()
