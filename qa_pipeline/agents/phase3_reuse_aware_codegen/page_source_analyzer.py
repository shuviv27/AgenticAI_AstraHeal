from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, GENERATED_PLAYWRIGHT_DIR
from qa_pipeline.core.text import camel_case

_TEXT_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_ATTR_RE = re.compile(r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", re.S)


@dataclass
class PageSourceElement:
    kind: str
    text: str
    tag: str = ""
    href: str = ""
    aria_label: str = ""
    title: str = ""
    alt: str = ""
    role: str = ""
    css_hint: str = ""
    confidence: float = 0.5
    source: str = "page_source"


def normalize_visible_text(value: str) -> str:
    value = unescape(str(value or ""))
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    value = _TAG_RE.sub(" ", value)
    value = _TEXT_WS_RE.sub(" ", value).strip()
    return value


def normalize_key(value: str) -> str:
    value = normalize_visible_text(value).lower()
    value = re.sub(r"\b(button|link|cta|menu|section|heading|image|icon)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return _TEXT_WS_RE.sub(" ", value).strip()


def _attrs(raw: str) -> dict[str, str]:
    return {m.group(1).lower(): unescape(m.group(3)) for m in _ATTR_RE.finditer(raw or "")}


def _css_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _text_from_inner(inner: str) -> str:
    return normalize_visible_text(inner)


def _add_unique(items: list[PageSourceElement], item: PageSourceElement) -> None:
    if not item.text and not item.aria_label and not item.alt and not item.href:
        return
    signature = (item.kind, normalize_key(item.text or item.aria_label or item.alt), item.href, item.css_hint)
    for existing in items:
        if (existing.kind, normalize_key(existing.text or existing.aria_label or existing.alt), existing.href, existing.css_hint) == signature:
            return
    items.append(item)


def _parse_anchors(html: str, base_url: str) -> list[PageSourceElement]:
    items: list[PageSourceElement] = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, re.I | re.S):
        attr = _attrs(m.group(1))
        text = _text_from_inner(m.group(2))
        aria = normalize_visible_text(attr.get("aria-label", ""))
        href = attr.get("href", "")
        label = aria or text or attr.get("title", "") or href
        parts = []
        if aria:
            parts.append(f'a[aria-label="{_css_string(aria)}"]')
        if href:
            # href exact is more reliable for navigation than auto-generated classes.
            parts.append(f'a[href="{_css_string(href)}"]')
            if href.startswith("/"):
                parts.append(f'a[href*="{_css_string(href.rstrip("/"))}"]')
        if text:
            parts.append(f'a:has-text("{_css_string(text)}")')
        css = ", ".join(dict.fromkeys(parts))
        _add_unique(items, PageSourceElement(kind="link", tag="a", text=text or aria, href=urljoin(base_url, href) if href else "", aria_label=aria, title=attr.get("title", ""), role=attr.get("role", "link"), css_hint=css, confidence=0.95 if href or aria else 0.75))
    return items


def _parse_buttons(html: str) -> list[PageSourceElement]:
    items: list[PageSourceElement] = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", html, re.I | re.S):
        attr = _attrs(m.group(1))
        text = _text_from_inner(m.group(2))
        aria = normalize_visible_text(attr.get("aria-label", ""))
        label = aria or text or attr.get("title", "")
        parts = []
        if aria:
            parts.append(f'button[aria-label="{_css_string(aria)}"]')
        if text:
            parts.append(f'button:has-text("{_css_string(text)}")')
        css = ", ".join(dict.fromkeys(parts))
        _add_unique(items, PageSourceElement(kind="button", tag="button", text=text or aria, aria_label=aria, title=attr.get("title", ""), role=attr.get("role", "button"), css_hint=css, confidence=0.9 if label else 0.6))
    return items


def _parse_headings(html: str) -> list[PageSourceElement]:
    items: list[PageSourceElement] = []
    for m in re.finditer(r"<h([1-6])\b([^>]*)>(.*?)</h\1>", html, re.I | re.S):
        level = m.group(1)
        text = _text_from_inner(m.group(3))
        if text:
            css = f'h{level}:has-text("{_css_string(text)}")'
            _add_unique(items, PageSourceElement(kind="heading", tag=f"h{level}", text=text, css_hint=css, confidence=0.96))
    return items


def _parse_images(html: str) -> list[PageSourceElement]:
    items: list[PageSourceElement] = []
    for m in re.finditer(r"<img\b([^>]*)/?>", html, re.I | re.S):
        attr = _attrs(m.group(1))
        alt = normalize_visible_text(attr.get("alt", ""))
        title = normalize_visible_text(attr.get("title", ""))
        src = attr.get("src", "")
        label = alt or title
        if not label:
            continue
        parts = []
        if alt:
            parts.append(f'img[alt="{_css_string(alt)}"]')
            parts.append(f'img[alt*="{_css_string(alt.split()[0])}" i]')
        if title:
            parts.append(f'img[title="{_css_string(title)}"]')
        css = ", ".join(dict.fromkeys(parts))
        _add_unique(items, PageSourceElement(kind="image", tag="img", text=label, alt=alt, title=title, href=src, css_hint=css, confidence=0.85))
    return items


def _parse_text_blocks(html: str) -> list[PageSourceElement]:
    items: list[PageSourceElement] = []
    for tag in ["p", "strong", "span", "div"]:
        for m in re.finditer(fr"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.I | re.S):
            text = _text_from_inner(m.group(1))
            if 3 <= len(text) <= 120 and not text.startswith(".") and not text.startswith("@"):
                # Keep a curated amount of useful visible text; avoid huge CSS/script fragments.
                if any(key in text.lower() for key in ["shop", "acima", "lease", "retailer", "apply", "checkout", "app", "privacy", "terms", "facebook", "linkedin", "instagram", "support", "faq"]):
                    _add_unique(items, PageSourceElement(kind="text", tag=tag, text=text, css_hint=f':text("{_css_string(text)}")', confidence=0.55))
    return items


def parse_page_source(html_text: str, base_url: str = "") -> dict[str, Any]:
    html = str(html_text or "")
    base_url = str(base_url or "")
    items: list[PageSourceElement] = []
    for group in (_parse_anchors(html, base_url), _parse_buttons(html), _parse_headings(html), _parse_images(html), _parse_text_blocks(html)):
        for item in group:
            _add_unique(items, item)
    # Add synonyms for known dynamic-web wording differences discovered from static source.
    text_values = {normalize_key(i.text or i.aria_label or i.alt): i for i in items}
    if "start shopping" in text_values and "shop now" not in text_values:
        src = text_values["start shopping"]
        _add_unique(items, PageSourceElement(kind="link", tag="a", text="Shop now", href=src.href, aria_label=src.aria_label, css_hint=src.css_hint, confidence=0.72, source="page_source_synonym"))
    return {
        "base_url": base_url,
        "total_elements": len(items),
        "elements": [asdict(i) for i in items[:1200]],
        "top_texts": [i.text for i in items if i.text][:200],
    }


def page_source_search_paths(feature: str, base_url: str = "") -> list[Path]:
    feature = str(feature or "feature").lower()
    paths = [
        QA_CACHE_DIR / "page_sources" / f"{feature}.txt",
        QA_CACHE_DIR / "page_sources" / f"{feature}.html",
        REPO_ROOT / "samples" / "page_sources" / f"{feature}_page_source.txt",
        REPO_ROOT / "samples" / "page_sources" / f"{feature}_home_source.txt",
    ]
    if "acima.com" in str(base_url).lower() or feature == "acima":
        paths.append(REPO_ROOT / "samples" / "page_sources" / "acima_home_source.txt")
    return paths


def analyze_page_source(feature: str, base_url: str = "", source_path: Path | None = None) -> dict[str, Any]:
    chosen: Path | None = source_path if source_path and source_path.exists() else None
    if not chosen:
        for path in page_source_search_paths(feature, base_url):
            if path.exists():
                chosen = path
                break
    if not chosen:
        return {"ok": False, "message": "No uploaded or sample page source was found.", "elements": [], "total_elements": 0}
    text = chosen.read_text(encoding="utf-8", errors="replace")
    report = parse_page_source(text, base_url)
    report.update({"ok": True, "source_file": str(chosen)})
    reports_dir = GENERATED_PLAYWRIGHT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "page-source-map.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Feature-specific cache for codegen.
    cache_dir = QA_CACHE_DIR / "page_source_maps"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{feature}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def load_page_source_map(feature: str) -> dict[str, Any]:
    path = QA_CACHE_DIR / "page_source_maps" / f"{feature}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    report_path = GENERATED_PLAYWRIGHT_DIR / "reports" / "page-source-map.json"
    if report_path.exists():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def locator_hint_from_page_source(feature: str, target: str, action: str = "verify") -> dict[str, Any] | None:
    data = load_page_source_map(feature)
    elements = data.get("elements") or []
    if not elements:
        return None
    target_key = normalize_key(target)
    if not target_key:
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    target_words = set(target_key.split())
    for e in elements:
        values = [e.get("text", ""), e.get("aria_label", ""), e.get("alt", ""), e.get("title", ""), e.get("href", "")]
        keys = [normalize_key(v) for v in values if v]
        key_words = set(" ".join(keys).split())
        score = 0.0
        if target_key in keys:
            score = 1.0
        elif any(target_key in k or k in target_key for k in keys if len(k) >= 3):
            score = 0.86
        elif target_words and key_words:
            overlap = len(target_words & key_words) / max(len(target_words), 1)
            score = overlap
        if score <= 0:
            continue
        # Action compatibility.
        kind = (e.get("kind") or "").lower()
        action_l = (action or "verify").lower()
        if action_l.startswith("click") and kind not in {"link", "button", "text"}:
            score *= 0.55
        if action_l in {"verify", "assert", "validate"} and kind in {"heading", "text", "link", "button", "image"}:
            score *= 1.05
        candidates.append((score + float(e.get("confidence", 0)) * 0.1, e))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    score, best = candidates[0]
    if score < 0.54:
        return None
    label = best.get("aria_label") or best.get("text") or best.get("alt") or target
    kind = (best.get("kind") or "text").lower()
    css = best.get("css_hint") or ""
    fallbacks: list[dict[str, str]] = []
    if kind == "link":
        primary = {"strategy": "role", "role": "link", "value": label, "description": target}
        if css:
            primary = {"strategy": "css", "value": css, "description": target}
            fallbacks.append({"strategy": "role", "role": "link", "value": label})
        fallbacks.extend([{"strategy": "role", "role": "button", "value": label}, {"strategy": "text", "value": label}])
    elif kind == "button":
        primary = {"strategy": "role", "role": "button", "value": label, "description": target}
        if css:
            primary = {"strategy": "css", "value": css, "description": target}
            fallbacks.append({"strategy": "role", "role": "button", "value": label})
        fallbacks.extend([{"strategy": "role", "role": "link", "value": label}, {"strategy": "text", "value": label}])
    elif kind == "heading":
        primary = {"strategy": "role", "role": "heading", "value": label, "description": target}
        if css:
            fallbacks.append({"strategy": "css", "value": css})
        fallbacks.append({"strategy": "text", "value": label})
    elif kind == "image":
        primary = {"strategy": "css", "value": css or f'img[alt*="{_css_string(label.split()[0])}" i]', "description": target}
        fallbacks.append({"strategy": "text", "value": label})
    else:
        primary = {"strategy": "text", "value": label, "description": target}
    # De-duplicate fallbacks and avoid including empty values.
    unique = []
    seen = set()
    for fb in fallbacks:
        if not fb.get("value"):
            continue
        sig = json.dumps(fb, sort_keys=True)
        if sig not in seen:
            seen.add(sig); unique.append(fb)
    if unique:
        primary["fallbacks"] = unique
    primary["page_source_confidence"] = round(score, 3)
    primary["source"] = "static_page_source"
    return primary


def save_uploaded_page_source(feature: str, upload_path: Path) -> Path:
    cache_dir = QA_CACHE_DIR / "page_sources"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{feature}.txt"
    dest.write_text(upload_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return dest
