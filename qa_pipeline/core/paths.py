from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QA_CACHE_DIR = REPO_ROOT / ".qa-cache"
GENERATED_PLAYWRIGHT_DIR = REPO_ROOT / "generated-playwright"
TESTCASES_DIR = REPO_ROOT / "testcases"
REPORTS_DIR = GENERATED_PLAYWRIGHT_DIR / "reports"
DOCS_DIR = REPO_ROOT / "docs"
SAMPLES_DIR = REPO_ROOT / "samples"

SOURCE_TYPE_DIRS = {
    "jira": TESTCASES_DIR / "jira_epics",
    "jira_epics": TESTCASES_DIR / "jira_epics",
    "srs": TESTCASES_DIR / "srs",
    "pdf": TESTCASES_DIR / "pdf_docs",
    "pdf_docs": TESTCASES_DIR / "pdf_docs",
    "confluence": TESTCASES_DIR / "confluence",
    "test_management": TESTCASES_DIR / "test_management",
}


def ensure_dirs() -> None:
    for path in [
        QA_CACHE_DIR,
        GENERATED_PLAYWRIGHT_DIR,
        GENERATED_PLAYWRIGHT_DIR / "pageObjects",
        GENERATED_PLAYWRIGHT_DIR / "pages",
        GENERATED_PLAYWRIGHT_DIR / "tests" / "generated",
        GENERATED_PLAYWRIGHT_DIR / "tests" / "e2e",
        GENERATED_PLAYWRIGHT_DIR / "fixtures",
        GENERATED_PLAYWRIGHT_DIR / "testData",
        GENERATED_PLAYWRIGHT_DIR / "utils",
        REPORTS_DIR,
        TESTCASES_DIR / "jira_epics",
        TESTCASES_DIR / "srs",
        TESTCASES_DIR / "pdf_docs",
        TESTCASES_DIR / "confluence",
        TESTCASES_DIR / "test_management",
        DOCS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def feature_testcase_path(source_type: str, feature: str) -> Path:
    base = SOURCE_TYPE_DIRS.get(source_type, TESTCASES_DIR / source_type)
    return base / feature / f"{feature}.scenarios.json"
