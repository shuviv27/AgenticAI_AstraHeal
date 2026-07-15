from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa_pipeline.agents.existing_framework_control.controller import (
    _explain_failed_case,
    _resolve_runtime_approved_files,
    _scope_from_failed_specs,
    create_runtime_patch_approval_request,
    existing_framework_artifact_locations,
)
from qa_pipeline.gui.app import app


class ExplainableRcaAndScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "package.json").write_text(json.dumps({"name": "scope-fixture"}), encoding="utf-8")
        (self.root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };\n", encoding="utf-8")
        (self.root / "tsconfig.json").write_text('{"compilerOptions":{"baseUrl":"."}}\n', encoding="utf-8")
        self.write("src/main/pages/LoginPage.ts", "export class LoginPage {}\n")
        self.write("src/main/ui_base/BasePage.ts", "export class BasePage {}\n")
        self.write(
            "src/test/specs/auth/login.spec.ts",
            "import { test } from '@playwright/test';\nimport { LoginPage } from '../../../main/pages/LoginPage';\ntest('login', async () => { new LoginPage(); });\n",
        )
        for idx in range(70):
            self.write(f"src/main/unrelated/Unused{idx}.ts", f"export const unused{idx} = {idx};\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_plain_english_rca_is_category_specific(self) -> None:
        module = _explain_failed_case({
            "spec": "src/test/specs/auth/login.spec.ts",
            "title": "loads config",
            "errors": ["Error: Cannot find module '@config/environment' Require stack: fixture.js"],
        }, root=self.root)
        overlay = _explain_failed_case({
            "spec": "src/test/specs/auth/login.spec.ts",
            "title": "clicks sign in",
            "errors": ["locator.click: another element intercepts pointer events"],
        }, root=self.root)
        assertion = _explain_failed_case({
            "spec": "src/test/specs/auth/login.spec.ts",
            "title": "shows dashboard",
            "errors": ["expect(received).toHaveText(expected) Expected: Dashboard Received: Login"],
        }, root=self.root)

        self.assertEqual(module["failure_category"], "typescript_module_resolution")
        self.assertIn("Do not edit locators", module["suggested_fix_area"])
        self.assertEqual(overlay["failure_category"], "overlay_or_blocker")
        self.assertIn("blocker", overlay["likely_fix_layer"].lower())
        self.assertEqual(assertion["failure_category"], "assertion_or_product_behavior_mismatch")
        self.assertIn("requirement", assertion["suggested_fix_area"].lower())
        self.assertNotEqual(module["suggested_fix_area"], overlay["suggested_fix_area"])

    def test_scope_provenance_excludes_unrelated_workspace_files(self) -> None:
        scope = _scope_from_failed_specs(self.root, ["src/test/specs/auth/login.spec.ts"])
        self.assertIn("src/test/specs/auth/login.spec.ts", scope["scope_groups"]["failed_spec_files"])
        self.assertIn("src/main/pages/LoginPage.ts", scope["scope_groups"]["imported_dependency_files"])
        self.assertNotIn("src/main/unrelated/Unused1.ts", scope["allowed_files"])
        self.assertLess(len(scope["allowed_files"]), 20)
        self.assertIn("file_reasons", scope)

    def test_runtime_approval_textarea_is_exact_write_boundary(self) -> None:
        approved = _resolve_runtime_approved_files(
            self.root,
            "src/main/pages/LoginPage.ts\nsrc/main/ui_base/BasePage.ts",
        )
        self.assertEqual(approved, ["src/main/pages/LoginPage.ts", "src/main/ui_base/BasePage.ts"])
        self.assertNotIn("src/test/specs/auth/login.spec.ts", approved)

    def test_approval_request_does_not_silently_grant_whole_workspace(self) -> None:
        scope = _scope_from_failed_specs(self.root, ["src/test/specs/auth/login.spec.ts"])
        rca = {
            "ok": True,
            "framework_path": str(self.root),
            "failed_specs": ["src/test/specs/auth/login.spec.ts"],
            "failed_inventory": {"failed_specs": ["src/test/specs/auth/login.spec.ts"]},
            "scope": scope,
            "signals": [{"kind": "locator_not_found_or_ambiguous", "recommendation": "verify DOM"}],
            "plain_english_failure_report": {
                "test_case_outcomes": [{
                    "spec": "src/test/specs/auth/login.spec.ts",
                    "test": "login",
                    "status": "failed",
                    "failure_category": "locator_missing_or_wrong_page_state",
                    "confidence": 0.82,
                    "plain_english_reason": "locator missing",
                    "likely_fix_layer": "page object",
                }]
            },
        }
        with patch("qa_pipeline.agents.existing_framework_control.controller.analyze_existing_failure", return_value=rca), patch(
            "qa_pipeline.agents.existing_framework_control.controller.read_human_intervention_memory", return_value={"records": []}
        ):
            payload = create_runtime_patch_approval_request(
                framework_path=str(self.root), provider="codex", policy_mode="approved_with_backup"
            )

        self.assertEqual(payload["allowed_files_count"], len(scope["allowed_files"]))
        self.assertGreater(payload["workspace_context_candidates_count"], payload["allowed_files_count"])
        self.assertFalse(payload["workspace_scope_enabled"])
        self.assertNotIn("src/main/unrelated/Unused1.ts", payload["allowed_files"])
        self.assertIn("not files that will definitely change", payload["allowed_files_explanation"])

    def test_local_artifact_locations_are_explicit(self) -> None:
        locations = existing_framework_artifact_locations(str(self.root))
        self.assertTrue(locations["ok"])
        self.assertTrue(Path(locations["central_report_root"]).is_absolute())
        self.assertTrue(Path(locations["central_cache_root"]).is_absolute())
        native_paths = [x["path"] for x in locations["framework_native_candidates"]]
        self.assertIn(str((self.root / "playwright-report" / "index.html").resolve()), native_paths)
        self.assertIn("plain_english_rca_html", locations["central_artifacts"])
        self.assertIn("self_healing_html", locations["central_artifacts"])
        self.assertIn("runtime_events", locations["central_artifacts"])

    def test_artifact_locations_route_is_available(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn("/api/existing-framework/artifact-locations", paths)


if __name__ == "__main__":
    unittest.main()
