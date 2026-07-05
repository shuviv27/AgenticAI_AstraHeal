from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.core.text import pascal_case

_QUOTE_RE = r"['\"]([^'\"]+)['\"]"


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError("PDF support requires dependency 'pypdf'. Run: python -m pip install -r requirements.txt") from exc
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _read_docx(path: Path) -> str:
    try:
        import docx  # type: ignore
    except Exception as exc:
        raise RuntimeError("DOCX support requires dependency 'python-docx'. Run: python -m pip install -r requirements.txt") from exc
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()


def extract_text_from_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in {".docx", ".doc"}:
        if suffix == ".doc":
            raise RuntimeError("Legacy .doc is not supported. Please convert to .docx or paste text in the GUI.")
        return _read_docx(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def _detect_feature(text: str, default_feature: str) -> str:
    patterns = [
        r"(?:feature|epic|module|story)\s*[:\-]\s*([A-Za-z0-9 _\-/]+)",
        r"#\s*([A-Za-z0-9 _\-/]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = m.group(1).strip().splitlines()[0]
            if value:
                return value[:60]
    return default_feature


def _section_to_tags(section: str) -> list[str]:
    low = section.lower()
    tags = []
    mapping = {
        "home": "home",
        "navigation": "navigation",
        "marketplace": "marketplace",
        "mobile": "mobile-app",
        "social": "social-links",
        "footer": "footer-legal",
        "legal": "footer-legal",
        "usability": "usability",
        "responsive": "responsive",
        "negative": "negative",
        "error": "error-handling",
        "accessibility": "accessibility",
    }
    for key, tag in mapping.items():
        if key in low and tag not in tags:
            tags.append(tag)
    return tags or ["functional"]


def _scenario_title(text: str, default_feature: str) -> str:
    for pattern in [
        r"(?:scenario|test case|acceptance criteria)\s*[:\-]\s*(.+)",
        r"As a .+? I want .+?(?: so that .+)?",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()[:140]
    return f"Validate {default_feature} business flow"


def _strip_step_prefix(line: str) -> str:
    return re.sub(r"^(given|when|then|and|precondition|expected)\b\s*[:\-]?\s*", "", line.strip(), flags=re.IGNORECASE)


def _quoted_or_after_as(line: str) -> str | None:
    m = re.search(_QUOTE_RE, line)
    if m:
        return m.group(1).strip()
    m = re.search(r"[“”]([^“”]+)[“”]", line)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bas\s+([^,.;]+)$", line, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _clean_target(raw: str) -> str:
    text = raw.strip().strip("'\"")
    text = re.sub(r"^(the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+as\s+['\"].+?['\"]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+as\s+[^,.;]+$", "", text, flags=re.IGNORECASE)
    text = text.replace("<", "").replace(">", "")
    return text.strip()


def _parse_launch(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if not any(token in low for token in ["launch", "open", "navigate", "go to", "goto", "visit", "opening"]):
        return None
    m = re.search(r"https?://[^\s'\"]+", line, re.IGNORECASE)
    if not m:
        m2 = re.search(_QUOTE_RE, line)
        if m2 and (m2.group(1).startswith("http://") or m2.group(1).startswith("https://")):
            return {"action": "goto", "target": "application", "value": m2.group(1)}
        return None
    return {"action": "goto", "target": "application", "value": m.group(0).rstrip(".,)")}


def _parse_enter(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if not any(token in low for token in ["enter", "type", "fill", "input"]):
        return None
    value = _quoted_or_after_as(line)
    m = re.search(r"(?:enter|type|fill|input)\s+(?:the\s+)?(.+?)(?:\s+as\s+|\s*=\s*|\s+with\s+)", line, re.IGNORECASE)
    if m:
        target = _clean_target(m.group(1))
    else:
        after = re.sub(r"^(enter|type|fill|input)\s+", "", _strip_step_prefix(line), flags=re.IGNORECASE)
        target = _clean_target(after)
    return {"action": "fill", "target": target or "input field", "value": value or ""}


def _parse_click(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if not re.search(r"^(?:verify\s+)?(?:click|clicking|tap|press|select)\b", _strip_step_prefix(line), re.IGNORECASE):
        return None
    target = None
    m = re.search(_QUOTE_RE, line)
    if m:
        target = m.group(1)
        if "button" in low and "button" not in target.lower():
            target += " button"
        if "link" in low and "link" not in target.lower():
            target += " link"
    else:
        m = re.search(r"(?:click|tap|press|select)\s+(?:on\s+)?(?:the\s+)?(.+)$", _strip_step_prefix(line), re.IGNORECASE)
        if m:
            target = m.group(1)
    return {"action": "click", "target": _clean_target(target or "button")}


def _parse_verify(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if not any(token in low for token in ["verify", "validate", "assert", "should", "must", "display", "shown", "visible", "expect"]):
        return None
    # Do not assert generic concepts like "home page" as visible text.
    # These must become page-readiness checks or concrete hero/header/footer assertions.
    if "home page" in low and any(token in low for token in ["load", "loads", "loaded", "open", "opens", "content", "successfully"]):
        return {"action": "verify_page_loaded", "target": "page loaded successfully", "expected": _strip_step_prefix(line)}
    target = _quoted_or_after_as(line) or _strip_step_prefix(line)
    return {"action": "verify", "target": _clean_target(target), "expected": _strip_step_prefix(line)}


def _normalize_relative_path(path: str) -> str:
    value = path.strip().strip("'\".,)")
    if not value.startswith("/") and not value.startswith("http"):
        value = "/" + value
    return value


def _extract_click_target(line: str) -> str:
    quoted = _quoted_or_after_as(line)
    if quoted:
        return quoted.strip()
    # Verify clicking “How It Works” navigates to /how-it-works
    m = re.search(r"clicking\s+[“\"']?([^”\"']+?)[”\"']?\s+(?:navigates|opens|goes)", line, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:click|clicking)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+navigates|\s+opens|\s+goes|$)", line, re.IGNORECASE)
    if m:
        value = m.group(1).strip()
        value = re.split(r"\s*(?:&|and)\s+handle\b|\s+and\s+handle\b", value, flags=re.IGNORECASE)[0].strip()
        value = re.sub(r"\s+button\b.*$", " button", value, flags=re.IGNORECASE).strip()
        return value
    if "logo" in line.lower():
        return "Acima logo"
    return "link or button"



def _split_csv_items(value: str) -> list[str]:
    value = re.sub(r"\([^)]*depending on final layout[^)]*\)", "", value, flags=re.IGNORECASE)
    return [_clean_target(x) for x in re.split(r",|/", value) if _clean_target(x)]


def _maybe_split_complex_visibility_requirement(clean: str, feature: str) -> list[dict[str, Any]] | None:
    low = clean.lower()
    # Top navigation list should not become one huge locator. Split every menu entry.
    if "top navigation" in low and "items" in low:
        m = re.search(r"items\s*:\s*(.+)$", clean, re.IGNORECASE)
        items = _split_csv_items(m.group(1)) if m else []
        if items:
            return [{"action": "verify", "target": item, "expected": clean, "page": pascal_case(feature)} for item in items]
    # Three-step marketing section must become independent visible text checks.
    if "shopping is easy" in low and not any(nav in low for nav in ["navigates", "navigate", "opens", "click"]) and ("select a retailer" in low or "apply for a lease" in low or "shop" in low):
        return [
            {"action": "verify", "target": "Shopping is easy", "expected": clean, "page": pascal_case(feature)},
            {"action": "verify", "target": "Select a retailer", "expected": clean, "page": pascal_case(feature)},
            {"action": "verify", "target": "Apply for a lease", "expected": clean, "page": pascal_case(feature)},
            {"action": "verify", "target": "Shop & checkout", "expected": clean, "page": pascal_case(feature)},
        ]
    if "amazon" in low and "best buy" in low and "walmart" in low:
        return [
            {"action": "verify", "target": "Amazon", "expected": clean, "page": pascal_case(feature)},
            {"action": "verify", "target": "Best Buy", "expected": clean, "page": pascal_case(feature)},
            {"action": "verify", "target": "Walmart", "expected": clean, "page": pascal_case(feature)},
        ]
    if "primary buttons and links" in low and "keyboard" in low:
        return [{"action": "verify_keyboard_accessible", "target": "primary buttons and links", "expected": clean, "page": pascal_case(feature)}]
    return None


def _classify_test_type(title: str, section: str, steps: list[dict[str, Any]]) -> str:
    value = f"{section} {title} " + " ".join(str(s.get('action','')) + ' ' + str(s.get('target','')) for s in steps)
    low = value.lower()
    if any(x in low for x in ['accessibility', 'keyboard', 'focus', 'contrast', 'alt text', 'heading hierarchy']):
        return 'accessibility'
    if any(x in low for x in ['negative', '404', 'network interruption', 'restricted', 'error']):
        return 'negative'
    if any(x in low for x in ['navigation', 'footer', 'legal', 'marketplace', 'mobile app', 'social', 'responsive']):
        return 'regression'
    if any(x in low for x in ['http 200', 'loads successfully', 'logo', 'hero', 'smoke', 'critical path']):
        return 'smoke'
    if any(x in low for x in ['api', 'openapi', 'endpoint']):
        return 'api'
    if any(x in low for x in ['performance', 'load test', 'k6']):
        return 'performance'
    if any(x in low for x in ['security', 'zap', 'snyk', 'owasp']):
        return 'security'
    return 'functional'


def _test_type_tags(test_type: str) -> list[str]:
    mapping = {
        'smoke': ['smoke', 'functional'],
        'regression': ['regression', 'functional'],
        'accessibility': ['accessibility', 'a11y'],
        'negative': ['negative', 'error-handling'],
        'api': ['api'],
        'performance': ['performance', 'k6'],
        'security': ['security', 'zap'],
        'functional': ['functional'],
    }
    return mapping.get(test_type, ['functional'])


def _scenario_from_requirement_line(line: str, section: str, feature: str, base_url: str, index: int) -> dict[str, Any]:
    clean = line.strip().rstrip(".")
    low = clean.lower()
    tags = _section_to_tags(section)
    steps: list[dict[str, Any]] = []
    if base_url:
        steps.append({"action": "goto", "target": "application", "value": base_url, "page": pascal_case(feature)})

    complex_steps = _maybe_split_complex_visibility_requirement(clean, feature)
    if complex_steps:
        steps.extend(complex_steps)
        test_type = _classify_test_type(clean, section, steps)
        return {
            "id": f"{feature.upper()}-{index:03d}",
            "title": clean[:150],
            "page": pascal_case(feature),
            "priority": "high" if "navigation" in tags or "accessibility" in tags else "medium",
            "test_type": test_type,
            "suite": test_type,
            "preconditions": ["Enterprise Docker stack and selected AI provider should be healthy before pipeline execution."],
            "start_url": base_url or None,
            "steps": steps,
            "expected_result": clean,
            "source_section": section,
            "tags": list(dict.fromkeys([feature] + tags + _test_type_tags(test_type))),
        }

    # Page availability / HTTP smoke check.
    # A requirement such as "Verify Acima home page hero content loads correctly"
    # must not become a literal assertion for text "home page".  Home page is a
    # page concept; validate page readiness plus the real hero evidence.
    if ("hero" in low and "home page" in low and any(w in low for w in ["load", "loads", "loaded", "content", "correctly"])):
        steps.append({"action": "verify_page_loaded", "target": "page loaded successfully", "expected": clean, "page": pascal_case(feature)})
        if feature.lower() == "acima" or "acima" in low:
            steps.append({"action": "verify", "target": "Shop with Acima Leasing", "expected": clean, "page": pascal_case(feature)})
            steps.append({"action": "verify", "target": "Shop In-store", "expected": clean, "page": pascal_case(feature)})
            steps.append({"action": "verify", "target": "Shop Online", "expected": clean, "page": pascal_case(feature)})
    elif "shop in-store" in low and "shop online" in low and any(w in low for w in ["visible", "displayed", "shows"]):
        steps.append({"action": "verify", "target": "Shop In-store", "expected": clean, "page": pascal_case(feature)})
        steps.append({"action": "verify", "target": "Shop Online", "expected": clean, "page": pascal_case(feature)})
    elif "shop with acima leasing" in low and ("heading" in low or "hero" in low):
        steps.append({"action": "verify", "target": "Shop with Acima Leasing", "expected": clean, "page": pascal_case(feature)})
        if "lease" in low and "own" in low:
            steps.append({"action": "verify", "target": "lease-to-own solutions", "expected": clean, "page": pascal_case(feature)})
    elif "http 200" in low or "loads successfully" in low or "page loads" in low:
        url = re.search(r"https?://[^\s'\"]+", clean, re.IGNORECASE)
        if url:
            steps = [{"action": "goto", "target": "application", "value": url.group(0).rstrip(".,)"), "page": pascal_case(feature)}]
        steps.append({"action": "verify_page_loaded", "target": "page loaded successfully", "expected": clean, "page": pascal_case(feature)})
    # Click and navigate rules.
    elif any(word in low for word in ["navigates to", "navigates back", "opens", "open ", "opens "] ) and ("click" in low or "button" in low or "link" in low or "icon" in low or "logo" in low):
        target = _extract_click_target(clean)
        expected_url = ""
        url_match = re.search(r"https?://[^\s'\"]+", clean, re.IGNORECASE)
        if url_match:
            expected_url = url_match.group(0).rstrip(".,)")
        else:
            path_match = re.search(r"\((/[^)]+)\)|\s(/[-A-Za-z0-9_/]+)", clean)
            if path_match:
                expected_url = _normalize_relative_path(path_match.group(1) or path_match.group(2))
            elif "home page" in low or "back to the home" in low:
                expected_url = base_url or "/"
        if "logo" in target.lower():
            target = "Acima logo"
        same_site = bool(base_url and expected_url and expected_url.startswith(base_url.rstrip("/")))
        action = "click_external" if (("new tab" in low or "external" in low or expected_url.startswith("http")) and not same_site) else "click_navigate"
        steps.append({"action": action, "target": target, "value": expected_url, "expected": clean, "page": pascal_case(feature)})
    # Responsive / hover / focus checks become assertion-style steps.
    elif any(x in low for x in ["location permission", "browser permission", "allow location", "current location", "geolocation"]):
        target = _extract_click_target(clean) if any(w in low for w in ["click", "tap", "select"]) else "location permission"
        expected_url = _known_navigation_url(target)
        if target and target.lower() not in {"location permission", "browser permission"}:
            steps.append({"action": "click_navigate" if expected_url else "click", "target": _clean_target(target), "value": expected_url, "expected": clean, "page": pascal_case(feature)})
        steps.append({"action": "handle_location_permission", "target": "browser location permission", "expected": clean, "page": pascal_case(feature)})
        if any(x in low for x in ["shop list", "store list", "nearby stores", "partner locations", "locations populate"]):
            steps.append({"action": "verify_store_list_populated", "target": "store list", "expected": clean, "page": pascal_case(feature)})
    elif "responsive" in low or "mobile view" in low:
        steps.append({"action": "verify_responsive", "target": "responsive mobile layout", "expected": clean, "page": pascal_case(feature)})
    elif "keyboard" in low or "tab" in low or "focus" in low:
        steps.append({"action": "verify_keyboard_accessible", "target": "keyboard accessible controls", "expected": clean, "page": pascal_case(feature)})
    elif "404" in low or "non-existent" in low:
        steps = [{"action": "goto", "target": "non existent page", "value": (base_url.rstrip("/") + "/abcxyz") if base_url else "/abcxyz", "page": pascal_case(feature)}]
        steps.append({"action": "verify_text_or_status", "target": "404 or not found page", "expected": clean, "page": pascal_case(feature)})
    else:
        # Extract stable business target from verification text for modern web locators.
        target_hint = _quoted_or_after_as(clean)
        if "logo" in low:
            target_hint = "Acima logo"
        elif "skip to main content" in low:
            target_hint = "Skip to main content link"
        elif "footer" in low:
            target_hint = "footer"
        elif "copyright" in low:
            target_hint = "© 2026 Acima, All Rights Reserved"
        elif "mobile app" in low:
            target_hint = "Do more in the Acima mobile app"
        elif "marketplace" in low and "section" in low:
            target_hint = "Acima Marketplace"
        elif "shopping is easy" in low:
            target_hint = "Shopping is easy"
        elif "shop in-store" in low and "shop online" in low:
            target_hint = "Shop In-store and Shop Online buttons"
        elif "shop with acima leasing" in low:
            target_hint = "Shop with Acima Leasing heading"
        parsed = _parse_launch(clean) or _parse_enter(clean) or _parse_click(clean) or _parse_verify(clean)
        if parsed:
            if target_hint and parsed.get("action") == "verify":
                parsed["target"] = target_hint
            steps.append({**parsed, "page": pascal_case(feature)})
        else:
            steps.append({"action": "verify", "target": target_hint or clean, "expected": clean, "page": pascal_case(feature)})

    priority = "high" if any(t in tags for t in ["navigation", "accessibility", "negative"]) else "medium"
    test_type = _classify_test_type(clean, section, steps)
    return {
        "id": f"{feature.upper()}-{index:03d}",
        "title": clean[:150],
        "page": pascal_case(feature),
        "priority": priority,
        "test_type": test_type,
        "suite": test_type,
        "preconditions": ["Enterprise Docker stack and selected AI provider should be healthy before pipeline execution."],
        "start_url": base_url or None,
        "steps": steps,
        "expected_result": clean,
        "source_section": section,
        "tags": list(dict.fromkeys([feature] + tags + _test_type_tags(test_type))),
    }


def _structured_scenarios_from_srs(text: str, feature: str, base_url: str = "") -> list[dict[str, Any]]:
    """Create one functional testcase per SRS requirement line.

    This is intentionally deterministic before AI. Codex/Ollama may refine this JSON later,
    but this parser guarantees a usable traceable baseline for modern websites with many
    navigation/link/visibility requirements.
    """
    scenarios: list[dict[str, Any]] = []
    current_section = "General"
    index = 1
    for raw_line in text.splitlines():
        line = raw_line.strip(" \t•-")
        if not line:
            continue
        header = re.match(r"^\d+\.\s*(.+)$", line)
        if header and not line.lower().startswith("verify"):
            current_section = header.group(1).strip()
            continue
        if re.match(r"^(verify|validate|ensure|check|confirm)\b", line, re.IGNORECASE):
            scenarios.append(_scenario_from_requirement_line(line, current_section, feature, base_url, index))
            index += 1
    return scenarios


def _steps_from_text(text: str, feature: str) -> tuple[list[dict[str, Any]], str | None]:
    raw_lines: list[str] = []
    for block in text.splitlines():
        block = block.strip()
        if not block:
            continue
        parts = re.split(r"(?:(?<=\.)\s+)(?=(?:launch|open|navigate|go to|enter|type|fill|click|tap|verify|validate|then|when|and)\b)", block, flags=re.IGNORECASE)
        raw_lines.extend(parts)
    lines = [re.sub(r"^\d+[\).\-]\s*", "", ln.strip(" -•\t")) for ln in raw_lines if ln.strip()]

    steps: list[dict[str, Any]] = []
    start_url: str | None = None
    for line in lines:
        low = line.lower()
        if len(steps) >= 40:
            break
        if low.startswith(("feature:", "feature -", "scenario:", "scenario -", "title:")):
            continue
        parsed = _parse_launch(line)
        if parsed:
            start_url = parsed.get("value") or start_url
            steps.append({**parsed, "page": feature})
            continue
        for parser in (_parse_enter, _parse_click, _parse_verify):
            parsed = parser(line)
            if parsed:
                steps.append({**parsed, "page": feature})
                break
    if not steps:
        steps = [
            {"action": "verify", "target": f"{feature} page is available", "page": feature},
            {"action": "verify", "target": f"{feature} expected outcome is visible", "page": feature},
        ]
    return steps, start_url



def _jira_field(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\s*:\s*(.*)$", text, re.IGNORECASE | re.MULTILINE)
    return (m.group(1).strip() if m else "")


def _jira_description(text: str) -> str:
    m = re.search(r"Description\s*/\s*Acceptance Criteria\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else text.strip())


def _lines_after_marker(text: str, marker: str, stop_markers: list[str]) -> list[str]:
    lines = text.splitlines()
    capture = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip(" \t•-")
        if re.match(rf"^{re.escape(marker)}\s*:", stripped, re.IGNORECASE):
            capture = True
            remainder = re.sub(rf"^{re.escape(marker)}\s*:\s*", "", stripped, flags=re.IGNORECASE)
            if remainder:
                out.append(remainder)
            continue
        if capture and any(re.match(rf"^{re.escape(stop)}\s*:", stripped, re.IGNORECASE) for stop in stop_markers):
            break
        if capture and stripped:
            out.append(stripped)
    return out


def _target_from_angle_or_quote(line: str) -> str | None:
    m = re.search(r"<([^>]+)>", line)
    if m:
        return m.group(1).strip()
    return _quoted_or_after_as(line)


def _known_navigation_url(target: str) -> str:
    low = (target or "").lower().replace("-", " ").strip()
    if low == "shop":
        return "/marketplace"
    mapping = {
        "shop in store": "/find-a-store",
        "shop instore": "/find-a-store",
        "shop nearby": "/find-a-store",
        "partner locations": "/find-a-store",
        "shop online": "/shop-online",
        "how it works": "/how-it-works",
        "get the app": "/mobile-app",
        "mobile app": "/mobile-app",
        "marketplace": "/marketplace",
        "shop marketplace": "/marketplace",
        "about us": "/about-us",
        "ways to shop": "/ways-to-shop",
        "for retailers": "/partner",
        "support": "/aboutleasing",
        "support/faq": "/aboutleasing",
        "blog": "/blog",
        "accessibility": "/accessibility",
    }
    for key, value in mapping.items():
        if key in low:
            return value
    return ""


def _page_from_url_for_pom(url: str | None) -> str | None:
    value = str(url or "").lower()
    if not value:
        return None
    if any(x in value for x in ["/find-a-store", "find-a-store", "stores", "locations", "store-locator"]):
        return "FindStore"
    if any(x in value for x in ["/shop-online", "shop-online", "online-stores"]):
        return "ShopOnline"
    if any(x in value for x in ["/how-it-works", "how-it-works"]):
        return "HowItWorks"
    if any(x in value for x in ["/mobile-app", "get-the-app"]):
        return "MobileApp"
    if any(x in value for x in ["/marketplace", "shop-marketplace"]):
        return "Marketplace"
    if any(x in value for x in ["/login", "signin", "sign-in"]):
        return "Login"
    if value.startswith("http://") or value.startswith("https://") or value in {"/", "/en", "/home"}:
        return "Home"
    return None


def _page_for_step_pom(action: str, target: str, value: str = "", current_page: str | None = None) -> str:
    action_l = str(action or "").lower()
    target_l = str(target or "").lower()
    value_l = str(value or "").lower()
    hay = f"{action_l} {target_l} {value_l}"
    if action_l == "click_nav_option":
        return current_page or "Home"
    if action_l == "verify_nav_menu_or_page_options":
        return current_page or "Home"
    if any(x in hay for x in ["find-a-store", "store list", "stores", "shop list", "nearby", "partner locations", "location permission", "geolocation", "zip", "postal", "miles", "address", "directions"]):
        if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
            return current_page
        return "FindStore"
    if any(x in hay for x in ["shop-online", "shop online", "online stores"]):
        if action_l in {"click", "click_navigate", "click_external", "tap", "select"} and current_page:
            return current_page
        if action_l in {"verify", "assert", "expect", "validate"} and not any(x in value_l for x in ["/shop-online", "shop-online"]):
            return current_page or "Home"
        return "ShopOnline"
    if any(x in hay for x in ["how it works", "how-it-works", "within reach", "shop now"]):
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
    return current_page or "Home"


def _assign_pom_pages_to_steps(steps: list[dict[str, Any]], start_url: str | None = "") -> tuple[list[dict[str, Any]], str]:
    current_page = _page_from_url_for_pom(start_url) or "Home"
    primary_page = current_page
    out: list[dict[str, Any]] = []
    for step in steps:
        action = str(step.get("action", "")).lower()
        value = str(step.get("value") or "")
        target = str(step.get("target") or "")
        copied = dict(step)
        if action in {"goto", "launch", "open", "navigate"}:
            current_page = _page_from_url_for_pom(value) or current_page
            copied["page"] = current_page
            primary_page = primary_page or current_page
            out.append(copied)
            continue
        step_page = _page_for_step_pom(action, target, value, current_page=current_page)
        copied["page"] = step_page
        out.append(copied)
        if action in {"click_navigate", "click_external"}:
            current_page = _page_from_url_for_pom(value) or _page_for_step_pom("verify", target, value, current_page=step_page)
    return out, primary_page or "Home"


def _append_visible_text_steps(steps: list[dict[str, Any]], expected_text: str, page: str, suppress_menu_options: bool = False) -> None:
    for raw in expected_text.splitlines():
        line = raw.strip(" \t•-")
        if not line or line.lower().startswith(("expected result", "page loads", "it populates", "the page", "user is redirected")):
            continue
        # Split simple standalone nav/menu lists into separate assertions only when
        # this is a pure visibility check.  For flows like "Click <Shop> on the
        # navigation bar; it populates options ...", the options must be verified
        # by one scoped nav-menu/page assertion after the click, not as body-wide
        # literal text checks.
        if re.match(r"^(shop|how it works|get the app|help|en|overview|shop marketplace|shop nearby stores|shop online stores)$", line, re.IGNORECASE):
            if not suppress_menu_options:
                steps.append({"action": "verify", "target": line, "expected": expected_text, "page": page})
        elif "main heading" in line.lower() and "shop with acima leasing" in line.lower():
            steps.append({"action": "verify", "target": "Shop with Acima Leasing", "expected": expected_text, "page": page})
        elif "shop in-store" in line.lower() and "shop online" in line.lower():
            steps.append({"action": "verify", "target": "Shop In-store", "expected": expected_text, "page": page})
            steps.append({"action": "verify", "target": "Shop Online", "expected": expected_text, "page": page})
        else:
            quoted = _target_from_angle_or_quote(line)
            if quoted:
                steps.append({"action": "verify", "target": quoted, "expected": expected_text, "page": page})



def _contains_menu_option_list(expected_text: str) -> bool:
    low = (expected_text or "").lower()
    option_hits = sum(1 for item in [
        "overview",
        "shop marketplace",
        "shop nearby stores",
        "shop online stores",
        "get the app",
        "shop near me",
        "near me",
        "online",
    ] if item in low)
    return "populates" in low and option_hits >= 2


def _is_header_navigation_click(line: str, full_text: str, target: str) -> bool:
    line_low = (line or "").lower()
    full_low = (full_text or "").lower()
    target_low = (target or "").strip().lower()
    if target_low not in {"shop", "how it works", "get the app", "help", "en"}:
        return False
    return any(x in line_low for x in ["navigation bar", "nav bar", "navbar", "header", "top menu", "menu"]) \
        or any(x in full_low for x in ["navigation bar", "nav bar", "navbar"])

def _structured_scenario_from_jira_issue_text(text: str, feature: str, base_url: str = "") -> dict[str, Any] | None:
    """Turn one Jira Story/Task/Bug block into one useful testcase.

    Jira descriptions often contain Objective/Precondition/Steps/Expected Result rather than
    lines starting with "Verify". This parser keeps the Jira source isolated and prevents the
    generator from falling back to stale uploaded SRS/PDF testcases from a previous session.
    """
    if "Jira Key:" not in text and "Issue Type:" not in text and "Title:" not in text:
        return None
    key = _jira_field(text, "Jira Key") or feature.upper()
    issue_type = _jira_field(text, "Issue Type") or "Issue"
    title = _jira_field(text, "Title") or f"Validate {feature}"
    priority = (_jira_field(text, "Priority") or "Medium").lower()
    desc = _jira_description(text)
    page = pascal_case(feature)
    blob = f"{title}\n{desc}"
    low = blob.lower()
    steps: list[dict[str, Any]] = []
    if base_url:
        steps.append({"action": "goto", "target": "application", "value": base_url, "page": page})
    # Always start with a real page readiness check for web Jira items.
    if any(x in low for x in ["home page", "page content", "page loads", "navigate", "browser"]):
        steps.append({"action": "verify_page_loaded", "target": "page loaded successfully", "expected": title, "page": page})

    step_lines = _lines_after_marker(desc, "Steps", ["Expected result", "Expected Result", "Acceptance Criteria"])
    expected_lines = _lines_after_marker(desc, "Expected result", ["Actual result", "Notes"])
    expected_text = "\n".join(expected_lines) or desc

    # Specific Acima / modern-web patterns, still generic enough for equivalent applications.
    # Only add hero/header assertions when the story itself is really about home/hero content.
    # Jira descriptions are often copy/pasted and may say "main home page" even when the actual
    # step is a feature action such as "Click Shop In-Store and handle browser location permission".
    # Do not let generic boilerplate create unrelated assertions for feature/navigation stories.
    title_low = title.lower()
    expected_low = expected_text.lower()
    explicit_home_or_hero_story = (
        any(x in title_low for x in ["home page", "homepage", "hero content", "home contents"])
        or "main heading “shop with acima leasing" in expected_low
        or "main heading \"shop with acima leasing" in expected_low
        or ("shop with acima leasing" in expected_low and "shop in-store" in expected_low and "shop online" in expected_low)
    )
    if explicit_home_or_hero_story:
        steps.append({"action": "verify", "target": "Shop with Acima Leasing", "expected": expected_text, "page": page})
        steps.append({"action": "verify", "target": "Shop In-store", "expected": expected_text, "page": page})
        steps.append({"action": "verify", "target": "Shop Online", "expected": expected_text, "page": page})

    has_click_instruction = any("click" in l.lower() or "tap" in l.lower() or "select" in l.lower() for l in step_lines)
    expects_menu_options = _contains_menu_option_list(expected_text)
    # Only verify the global nav labels directly when the story is a nav visibility
    # check.  A story that says "Click <Shop> on navigation bar" must perform a
    # scoped click on the header nav item and then verify the resulting menu/page.
    if ("navigation bar" in low or "navbar" in low) and not has_click_instruction:
        for target in ["Shop", "How It Works", "Get the App", "Help", "En"]:
            if target.lower() in low or "navigation" in low:
                steps.append({"action": "verify", "target": target, "expected": expected_text, "page": page})
    for line in step_lines:
        line_low = line.lower()
        if "click" in line_low or "tap" in line_low or "select" in line_low:
            target = _target_from_angle_or_quote(line)
            if not target:
                m = re.search(r"(?:click|tap|select)\s+(?:on\s+)?(?:the\s+)?([^.&]+)", line, re.IGNORECASE)
                target = m.group(1).strip() if m else "target"
            target = _clean_target(target)
            expected_url = _known_navigation_url(target)
            if _is_header_navigation_click(line, blob, target):
                # Header/nav clicks are scoped to mimic a real user on the top navigation.
                # If the expected result describes dropdown/menu options, do NOT convert the
                # interaction into a direct route assertion such as /marketplace. The browser
                # must click the visible nav item first; the next verify_nav_menu_or_page_options
                # step confirms the dropdown/menu/page outcome.
                action = "click_nav_option"
                if expects_menu_options:
                    expected_url = ""
                elif not expected_url and target.lower() == "shop":
                    expected_url = "/marketplace"
            else:
                action = "click_navigate" if expected_url else "click"
            step_payload = {"action": action, "target": target, "value": expected_url, "expected": expected_text, "page": page}
            if action == "click_nav_option" and expects_menu_options:
                step_payload["navigation_behavior"] = "human_click_then_dropdown_or_menu_verification"
            steps.append(step_payload)
            if action == "click_nav_option" and expects_menu_options:
                steps.append({"action": "verify_nav_menu_or_page_options", "target": f"{target} navigation options", "value": target, "expected": expected_text, "page": page})
            if any(x in line_low for x in ["location permission", "browser permission", "allow location", "current location", "geolocation"]):
                # This is an instruction to handle a browser capability, not visible application text.
                # Generate a browser/zipcode handling action, never an assertion for literal
                # "location permission handled" text.
                steps.append({"action": "handle_location_permission", "target": "browser location permission", "expected": expected_text, "page": page})
    _append_visible_text_steps(steps, expected_text, page, suppress_menu_options=expects_menu_options)
    if (not expects_menu_options) and any(x in expected_text.lower() for x in ["shop list will populate", "store list", "nearby partner locations", "nearby stores", "partner locations"]):
        steps.append({"action": "verify_store_list_populated", "target": "store list", "expected": expected_text, "page": page})
    # De-duplicate identical action/target/value triplets while preserving order.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for step in steps:
        sig = (str(step.get("action", "")), str(step.get("target", "")).lower(), str(step.get("value", "")).lower())
        if sig not in seen:
            deduped.append(step)
            seen.add(sig)
    if not deduped:
        deduped = [{"action": "verify", "target": title, "expected": expected_text, "page": page}]
    deduped, primary_page = _assign_pom_pages_to_steps(deduped, base_url)
    test_type = _classify_test_type(title, issue_type, deduped)
    if any(step.get("action") == "verify_page_loaded" for step in deduped) and len(deduped) <= 4:
        test_type = "smoke"
    return {
        "id": key,
        "title": title[:180],
        "page": primary_page,
        "priority": "high" if priority == "high" else "medium",
        "test_type": test_type,
        "suite": test_type,
        "preconditions": ["Jira source is the active context for this generation run.", "Application URL is configured in Project Setup."],
        "start_url": base_url or None,
        "steps": deduped,
        "expected_result": expected_text,
        "source_section": issue_type,
        "source_ref": key,
        "tags": list(dict.fromkeys([feature, "jira", issue_type.lower(), key.lower().replace("-", "_"), *_test_type_tags(test_type)])),
    }


def _load_json_or_text_json(source_path: Path) -> dict[str, Any] | None:
    if source_path.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _normalize_existing_json(data: dict[str, Any], source_path: Path, source_type: str, feature: str, base_url: str = "") -> dict[str, Any]:
    if "scenarios" in data:
        data.setdefault("source_ref", source_path.name)
        data.setdefault("source_type", source_type)
        data.setdefault("feature", feature)
        data.setdefault("page", pascal_case(feature))
        if base_url:
            data.setdefault("start_url", base_url)
        for scenario in data.get("scenarios", []):
            scenario.setdefault("source_ref", source_path.name)
            scenario.setdefault("page", data.get("page", pascal_case(feature)))
            scenario.setdefault("priority", data.get("priority", "medium"))
            if base_url:
                scenario.setdefault("start_url", base_url)
            scenario.setdefault("preconditions", [])
            for step in scenario.get("steps", []):
                step.setdefault("page", scenario.get("page"))
        return data

    text_parts = []
    for key in ["key", "summary", "title", "description", "acceptance_criteria", "acceptanceCriteria"]:
        value = data.get(key)
        if value:
            text_parts.append(f"{key}: {value}")
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    for key in ["summary", "description"]:
        value = fields.get(key)
        if value:
            text_parts.append(f"{key}: {value}")
    text = "\n".join(text_parts) or json.dumps(data)
    clean_feature = pascal_case(_detect_feature(text, feature))
    steps, start_url = _steps_from_text(text, clean_feature)
    if base_url:
        start_url = base_url
    return {
        "source_ref": source_path.name,
        "source_type": source_type,
        "feature": feature,
        "page": clean_feature,
        "priority": data.get("priority", "medium"),
        "tags": [feature, source_type],
        "start_url": start_url,
        "scenarios": [{
            "id": data.get("key") or f"{source_type.upper()}-{re.sub(r'[^A-Za-z0-9]+', '-', feature).strip('-').upper()}-001",
            "title": _scenario_title(text, feature),
            "page": clean_feature,
            "priority": data.get("priority", "medium"),
            "preconditions": [],
            "start_url": start_url,
            "steps": steps,
            "expected_result": "Expected behavior from source document is verified",
            "source_ref": source_path.name,
        }],
        "raw_text_preview": text[:4000],
    }


def normalize_source_to_json(source_path: Path, source_type: str, feature: str, *, pasted_text: str | None = None, base_url: str = "") -> Path:
    if source_path.suffix.lower() == ".json" and not pasted_text:
        loaded = _load_json_or_text_json(source_path)
        if loaded is not None:
            data = _normalize_existing_json(loaded, source_path, source_type, feature, base_url=base_url)
            out_dir = source_path.parent / "normalized"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{feature}_{source_type}_normalized.json"
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return out

    text = pasted_text if pasted_text is not None else extract_text_from_source(source_path)
    clean_feature = pascal_case(_detect_feature(text, feature))
    feature_page = pascal_case(feature)
    jira_scenario = _structured_scenario_from_jira_issue_text(text, feature, base_url=base_url) if source_type in {"jira", "jira_epics"} else None
    srs_scenarios = [] if jira_scenario else _structured_scenarios_from_srs(text, feature, base_url=base_url)
    if jira_scenario:
        data = {
            "source_ref": source_path.name,
            "source_type": source_type,
            "feature": feature,
            "page": feature_page,
            "priority": jira_scenario.get("priority", "medium"),
            "tags": [feature, source_type, "jira-active-context"],
            "start_url": base_url or None,
            "scenarios": [jira_scenario],
            "raw_text_preview": text[:4000],
        }
    elif srs_scenarios:
        data = {
            "source_ref": source_path.name,
            "source_type": source_type,
            "feature": feature,
            "page": feature_page,
            "priority": "medium",
            "tags": [feature, source_type, "modern-web", "dynamic-components"],
            "start_url": base_url or None,
            "scenarios": [
                {**scenario, "source_ref": source_path.name}
                for scenario in srs_scenarios
            ],
            "raw_text_preview": text[:4000],
        }
    else:
        steps, start_url = _steps_from_text(text, clean_feature)
        start_url = base_url or start_url
        data = {
            "source_ref": source_path.name,
            "source_type": source_type,
            "feature": feature,
            "page": clean_feature,
            "priority": "medium",
            "tags": [feature, source_type],
            "start_url": start_url,
            "scenarios": [
                {
                    "id": f"{source_type.upper()}-{re.sub(r'[^A-Za-z0-9]+', '-', feature).strip('-').upper()}-001",
                    "title": _scenario_title(text, feature),
                    "page": clean_feature,
                    "priority": "medium",
                    "preconditions": [],
                    "start_url": start_url,
                    "steps": steps,
                    "expected_result": "Expected behavior from source document is verified",
                    "source_ref": source_path.name,
                }
            ],
            "raw_text_preview": text[:4000],
        }
    out_dir = source_path.parent / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{feature}_{source_type}_normalized.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
