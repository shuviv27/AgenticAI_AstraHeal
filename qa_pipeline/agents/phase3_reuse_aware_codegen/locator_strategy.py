from __future__ import annotations

import re

from qa_pipeline.core.text import camel_case, kebab_case


def _label(target: str) -> str:
    value = re.sub(r"\b(button|link|menu|item|section|heading|image|logo|icon)\b", "", target, flags=re.IGNORECASE)
    return " ".join(value.split()).strip() or target.strip()


def locator_key(action: str, target: str) -> str:
    base = camel_case(target)
    lower = target.lower()
    action_lower = (action or "").lower()
    if action_lower == "click_nav_option":
        clean = re.sub(r"\bnavigation options?\b", "", target, flags=re.IGNORECASE).strip() or target
        return camel_case(f"nav {clean} link")
    if action_lower in ["verify", "assert", "expect", "validate"] and any(x in lower for x in ["heading", "title", "hero", "h1", "shop with acima leasing", "leasing"]):
        return base if base.endswith("Heading") else f"{base}Heading"
    if any(x in lower for x in ["button", "submit", "login", "save", "cancel", "add", "delete", "shop"]):
        return base if base.endswith("Button") else f"{base}Button"
    if any(x in lower for x in ["input", "field", "username", "password", "email", "name", "search"]):
        return base if base.endswith("Input") else f"{base}Input"
    if any(x in lower for x in ["link", "menu", "navigation", "facebook", "instagram", "linkedin", "privacy", "terms", "accessibility", "careers", "invest", "blog"]):
        return base if base.endswith("Link") else f"{base}Link"
    if any(x in lower for x in ["heading", "title", "hero"]):
        return base if base.endswith("Heading") else f"{base}Heading"
    if any(x in lower for x in ["logo", "image", "icon"]):
        return base if base.endswith("Image") else f"{base}Image"
    if "section" in lower:
        return base if base.endswith("Section") else f"{base}Section"
    return base


def method_name(action: str, target: str) -> str:
    action = (action or "verify").lower()
    target_norm = re.sub(r"[^a-z0-9]+", " ", str(target or "").lower()).strip()
    page_concepts = {"home page", "homepage", "page", "web page", "website", "site", "application", "page loaded successfully"}
    if action in ["verify", "assert", "expect", "validate", "verify_text_or_status"] and (target_norm in page_concepts or ("home page" in target_norm and any(w in target_norm for w in ["load", "loaded", "loads", "content"]))):
        return "verifyPageLoadedSuccessfully"
    if action in ["fill", "enter", "type"]:
        return "fill" + camel_key_title(target)
    if action in ["click", "tap", "select"]:
        return "click" + camel_key_title(target)
    if action == "click_nav_option":
        return "clickNav" + camel_key_title(target) + "AndVerifyNavigationOrMenu"
    if action == "verify_nav_menu_or_page_options":
        return "verify" + camel_key_title(target) + "MenuOrPageOptions"
    if action == "click_navigate":
        return "click" + camel_key_title(target) + "AndVerifyNavigation"
    if action == "click_external":
        return "click" + camel_key_title(target) + "AndVerifyExternalNavigation"
    if action in ["handle_location_permission", "handle_browser_permission", "handle_geolocation"]:
        return "handleLocationPermissionIfRequested"
    if action == "verify_store_list_populated":
        return "verifyStoreListPopulated"
    if action == "verify_page_loaded":
        return "verifyPageLoadedSuccessfully"
    if action == "verify_url":
        return "verify" + camel_key_title(target) + "Url"
    if action == "verify_responsive":
        return "verifyResponsiveLayoutSmoke"
    if action == "verify_keyboard_accessible":
        return "verifyKeyboardAccessible" + camel_key_title(target)
    if action == "verify_text_or_status":
        return "verify" + camel_key_title(target)
    if action in ["verify", "assert", "expect", "validate"]:
        return "verify" + camel_key_title(target)
    return camel_case(f"{action} {target}")


def camel_key_title(target: str) -> str:
    value = camel_case(target)
    return value[:1].upper() + value[1:]


def _with_common_fallbacks(primary: dict, label: str, target: str) -> dict:
    """Add safe dynamic-web fallbacks to keep visible text locatable even on non-standard components."""
    fallbacks = []
    clean = label or target
    role = primary.get("role")
    if primary.get("strategy") == "role" and role == "button":
        fallbacks.extend([
            {"strategy": "role", "role": "link", "value": clean},
            {"strategy": "text", "value": clean},
        ])
    elif primary.get("strategy") == "role" and role == "link":
        fallbacks.extend([
            {"strategy": "role", "role": "button", "value": clean},
            {"strategy": "text", "value": clean},
        ])
    elif primary.get("strategy") == "role" and role == "heading":
        fallbacks.append({"strategy": "text", "value": clean})
    elif primary.get("strategy") == "text":
        fallbacks.extend([
            {"strategy": "role", "role": "heading", "value": clean},
            {"strategy": "role", "role": "button", "value": clean},
            {"strategy": "role", "role": "link", "value": clean},
        ])
    if fallbacks:
        primary = {**primary, "fallbacks": fallbacks}
    return primary


def infer_locator(action: str, target: str) -> dict:
    lower = target.lower()
    label = _label(target)
    action_lower = (action or "").lower()

    # Dynamic modern web preference order: role/testId/label/text/css fallback.
    if action_lower == "click_nav_option":
        nav_label = re.sub(r"\bnavigation options?\b", "", label, flags=re.IGNORECASE).strip() or label
        href_hint = ""
        if nav_label.lower() == "shop":
            href_hint = "marketplace"
        elif "how it works" in nav_label.lower():
            href_hint = "how-it-works"
        elif "get the app" in nav_label.lower() or "mobile" in nav_label.lower():
            href_hint = "mobile-app"
        primary = {"strategy": "css", "value": f"nav a:has-text('{nav_label}'), header a:has-text('{nav_label}'), [role='navigation'] a:has-text('{nav_label}'), a[href*='{href_hint}']:has-text('{nav_label}')" if href_hint else f"nav a:has-text('{nav_label}'), header a:has-text('{nav_label}'), [role='navigation'] a:has-text('{nav_label}')", "description": target}
        primary["fallbacks"] = [
            {"strategy": "role", "role": "link", "value": nav_label},
            {"strategy": "text", "value": nav_label},
        ]
        return primary
    if "skip to main" in lower:
        return _with_common_fallbacks({"strategy": "role", "role": "link", "value": "Skip to main content"}, "Skip to main content", target)
    if "logo" in lower:
        return {"strategy": "css", "value": "header a:has(img), header img[alt*='Acima' i], a[aria-label*='home' i], a:has-text('acima')", "description": target}
    if "main content" in lower:
        return {"strategy": "css", "value": "main, [role='main'], #main-content", "description": target}
    if "footer" in lower:
        return {"strategy": "css", "value": "footer", "description": target}
    if "section" in lower:
        return _with_common_fallbacks({"strategy": "text", "value": label, "description": target}, label, target)
    if any(x in lower for x in ["heading", "title", "hero", "h1"]):
        return _with_common_fallbacks({"strategy": "role", "role": "heading", "value": label or target, "description": target}, label, target)
    if any(x in lower for x in ["username", "password", "email", "name", "input", "field", "search", "filter"]):
        return {"strategy": "label", "value": label or target, "description": target}
    if any(x in lower for x in ["link", "menu", "navigation", "facebook", "instagram", "linkedin", "privacy", "terms", "careers", "invest", "blog", "accessibility", "locations", "upbound", "support", "faq"]):
        return _with_common_fallbacks({"strategy": "role", "role": "link", "value": label or target, "description": target}, label, target)
    if any(x in lower for x in ["button", "submit", "login", "save", "cancel", "add", "delete", "shop", "download", "start"]):
        # For dynamic sites, visual buttons are often anchors; include link/text fallback.
        return _with_common_fallbacks({"strategy": "role", "role": "button", "value": label or target, "description": target}, label, target)
    # For marketing copy and non-standard components, visible text is more stable than auto-generated classes.
    return _with_common_fallbacks({"strategy": "text", "value": label or target, "description": target}, label, target)
