from __future__ import annotations

import io
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import openpyxl

from qa_pipeline.agentic.credential_vault import (
    consume_ephemeral_credentials,
    get_feature_credential_profiles,
    store_ephemeral_credentials,
    store_feature_credential_profiles,
)
from qa_pipeline.agentic.functional_walkthrough import (
    locator_from_element,
    rank_elements,
    walkthrough_directory,
    walkthrough_enhanced_testcase_path,
    walkthrough_report_path,
    _provider_decision,
    _scenario_credentials,
    _verified_locator_for_element,
    _deterministic_transition_decision,
    _expand_steps_with_inserted_actions,
    _resolve_step_target_adaptively,
)
from qa_pipeline.core.io import write_json
from qa_pipeline.core.paths import feature_testcase_path
from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import (
    extract_and_normalize_source,
    extract_excel_credential_profiles,
    generate_existing_framework_tests,
)


def test_locator_prefers_testid_then_accessible_fallbacks() -> None:
    locator = locator_from_element({
        "tag": "button",
        "role": "button",
        "text": "Submit",
        "accessible_name": "Submit order",
        "testid": "submit-order",
        "label": "",
        "placeholder": "",
        "dom_id": "submitBtn",
    })
    assert locator["ok"] is True
    assert locator["strategy"] == "testId"
    assert locator["value"] == "submit-order"
    assert any(item["strategy"] == "role" for item in locator["fallbacks"])


def test_element_ranking_uses_step_semantics_and_role() -> None:
    step = {"action": "click", "target": "Click Login button"}
    elements = [
        {"element_id": "el-1", "tag": "input", "role": "textbox", "accessible_name": "Username"},
        {"element_id": "el-2", "tag": "button", "role": "button", "accessible_name": "Login", "text": "Login"},
    ]
    ranked = rank_elements(step, elements)
    assert ranked[0]["element_id"] == "el-2"
    assert ranked[0]["locator"]["strategy"] == "role"


def test_ephemeral_credentials_are_consumed_once() -> None:
    token = store_ephemeral_credentials("user@example.test", "not-persisted")
    assert consume_ephemeral_credentials(token) == {"username": "user@example.test", "password": "not-persisted"}
    assert consume_ephemeral_credentials(token) == {"username": "", "password": ""}


def test_generation_never_blocks_on_missing_walkthrough_evidence() -> None:
    feature = f"walkthrough_optional_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    try:
        (root / "src/main/pages").mkdir(parents=True)
        (root / "src/test/specs").mkdir(parents=True)
        (root / "src/main/pages/LoginPage.ts").write_text(
            "import { Page } from '@playwright/test';\nexport class LoginPage { constructor(private readonly page: Page) {} }\n",
            encoding="utf-8",
        )
        (root / "src/test/specs/existing.spec.ts").write_text("import { test } from '@playwright/test'; test('x', async()=>{});", encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };", encoding="utf-8")
        path = feature_testcase_path("module2_uploaded", feature)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"feature": feature, "scenarios": [{"id": "TC-1", "title": "Login", "page": "Login", "steps": [{"action": "click", "target": "Login button"}]}]})
        result = generate_existing_framework_tests(
            str(root), feature,
            target_page_file="src/main/pages/LoginPage.ts",
            target_locator_file="src/main/pages/LoginPage.ts",
            validate_generated=False,
            require_walkthrough_evidence=True,
        )
        assert result["ok"] is True, result
        assert result["generated_spec_count"] == 1
        assert result["extension_plan"]["strict_walkthrough_requested_but_ignored"] is True
        assert result["extension_plan"]["provisional_locator_count"] == 1
        assert list((root / "src/test/specs").glob(f"{feature}-*.spec.ts"))
    finally:
        temp.cleanup()
        shutil.rmtree(feature_testcase_path("module2_uploaded", feature).parent, ignore_errors=True)
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)


def test_generation_uses_verified_walkthrough_locator() -> None:
    feature = f"walkthrough_locator_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    try:
        (root / "src/main/pages").mkdir(parents=True)
        (root / "src/test/specs").mkdir(parents=True)
        page = root / "src/main/pages/LoginPage.ts"
        page.write_text("import { Page } from '@playwright/test';\nexport class LoginPage { constructor(private readonly page: Page) {} }\n", encoding="utf-8")
        (root / "src/test/specs/existing.spec.ts").write_text("import { test } from '@playwright/test'; test('x', async()=>{});", encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };", encoding="utf-8")
        original = feature_testcase_path("module2_uploaded", feature)
        original.parent.mkdir(parents=True, exist_ok=True)
        payload = {"feature": feature, "scenarios": [{"id": "TC-1", "title": "Login", "page": "Login", "steps": [{"action": "click", "target": "Login button"}]}]}
        write_json(original, payload)
        enhanced = json.loads(json.dumps(payload))
        enhanced["scenarios"][0]["steps"][0]["walkthrough"] = {
            "status": "verified",
            "locator": {"strategy": "role", "role": "button", "value": "Log In", "exact": True, "confidence": 0.96, "fallbacks": [{"strategy": "text", "value": "Log In"}]},
        }
        enhanced_path = walkthrough_enhanced_testcase_path(feature)
        write_json(enhanced_path, enhanced)
        write_json(walkthrough_report_path(feature), {"ok": True, "ready_for_generation": True, "feature": feature})

        result = generate_existing_framework_tests(
            str(root), feature,
            target_page_file="src/main/pages/LoginPage.ts",
            target_locator_file="src/main/pages/LoginPage.ts",
            validate_generated=False,
            use_walkthrough_evidence=True,
            require_walkthrough_evidence=True,
        )
        assert result["ok"] is True, result
        text = page.read_text(encoding="utf-8")
        assert "getByRole" in text and "Log In" in text
        assert result["extension_plan"]["walkthrough_evidence_used"] is True
    finally:
        temp.cleanup()
        shutil.rmtree(feature_testcase_path("module2_uploaded", feature).parent, ignore_errors=True)
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)


def test_gui_uses_integrated_browser_grounded_generation_without_hard_gate() -> None:
    html = (Path(__file__).resolve().parents[1] / "qa_pipeline/gui/static/index.html").read_text(encoding="utf-8")
    addnew = html.split('<section id="addnew"', 1)[1].split('</section>', 1)[0]
    assert "Adaptive AI walkthrough" not in addnew
    assert "1. Load / normalize testcase source" in addnew
    assert "2. Preview placement" in addnew
    assert "3. Generate & add tests" in addnew
    assert "require_walkthrough_evidence" not in addnew
    assert "Browser-grounded generation" in addnew
    assert "browser_grounded_generation" in addnew
    assert "grounding_max_intermediate_actions" in addnew


def test_verified_locator_rejects_ambiguous_candidate_and_uses_unique_fallback() -> None:
    class FakeLocator:
        def __init__(self, markers): self.markers = markers
        def count(self): return len(self.markers)
        def evaluate_all(self, _script): return self.markers

    class FakePage:
        def get_by_test_id(self, value):
            assert value == "login"
            return FakeLocator(["el-3", "el-9"])
        def get_by_role(self, role, name, exact=False):
            assert role == "button" and name == "Log In" and exact is True
            return FakeLocator(["el-3"])

    bundle = {
        "ok": True,
        "confidence": 0.99,
        "all_candidates": [
            {"strategy": "testId", "value": "login", "confidence": 0.99},
            {"strategy": "role", "role": "button", "value": "Log In", "exact": True, "confidence": 0.96},
        ],
    }
    verified = _verified_locator_for_element(FakePage(), bundle, "el-3")
    assert verified["ok"] is True
    assert verified["strategy"] == "role"
    assert any(item["count"] == 2 and not item["matches_selected"] for item in verified["validation"])


def test_walkthrough_dom_capture_includes_open_shadow_roots() -> None:
    source = (Path(__file__).resolve().parents[1] / "qa_pipeline/agentic/functional_walkthrough.py").read_text(encoding="utf-8")
    assert "el.shadowRoot" in source
    assert "data-astraheal-walkthrough-id" in source


def test_excel_credentials_move_to_volatile_profiles_but_not_normalized_json() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Test_Case", "Summery", "Step Number", "Step Description", "Test Data", "Expected Result"])
    sheet.append(["TC_01", "Store coworker login", "1", "Enter valid Store Co-worker username", "Username: store.user@example.test", "Accepted"])
    sheet.append(["", "", "2", "Enter valid password", "Password: Temporary-Secret!", "Accepted"])
    data = io.BytesIO(); workbook.save(data)

    profiles = extract_excel_credential_profiles(data.getvalue(), "credential_test")
    payload = extract_and_normalize_source("credential_test", uploaded_bytes=data.getvalue(), uploaded_name="cases.xlsx")
    serialized = json.dumps(payload)

    assert profiles["TC_01"]["username"] == "store.user@example.test"
    assert profiles["TC_01"]["password"] == "Temporary-Secret!"
    assert profiles["TC_01"]["role"] == "store_coworker"
    assert "store.user@example.test" not in serialized
    assert "Temporary-Secret!" not in serialized
    assert payload["scenarios"][0]["steps"][0]["value_env"] == "SALESFORCE_STORE_COWORKER_TC_01_USERNAME"


def test_feature_profiles_are_handed_to_run_vault_and_selected_by_scenario() -> None:
    feature = f"vault_{uuid.uuid4().hex[:8]}"
    profiles = {
        "TC_01": {"username": "first@example.test", "password": "one", "role": "store_coworker"},
        "TC_02": {"username": "second@example.test", "password": "two", "role": "admin_user"},
    }
    store_feature_credential_profiles(feature, profiles)
    copied = get_feature_credential_profiles(feature)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    store_ephemeral_credentials(key=run_id, profiles=copied)
    consumed = consume_ephemeral_credentials(run_id)

    selected = _scenario_credentials({"id": "TC_02", "credential_profile": "admin_user"}, consumed)
    assert selected == {"username": "second@example.test", "password": "two", "role": "admin_user", "profile_id": "TC_02"}
    assert consume_ephemeral_credentials(run_id) == {"username": "", "password": ""}


def test_provider_failure_falls_back_to_ranked_live_dom() -> None:
    step = {"action": "fill", "target": "Enter Username"}
    elements = [
        {"element_id": "el-0", "tag": "input", "role": "textbox", "accessible_name": "Username", "label": "Username", "dom_id": "username"},
        {"element_id": "el-1", "tag": "button", "role": "button", "accessible_name": "Log In"},
    ]
    with patch("qa_pipeline.agentic.functional_walkthrough.provider_gateway.invoke_json", return_value={"ok": False, "error": "provider unavailable"}):
        decision = _provider_decision(
            provider="codex", model="", step=step, elements=elements,
            page_url="https://example.test/login", page_title="Login", repo_root=".",
        )
    assert decision["ok"] is True
    assert decision["element_id"] == "el-0"
    assert decision["decision_source"] in {"deterministic_dom_fallback", "deterministic_high_confidence"}
    assert decision["confidence"] >= 0.72
    assert decision.get("provider_fallback_from") == "codex" or decision.get("provider_skipped_reason")


def test_blocked_generation_writes_html_and_json_report() -> None:
    feature = f"walkthrough_report_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
    try:
        (root / "src/main/pages").mkdir(parents=True)
        (root / "src/test/specs").mkdir(parents=True)
        (root / "src/main/pages/LoginPage.ts").write_text("export class LoginPage {}\n", encoding="utf-8")
        (root / "src/test/specs/existing.spec.ts").write_text("import { test } from '@playwright/test'; test('x', async()=>{});", encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };", encoding="utf-8")
        path = feature_testcase_path("module2_uploaded", feature); path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"feature": feature, "scenarios": [{"id": "TC-1", "title": "Login", "page": "Login", "steps": [{"action": "click", "target": "Login button"}]}]})
        result = generate_existing_framework_tests(
            str(root), feature, target_page_file="src/main/pages/LoginPage.ts", target_locator_file="src/main/pages/LoginPage.ts",
            validate_generated=False, require_walkthrough_evidence=True,
        )
        assert Path(result["generation_report"]).exists()
        assert Path(result["generation_report_html"]).exists()
    finally:
        temp.cleanup()
        shutil.rmtree(feature_testcase_path("module2_uploaded", feature).parent, ignore_errors=True)
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)


def test_gui_exposes_generation_report_without_walkthrough_controls() -> None:
    html = (Path(__file__).resolve().parents[1] / "qa_pipeline/gui/static/index.html").read_text(encoding="utf-8")
    assert "Open latest functional walkthrough report" not in html
    assert "Open latest Playwright generation report" in html
    assert 'name="walkthrough_allow_mutations"' not in html
    route_paths = {getattr(route, "path", "") for route in __import__("qa_pipeline.gui.app", fromlist=["app"]).app.routes}
    assert "/api/agentic/walkthrough/report/html" in route_paths  # compatibility route remains
    assert "/api/module2/playwright/generation-report/html" in route_paths


def test_scenario_specific_environment_names_prevent_account_collision() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Test_Case", "Summery", "Step Number", "Step Description", "Test Data", "Expected Result"])
    sheet.append(["TC_08", "Admin flow one", "1", "Enter valid admin user", "Username: admin.one@example.test", "Accepted"])
    sheet.append(["", "", "2", "Enter valid password", "Password: Secret-One", "Accepted"])
    sheet.append(["TC_09", "Admin flow two", "1", "Enter valid admin user", "Username: admin.two@example.test", "Accepted"])
    sheet.append(["", "", "2", "Enter valid password", "Password: Secret-Two", "Accepted"])
    data = io.BytesIO(); workbook.save(data)

    payload = extract_and_normalize_source("account_collision", uploaded_bytes=data.getvalue(), uploaded_name="cases.xlsx")
    envs = [step.get("value_env") for scenario in payload["scenarios"] for step in scenario["steps"] if step.get("value_sensitive")]
    assert "SALESFORCE_ADMIN_TC_08_USERNAME" in envs
    assert "SALESFORCE_ADMIN_TC_09_USERNAME" in envs
    assert len(envs) == len(set(envs))


def test_post_generation_runtime_output_redacts_volatile_credentials() -> None:
    from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import _validate_specs

    temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
    try:
        cli = root / "node_modules/.bin/playwright"
        cli.parent.mkdir(parents=True)
        cli.write_text("", encoding="utf-8")
        cli.chmod(0o755)
        (root / "package.json").write_text("{}", encoding="utf-8")
        secret = "Do-Not-Write-This-Secret"
        from qa_pipeline.core.commands import CommandResult
        with patch("qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests._validate_generated_pom_contract", return_value={"ok": True}), patch(
            "qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests._validate_typescript_syntax", return_value={"ok": True}), patch(
            "qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests.run_command",
            side_effect=[
                CommandResult(ok=True, command="playwright test --list", returncode=0, stdout="listed", stderr=""),
                CommandResult(ok=False, command="playwright test", returncode=1, stdout=f"failure value={secret}", stderr=f"password {secret}"),
            ],
        ) as run:
            result = _validate_specs(
                root, ["tests/generated.spec.ts"], True, ["tests/generated.spec.ts"],
                execute_generated=True,
                execution_env={"SCENARIO_PASSWORD": secret},
                required_environment_variables=["SCENARIO_PASSWORD"],
            )
        assert run.call_count == 2
        assert result["ok"] is True
        assert result["runtime_execution"]["ok"] is False
        assert secret not in json.dumps(result)
        assert "[REDACTED]" in result["runtime_execution"]["stderr"]
    finally:
        temp.cleanup()


def test_runtime_failure_retains_generated_files_for_grounded_rca() -> None:
    feature = f"runtime_retain_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
    try:
        (root / "src/main/pages").mkdir(parents=True)
        (root / "src/test/specs").mkdir(parents=True)
        page = root / "src/main/pages/LoginPage.ts"
        page.write_text("import { Page } from '@playwright/test';\nexport class LoginPage { constructor(private readonly page: Page) {} }\n", encoding="utf-8")
        (root / "src/test/specs/existing.spec.ts").write_text("import { test } from '@playwright/test'; test('x', async()=>{});", encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };", encoding="utf-8")
        path = feature_testcase_path("module2_uploaded", feature); path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"feature": feature, "scenarios": [{"id": "TC-1", "title": "Login", "page": "Login", "steps": [{"action": "click", "target": "Login button"}]}]})
        with patch(
            "qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests._validate_specs",
            return_value={"ok": True, "runtime_execution": {"ok": False, "skipped": False, "stderr": "locator failed"}},
        ):
            result = generate_existing_framework_tests(
                str(root), feature, target_page_file="src/main/pages/LoginPage.ts", target_locator_file="src/main/pages/LoginPage.ts",
                validate_generated=True, execute_generated_after_creation=True,
            )
        assert result["ok"] is True
        assert result["extension_plan"]["runtime_execution_ok"] is False
        assert result["rollback"]["performed"] is False
        assert result["generated_spec_count"] == 1
        assert (root / result["generated_specs"][0]).exists()
        assert "retained" in result["message"].lower()
    finally:
        temp.cleanup()
        shutil.rmtree(feature_testcase_path("module2_uploaded", feature).parent, ignore_errors=True)
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)



def test_adaptive_transition_inserts_login_to_sandbox_before_password() -> None:
    step = {"action": "fill", "target": "Enter valid password", "description": "Enter valid password"}
    elements = [
        {"element_id": "el-0", "tag": "button", "role": "button", "accessible_name": "Log In to Sandbox", "text": "Log In to Sandbox"},
        {"element_id": "el-1", "tag": "a", "role": "link", "accessible_name": "Forgot Username", "text": "Forgot Username"},
    ]
    decision = _deterministic_transition_decision(step, elements)
    assert decision["ok"] is True
    assert decision["decision"] == "intermediate_action"
    assert decision["element_id"] == "el-0"
    assert decision["action"] == "click"
    assert decision["confidence"] >= 0.72


def test_adaptive_transition_rejects_business_mutation() -> None:
    step = {"action": "fill", "target": "Enter password"}
    elements = [
        {"element_id": "el-0", "tag": "button", "role": "button", "accessible_name": "Delete account", "text": "Delete account"},
        {"element_id": "el-1", "tag": "button", "role": "button", "accessible_name": "Purchase now", "text": "Purchase now"},
    ]
    decision = _deterministic_transition_decision(step, elements)
    assert decision["ok"] is False
    assert decision["decision"] == "manual"


def test_walkthrough_expands_discovered_prerequisite_for_generation() -> None:
    steps = [
        {"step_number": "2", "action": "fill", "target": "Enter valid password", "value_env": "APP_PASSWORD", "value_sensitive": True},
    ]
    result = {
        "step_index": 1,
        "step_number": "2",
        "enhanced_step": "Enter the password in the Password field.",
        "action": "fill",
        "ok": True,
        "status": "verified",
        "locator": {"strategy": "label", "value": "Password", "exact": True},
        "inserted_actions": [
            {
                "action": "click",
                "target": "Log In to Sandbox",
                "enhanced_step": "Click Log In to Sandbox to open the password page.",
                "status": "adaptive_intermediate_verified",
                "ok": True,
                "locator": {"strategy": "role", "role": "button", "value": "Log In to Sandbox", "exact": True},
            }
        ],
    }
    expanded = _expand_steps_with_inserted_actions(steps, [result])
    assert len(expanded) == 2
    assert expanded[0]["generated_by_walkthrough"] is True
    assert expanded[0]["action"] == "click"
    assert expanded[0]["walkthrough"]["status"] == "adaptive_intermediate_verified"
    assert expanded[1]["action"] == "fill"
    assert expanded[1]["walkthrough"]["locator"]["value"] == "Password"


def test_gui_removes_adaptive_walkthrough_controls() -> None:
    html = (Path(__file__).resolve().parents[1] / "qa_pipeline/gui/static/index.html").read_text(encoding="utf-8")
    assert 'name="walkthrough_max_intermediate_actions"' not in html
    assert "treats each normalized Excel/document step as a goal" not in html
    assert "startFunctionalWalkthrough" not in html


def test_default_locator_factory_supports_placeholder_end_to_end() -> None:
    source = (Path(__file__).resolve().parents[1] / "generated-playwright/utils/locatorFactory.ts").read_text(encoding="utf-8")
    assert "strategy: 'placeholder'" in source
    assert "case 'placeholder':" in source
    assert "getByPlaceholder" in source


def test_generation_uses_adaptive_intermediate_walkthrough_step() -> None:
    feature = f"adaptive_generation_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    try:
        (root / "src/main/pages").mkdir(parents=True)
        (root / "src/test/specs").mkdir(parents=True)
        page = root / "src/main/pages/LoginPage.ts"
        page.write_text("import { Page } from '@playwright/test';\nexport class LoginPage { constructor(private readonly page: Page) {} }\n", encoding="utf-8")
        (root / "src/test/specs/existing.spec.ts").write_text("import { test } from '@playwright/test'; test('x', async()=>{});", encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"@playwright/test": "1.50.0"}}), encoding="utf-8")
        (root / "playwright.config.ts").write_text("export default { testDir: './src/test/specs' };", encoding="utf-8")
        original = feature_testcase_path("module2_uploaded", feature)
        original.parent.mkdir(parents=True, exist_ok=True)
        original_payload = {
            "feature": feature,
            "scenarios": [{"id": "TC-1", "title": "Two-stage login", "page": "Login", "steps": [
                {"step_number": "1", "action": "fill", "target": "Password", "value_env": "APP_PASSWORD", "value_sensitive": True}
            ]}],
        }
        write_json(original, original_payload)
        enhanced = json.loads(json.dumps(original_payload))
        enhanced["scenarios"][0]["steps"] = [
            {
                "step_number": "1.1",
                "action": "click",
                "target": "Log In to Sandbox",
                "description": "Click Log In to Sandbox to open the password page.",
                "generated_by_walkthrough": True,
                "walkthrough": {
                    "status": "adaptive_intermediate_verified",
                    "locator": {"strategy": "role", "role": "button", "value": "Log In to Sandbox", "exact": True, "confidence": 0.96},
                },
            },
            {
                "step_number": "1",
                "action": "fill",
                "target": "Password",
                "value_env": "APP_PASSWORD",
                "value_sensitive": True,
                "walkthrough": {
                    "status": "verified",
                    "locator": {"strategy": "label", "value": "Password", "exact": True, "confidence": 0.94},
                },
            },
        ]
        write_json(walkthrough_enhanced_testcase_path(feature), enhanced)
        write_json(walkthrough_report_path(feature), {"ok": True, "ready_for_generation": True, "feature": feature})

        result = generate_existing_framework_tests(
            str(root), feature,
            target_page_file="src/main/pages/LoginPage.ts",
            target_locator_file="src/main/pages/LoginPage.ts",
            validate_generated=False,
            use_walkthrough_evidence=True,
            require_walkthrough_evidence=True,
        )
        assert result["ok"] is True, result
        page_text = page.read_text(encoding="utf-8")
        assert "Log In to Sandbox" in page_text
        assert "Password" in page_text
        assert "async clickLogInToSandbox" in page_text
        assert "async fillPassword" in page_text
        spec_files = list((root / "src/test/specs").glob(f"{feature}-*.spec.ts"))
        assert len(spec_files) == 1
        spec_text = spec_files[0].read_text(encoding="utf-8")
        assert "clickLogInToSandbox" in spec_text
        assert "fillPassword" in spec_text
        assert "test.step" in spec_text
        assert "AI-discovered prerequisite" in spec_text
    finally:
        temp.cleanup()
        shutil.rmtree(feature_testcase_path("module2_uploaded", feature).parent, ignore_errors=True)
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)



def test_adaptive_resolver_executes_intermediate_then_retries_original_goal() -> None:
    class FakeContext:
        def __init__(self, page): self.pages = [page]

    class FakeLocator:
        def __init__(self, page, marker, kind):
            self.page, self.marker, self.kind = page, marker, kind
        def count(self): return 1
        def evaluate_all(self, _script): return [self.marker]
        def wait_for(self, **_kwargs): return None
        def click(self, **_kwargs):
            if self.kind == "sandbox":
                self.page.state = "password"
                self.page.title_value = "Password"
        def fill(self, value, **_kwargs): self.page.filled[self.kind] = value
        def is_visible(self, **_kwargs): return True

    class FakePage:
        def __init__(self):
            self.state = "username"
            self.url = "https://example.test/login"
            self.title_value = "Login"
            self.filled = {}
            self.context = FakeContext(self)
        def title(self): return self.title_value
        def evaluate(self, script):
            if "querySelectorAll(selector)" in script:
                if self.state == "username":
                    return [
                        {"element_id": "el-0", "tag": "input", "role": "textbox", "accessible_name": "Username", "label": "Username", "dom_id": "username", "visible": True},
                        {"element_id": "el-1", "tag": "button", "role": "button", "accessible_name": "Log In to Sandbox", "text": "Log In to Sandbox", "dom_id": "sandbox", "visible": True},
                    ]
                return [
                    {"element_id": "el-0", "tag": "input", "role": "textbox", "accessible_name": "Password", "label": "Password", "dom_id": "password", "type": "password", "visible": True},
                    {"element_id": "el-1", "tag": "button", "role": "button", "accessible_name": "Login", "text": "Login", "dom_id": "login", "visible": True},
                ]
            return None
        def get_by_role(self, role, name, exact=False):
            if "Sandbox" in str(name): return FakeLocator(self, "el-1", "sandbox")
            if str(name) == "Password": return FakeLocator(self, "el-0", "password")
            if str(name) == "Username": return FakeLocator(self, "el-0", "username")
            return FakeLocator(self, "el-1", "login")
        def get_by_label(self, value, exact=False):
            return FakeLocator(self, "el-0", "password" if value == "Password" else "username")
        def get_by_placeholder(self, value, exact=False): return FakeLocator(self, "el-0", value.lower())
        def get_by_test_id(self, value): return FakeLocator(self, "el-0", value)
        def get_by_text(self, value, exact=False): return FakeLocator(self, "el-1", "sandbox" if "Sandbox" in value else "login")
        def locator(self, value): return FakeLocator(self, "el-0", value)
        def wait_for_timeout(self, _ms): return None
        def wait_for_load_state(self, *_args, **_kwargs): return None

    page = FakePage()
    result = _resolve_step_target_adaptively(
        page=page,
        step={"action": "fill", "target": "Enter valid password", "description": "Enter valid password"},
        provider="deterministic",
        model="",
        repo_root=".",
        confidence_threshold=0.72,
        action_timeout_ms=2000,
        max_intermediate_actions=4,
        event_publisher=None,
        scenario_id="TC_01",
        step_index=3,
        progress=30,
    )
    assert result["ok"] is True, result
    assert page.state == "password"
    assert result["locator"]["value"] == "Password"
    assert len(result["inserted_actions"]) == 1
    assert result["inserted_actions"][0]["target"] == "Log In to Sandbox"


def test_browser_grounding_orchestrator_is_non_blocking_and_records_mcp_evidence() -> None:
    from qa_pipeline.agentic.browser_grounded_generation import ground_testcases_for_generation

    feature = f"grounding_orchestrator_{uuid.uuid4().hex[:8]}"
    temp = tempfile.TemporaryDirectory()
    try:
        root = Path(temp.name)
        report = {
            "ok": False,
            "ready_for_generation": False,
            "verified_locator_count": 2,
            "scenarios": [{"scenario_id": "TC-1", "title": "Login", "steps": []}],
            "message": "Partial browser evidence collected.",
        }
        with patch("qa_pipeline.agentic.browser_grounded_generation.get_feature_credential_profiles", return_value={"TC-1": {"username": "u", "password": "p"}}), \
             patch("qa_pipeline.agentic.browser_grounded_generation.run_functional_walkthrough", return_value=report), \
             patch("qa_pipeline.agentic.browser_grounded_generation.mcp_status", return_value={"mcp_probe_ok": True}):
            result = ground_testcases_for_generation(
                framework_path=str(root), feature=feature, provider="codex", model="gpt-5",
                base_url="https://qa.example.test", headed=False,
            )
        assert result["attempted"] is True
        assert result["generation_may_continue"] is True
        assert result["partial"] is True
        assert result["credential_profile_count"] == 1
        assert result["credentials_persisted"] is False
        assert result["mcp"]["mcp_probe_ok"] is True
        assert "playwright codegen" in result["playwright_codegen_command"]
    finally:
        temp.cleanup()
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)


def test_grounded_login_prerequisite_propagates_to_independent_tests_on_same_app() -> None:
    from qa_pipeline.agentic.browser_grounded_generation import load_grounded_payload

    feature = f"propagate_login_{uuid.uuid4().hex[:8]}"
    original = {
        "feature": feature,
        "scenarios": [
            {"id": "TC-1", "title": "First", "steps": [
                {"step_number": "1", "action": "goto", "target": "Open app", "value": "https://qa.example.test"},
                {"step_number": "2", "action": "fill", "target": "Username"},
                {"step_number": "3", "action": "fill", "target": "Password"},
            ]},
            {"id": "TC-2", "title": "Second", "steps": [
                {"step_number": "1", "action": "goto", "target": "Open app", "value": "https://qa.example.test"},
                {"step_number": "2", "action": "fill", "target": "Username"},
                {"step_number": "3", "action": "fill", "target": "Password"},
            ]},
        ],
    }
    enhanced = json.loads(json.dumps(original))
    enhanced["scenarios"][0]["steps"] = [
        enhanced["scenarios"][0]["steps"][0],
        enhanced["scenarios"][0]["steps"][1],
        {
            "step_number": "3.1", "parent_step_number": "3", "action": "click",
            "target": "Log In to Sandbox", "generated_by_walkthrough": True,
            "walkthrough": {
                "status": "adaptive_intermediate_verified",
                "locator": {"strategy": "role", "role": "button", "value": "Log In to Sandbox", "exact": True},
            },
        },
        enhanced["scenarios"][0]["steps"][2],
    ]
    try:
        write_json(walkthrough_enhanced_testcase_path(feature), enhanced)
        merged = load_grounded_payload(feature, original)
        for scenario in merged["scenarios"]:
            targets = [str(step.get("target") or "") for step in scenario["steps"]]
            assert "Log In to Sandbox" in targets, (scenario["id"], targets)
            assert targets.index("Log In to Sandbox") < targets.index("Password")
    finally:
        shutil.rmtree(walkthrough_directory(feature), ignore_errors=True)


def test_page_object_contract_rejects_missing_generated_method() -> None:
    from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import _validate_generated_pom_contract

    temp = tempfile.TemporaryDirectory(); root = Path(temp.name)
    try:
        (root / "tests").mkdir(); (root / "pages").mkdir()
        (root / "pages/LoginPage.ts").write_text("export class LoginPage {}\n", encoding="utf-8")
        (root / "tests/login.spec.ts").write_text(
            "import { LoginPage } from '../pages/LoginPage';\nconst screen = new LoginPage();\nscreen.missingMethod();\n",
            encoding="utf-8",
        )
        result = _validate_generated_pom_contract(root, ["tests/login.spec.ts"])
        assert result["ok"] is False
        assert any(item["kind"] == "missing_page_method" for item in result["issues"])
    finally:
        temp.cleanup()


def test_native_submit_input_uses_value_as_accessible_name_and_stable_css() -> None:
    locator = locator_from_element({
        "tag": "input",
        "role": "button",
        "type": "submit",
        "control_value": "Log In to Sandbox",
        "accessible_name": "",
        "text": "",
        "dom_id": "Login",
        "name": "Login",
    })
    assert locator["ok"] is True
    assert locator["strategy"] == "role"
    assert locator["role"] == "button"
    assert locator["value"] == "Log In to Sandbox"
    candidates = locator["all_candidates"]
    assert any(item["strategy"] == "css" and item["value"] == "#Login" for item in candidates)
    assert any(item["strategy"] == "css" and 'name="Login"' in item["value"] for item in candidates)
    assert locator["control_signature"]


def test_smart_locator_rejects_ambiguous_and_undefined_candidates() -> None:
    source = (Path(__file__).resolve().parents[1] / "generated-playwright/utils/SmartLocator.ts").read_text(encoding="utf-8")
    assert "count === 1 && visible" in source
    assert "Role and accessible name cannot be undefined" in source
    assert '#Login, input[name="Login"], button[name="Login"]' in source
    assert "controlValue" in source


def test_generated_verified_login_locator_keeps_stable_control_across_page_states() -> None:
    from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import _locator_definition_from_walkthrough

    definition = _locator_definition_from_walkthrough({
        "strategy": "role",
        "role": "button",
        "value": "Log In to Sandbox",
        "exact": True,
        "stable_attributes": {
            "dom_id": "Login",
            "name": "Login",
            "type": "submit",
            "control_value": "Log In to Sandbox",
        },
        "fallbacks": [],
    }, "Click Log In to Sandbox button")
    assert "value: 'Log In to Sandbox'" in definition
    assert "#Login" in definition
    assert 'input[name="Login"]' in definition
    assert "value: 'Log In'" in definition
    assert "value: 'Login'" in definition


def test_verified_css_locator_values_are_not_treated_as_ui_text() -> None:
    from qa_pipeline.modules.playwright_ts_generator.enterprise_add_new_tests import _locator_definition_from_walkthrough

    definition = _locator_definition_from_walkthrough({
        "strategy": "css",
        "value": 'input[name="Login"]',
        "fallbacks": [{"strategy": "css", "value": 'input[type="submit"][value="Log In"]'}],
    }, "Login submit control")
    assert 'input[name="Login"]' in definition
    assert 'input[type="submit"][value="Log In"]' in definition
    assert 'input[name="Login\'' not in definition
