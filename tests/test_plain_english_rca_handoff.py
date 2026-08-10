from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qa_pipeline.agents.existing_framework_control.controller import (
    _best_failed_inventory_for_followup,
    ensure_plain_english_rca_report,
)


class PlainEnglishRcaHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.framework = self.base / "framework"
        (self.framework / "tests" / "generated").mkdir(parents=True)
        (self.framework / "tests" / "generated" / "login.spec.ts").write_text(
            "import { test } from '@playwright/test';\ntest('login', async () => {});\n",
            encoding="utf-8",
        )
        self.reports = self.base / "reports"
        self.existing = self.reports / "existing-framework"
        self.existing.mkdir(parents=True)
        self.generic_inventory = self.reports / "failed-tests.json"
        self.generic_seq = self.reports / "sequential-execution-report.json"
        self.generic_dist = self.reports / "distributed-execution-report.json"
        self.existing_inventory = self.existing / "failed-tests.json"
        self.existing_execution = self.existing / "execution-report.json"
        self.plain_json = self.existing / "plain-english-failure-report.json"
        self.plain_html = self.existing / "plain-english-failure-report.html"
        self.rca_json = self.existing / "root-cause-report.json"
        self.html_dir = self.existing / "html"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_paths(self):
        return patch.multiple(
            "qa_pipeline.agents.existing_framework_control.controller",
            REPORTS_DIR=self.reports,
            EXISTING_REPORTS_DIR=self.existing,
            EXISTING_INVENTORY_JSON=self.existing_inventory,
            EXISTING_PLAIN_FAILURE_JSON=self.plain_json,
            EXISTING_PLAIN_FAILURE_HTML=self.plain_html,
            EXISTING_RCA_JSON=self.rca_json,
            EXISTING_HTML_DIR=self.html_dir,
            GENERIC_FAILED_INVENTORY_JSON=self.generic_inventory,
            GENERIC_SEQUENTIAL_EXECUTION_JSON=self.generic_seq,
            GENERIC_DISTRIBUTED_EXECUTION_JSON=self.generic_dist,
        )

    def _failed_inventory(self) -> dict:
        rec = {
            "id": "login::fails",
            "spec": "tests/generated/login.spec.ts",
            "title": "login fails",
            "status": "failed",
            "line": 8,
            "errors": [{"message": "Error: SmartLocator failed for Log In button. Locator resolved to 0 elements."}],
        }
        return {
            "ok": True,
            "framework_path": str(self.framework),
            "source": "sequential_execution",
            "all_specs": ["tests/generated/login.spec.ts"],
            "failed_specs": ["tests/generated/login.spec.ts"],
            "passed_specs": [],
            "all_test_cases": [rec],
            "failed_tests": [rec],
            "failed_test_cases": [rec],
            "failed_count": 1,
        }

    def test_plain_report_reads_generated_framework_failed_inventory(self) -> None:
        self.generic_inventory.write_text(json.dumps(self._failed_inventory()), encoding="utf-8")
        with self._patch_paths():
            result = ensure_plain_english_rca_report(str(self.framework))
        self.assertTrue(result["ready"], result)
        html = self.plain_html.read_text(encoding="utf-8")
        self.assertIn("login fails", html)
        self.assertIn("locator", html.lower())
        self.assertNotIn("No failed execution evidence", html)

    def test_newer_successful_run_overrides_older_failure(self) -> None:
        self.existing_inventory.write_text(json.dumps(self._failed_inventory()), encoding="utf-8")
        old = time.time() - 30
        os.utime(self.existing_inventory, (old, old))
        success = {
            "ok": True,
            "framework_path": str(self.framework),
            "source": "sequential_execution",
            "all_specs": ["tests/generated/login.spec.ts"],
            "passed_specs": ["tests/generated/login.spec.ts"],
            "failed_specs": [],
            "all_test_cases": [{
                "id": "login::passes",
                "spec": "tests/generated/login.spec.ts",
                "title": "login passes",
                "status": "passed",
            }],
            "failed_tests": [],
            "failed_count": 0,
        }
        self.generic_inventory.write_text(json.dumps(success), encoding="utf-8")
        with self._patch_paths():
            result = ensure_plain_english_rca_report(str(self.framework))
        self.assertTrue(result["ready"], result)
        html = self.plain_html.read_text(encoding="utf-8")
        self.assertIn("no failed tests", html.lower())
        self.assertNotIn("login fails", html)

    def test_followup_inventory_mirrors_generated_execution_for_rca_and_healing(self) -> None:
        self.generic_inventory.write_text(json.dumps(self._failed_inventory()), encoding="utf-8")
        with self._patch_paths(), patch(
            "qa_pipeline.agents.existing_framework_control.controller._latest_failed_only_remaining_inventory",
            return_value={},
        ):
            inventory = _best_failed_inventory_for_followup(str(self.framework))
        self.assertEqual(inventory["failed_specs"], ["tests/generated/login.spec.ts"])
        mirrored = json.loads(self.existing_inventory.read_text(encoding="utf-8"))
        self.assertEqual(mirrored["failed_count"], 1)
        self.assertIn("failed_test_cases", mirrored)


if __name__ == "__main__":
    unittest.main()

class GeneratedExecutionEvidenceTests(unittest.TestCase):
    def test_playwright_json_preserves_error_evidence_for_rca(self) -> None:
        from qa_pipeline.agents.phase4_review_execution.executor import _extract_failed_from_playwright_json
        payload = {
            "suites": [{
                "title": "generated",
                "file": "tests/generated/login.spec.ts",
                "specs": [{
                    "title": "login fails",
                    "file": "tests/generated/login.spec.ts",
                    "line": 12,
                    "tests": [{
                        "projectName": "chromium",
                        "results": [{
                            "status": "failed",
                            "errors": [{
                                "message": "Error: SmartLocator failed for Log In button",
                                "stack": "at SmartLocator.firstReachable"
                            }]
                        }]
                    }]
                }]
            }]
        }
        parsed = _extract_failed_from_playwright_json(payload)
        self.assertEqual(parsed["failed_specs"], ["tests/generated/login.spec.ts"])
        self.assertEqual(parsed["failed_test_case_count"], 1)
        self.assertIn("SmartLocator failed", parsed["failed_test_cases"][0]["error"])
        self.assertEqual(parsed["failed_test_cases"][0]["line"], 12)
