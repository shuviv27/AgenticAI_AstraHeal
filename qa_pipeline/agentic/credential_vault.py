from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _SecretRecord:
    username: str
    password: str
    created_at: float
    ttl_seconds: int
    profiles: dict[str, dict[str, str]] = field(default_factory=dict)


_LOCK = threading.RLock()
_SECRETS: dict[str, _SecretRecord] = {}
_FEATURE_SECRETS: dict[str, _SecretRecord] = {}


def _normalise_profiles(profiles: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    clean: dict[str, dict[str, str]] = {}
    for key, raw in dict(profiles or {}).items():
        if not isinstance(raw, dict):
            continue
        item = {
            "username": str(raw.get("username") or ""),
            "password": str(raw.get("password") or ""),
            "role": str(raw.get("role") or "default"),
            "profile_id": str(raw.get("profile_id") or key),
        }
        if item["username"] or item["password"]:
            clean[str(key)] = item
    return clean


def store_ephemeral_credentials(
    username: str = "",
    password: str = "",
    ttl_seconds: int = 900,
    *,
    key: str = "",
    profiles: dict[str, Any] | None = None,
) -> str:
    """Store application credentials only in process memory.

    ``profiles`` may contain scenario-specific credential sets. Credentials are
    removed from memory as soon as the walkthrough agent consumes the run key,
    or after the TTL expires. Nothing in this vault is written to SQLite,
    LangSmith, reports, generated source, or testcase JSON.
    """
    purge_expired_credentials()
    token = str(key or secrets.token_urlsafe(24))
    with _LOCK:
        _SECRETS[token] = _SecretRecord(
            username=str(username or ""),
            password=str(password or ""),
            created_at=time.time(),
            ttl_seconds=max(60, min(int(ttl_seconds or 900), 3600)),
            profiles=_normalise_profiles(profiles),
        )
    return token


def consume_ephemeral_credentials(token: str) -> dict[str, Any]:
    purge_expired_credentials()
    with _LOCK:
        record = _SECRETS.pop(str(token or ""), None)
    if record is None:
        return {"username": "", "password": ""}
    result: dict[str, Any] = {"username": record.username, "password": record.password}
    if record.profiles:
        result["profiles"] = copy.deepcopy(record.profiles)
    return result


def store_feature_credential_profiles(
    feature: str,
    profiles: dict[str, Any],
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Temporarily retain credentials extracted from an uploaded source.

    The feature store bridges the separate *load testcase* and *walkthrough*
    button clicks within the same backend process. It is volatile and expires.
    Only a masked summary should ever be returned to the GUI.
    """
    purge_expired_credentials()
    key = str(feature or "").strip().lower()
    clean = _normalise_profiles(profiles)
    with _LOCK:
        if clean:
            _FEATURE_SECRETS[key] = _SecretRecord(
                username="",
                password="",
                created_at=time.time(),
                ttl_seconds=max(60, min(int(ttl_seconds or 3600), 7200)),
                profiles=clean,
            )
        else:
            _FEATURE_SECRETS.pop(key, None)
    return credential_profile_summary(key)


def get_feature_credential_profiles(feature: str) -> dict[str, dict[str, str]]:
    purge_expired_credentials()
    key = str(feature or "").strip().lower()
    with _LOCK:
        record = _FEATURE_SECRETS.get(key)
        return copy.deepcopy(record.profiles) if record else {}


def credential_profile_summary(feature: str) -> dict[str, Any]:
    profiles = get_feature_credential_profiles(feature)
    roles = sorted({str(item.get("role") or "default") for item in profiles.values()})
    complete = sum(1 for item in profiles.values() if item.get("username") and item.get("password"))
    return {
        "profile_count": len(profiles),
        "complete_profile_count": complete,
        "roles": roles,
        "scenario_ids": sorted(profiles),
        "credentials_persisted": False,
    }


def clear_feature_credential_profiles(feature: str) -> None:
    with _LOCK:
        _FEATURE_SECRETS.pop(str(feature or "").strip().lower(), None)


def purge_expired_credentials() -> int:
    now = time.time()
    removed = 0
    with _LOCK:
        for store in (_SECRETS, _FEATURE_SECRETS):
            for token, record in list(store.items()):
                if now - record.created_at > record.ttl_seconds:
                    store.pop(token, None)
                    removed += 1
    return removed


def credential_vault_size() -> int:
    purge_expired_credentials()
    with _LOCK:
        return len(_SECRETS) + len(_FEATURE_SECRETS)
