from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, QA_CACHE_DIR, REPORTS_DIR, ensure_dirs
from qa_pipeline.core.io import write_json


@dataclass
class LocatorRef:
    page: str
    key: str
    strategy: str
    value: str
    file: str


@dataclass
class MethodRef:
    page: str
    name: str
    file: str


@dataclass
class FrameworkInventory:
    locators: list[LocatorRef] = field(default_factory=list)
    methods: list[MethodRef] = field(default_factory=list)
    specs: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "locators": [asdict(x) for x in self.locators],
            "methods": [asdict(x) for x in self.methods],
            "specs": self.specs,
            "test_data": self.test_data,
        }

    def has_locator(self, page: str, key: str) -> bool:
        return any(x.page == page and x.key == key for x in self.locators)

    def has_method(self, page: str, name: str) -> bool:
        return any(x.page == page and x.name == name for x in self.methods)


def _page_from_file(path: Path) -> str:
    name = path.stem
    name = name.replace(".objects", "")
    return name.replace("Page", "") if name.endswith("Page") else name


def scan_framework() -> FrameworkInventory:
    ensure_dirs()
    inv = FrameworkInventory()
    po_dir = GENERATED_PLAYWRIGHT_DIR / "pageObjects"
    pages_dir = GENERATED_PLAYWRIGHT_DIR / "pages"

    for path in sorted(po_dir.glob("*Page.objects.ts")):
        text = path.read_text(encoding="utf-8")
        page = path.stem.replace(".objects", "").replace("Page", "")
        # Object format: key: { strategy: 'testId', value: 'username' }
        for m in re.finditer(r"(\w+)\s*:\s*\{[^}]*?strategy\s*:\s*['\"]([^'\"]+)['\"][^}]*?value\s*:\s*['\"]([^'\"]+)['\"]", text, re.S):
            inv.locators.append(LocatorRef(page=page, key=m.group(1), strategy=m.group(2), value=m.group(3), file=str(path.relative_to(GENERATED_PLAYWRIGHT_DIR))))

    for path in sorted(pages_dir.glob("*Page.ts")):
        text = path.read_text(encoding="utf-8")
        page = path.stem.replace("Page", "")
        for m in re.finditer(r"async\s+(\w+)\s*\(", text):
            inv.methods.append(MethodRef(page=page, name=m.group(1), file=str(path.relative_to(GENERATED_PLAYWRIGHT_DIR))))
        for m in re.finditer(r"\n\s*(\w+)\s*\(", text):
            name = m.group(1)
            if name not in {"constructor", "getLocator"} and not inv.has_method(page, name):
                inv.methods.append(MethodRef(page=page, name=name, file=str(path.relative_to(GENERATED_PLAYWRIGHT_DIR))))

    for path in sorted((GENERATED_PLAYWRIGHT_DIR / "tests").glob("**/*.spec.ts")):
        inv.specs.append(str(path.relative_to(GENERATED_PLAYWRIGHT_DIR)))

    for path in sorted((GENERATED_PLAYWRIGHT_DIR / "testData").glob("**/*")):
        if path.is_file():
            inv.test_data.append(str(path.relative_to(GENERATED_PLAYWRIGHT_DIR)))

    write_json(QA_CACHE_DIR / "framework-inventory.json", inv.to_dict())
    write_json(REPORTS_DIR / "framework-inventory.json", inv.to_dict())
    return inv
