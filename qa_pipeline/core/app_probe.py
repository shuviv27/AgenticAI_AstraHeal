from __future__ import annotations

import ssl
import urllib.request
from urllib.error import URLError, HTTPError


def check_application_url(base_url: str, timeout: int = 12) -> dict:
    base_url = (base_url or "").strip()
    if not base_url:
        return {"ok": False, "error": "Base URL is empty. Enter the website/application URL in Project Setup."}
    if not base_url.startswith(("http://", "https://")):
        return {"ok": False, "error": "Base URL must start with http:// or https://", "base_url": base_url}
    req = urllib.request.Request(base_url, method="GET", headers={"User-Agent": "AI-QA-Pipeline-Probe/1.0"})
    try:
        # Use default SSL verification. We do not bypass enterprise SSL by default.
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            return {
                "ok": True,
                "base_url": base_url,
                "status_code": getattr(resp, "status", None),
                "content_type": resp.headers.get("content-type", ""),
                "message": "Application URL is reachable from this machine/container.",
            }
    except HTTPError as exc:
        return {
            "ok": exc.code < 500,
            "base_url": base_url,
            "status_code": exc.code,
            "error": str(exc),
            "message": "URL responded with HTTP status. This may still be usable for test execution.",
        }
    except URLError as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc.reason), "message": "URL is not reachable from this environment. Check VPN/proxy/VDI access."}
    except Exception as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc)}
