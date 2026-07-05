from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any

import requests


JIRA_SEARCH_FIELDS = [
    "summary",
    "description",
    "issuetype",
    "status",
    "priority",
    "labels",
    "parent",
    "subtasks",
    "issuelinks",
    "customfield_10014",  # classic Epic Link on many Jira Cloud instances
    "customfield_10008",  # legacy Sprint on many Jira Cloud instances
]


def _clean_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def adf_to_text(value: Any) -> str:
    """Convert Jira Cloud Atlassian Document Format or plain values into readable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for part in (adf_to_text(v) for v in value) if part).strip()
    if isinstance(value, dict):
        parts: list[str] = []
        text = value.get("text")
        if text:
            parts.append(str(text))
        for key in ("content", "attrs", "value"):
            if key in value:
                child = adf_to_text(value[key])
                if child:
                    parts.append(child)
        return "\n".join(parts).strip()
    return str(value)


@dataclass
class JiraCredentials:
    base_url: str
    username: str
    api_token: str

    @classmethod
    def from_values(cls, base_url: str = "", username: str = "", api_token: str = "") -> "JiraCredentials":
        return cls(
            base_url=_clean_base_url(base_url or os.getenv("JIRA_URL") or os.getenv("JIRA_BASE_URL") or ""),
            username=(username or os.getenv("JIRA_USERNAME") or os.getenv("JIRA_EMAIL") or "").strip(),
            api_token=(api_token or os.getenv("JIRA_API_TOKEN") or "").strip(),
        )

    def missing(self) -> list[str]:
        missing = []
        if not self.base_url:
            missing.append("JIRA_URL")
        if not self.username:
            missing.append("JIRA_USERNAME or JIRA_EMAIL")
        if not self.api_token:
            missing.append("JIRA_API_TOKEN")
        return missing


class JiraClient:
    """Small Jira Cloud client used by the GUI.

    Important: Atlassian has removed/started removing the old /rest/api/3/search endpoint
    from Jira Cloud tenants.  This client uses the new enhanced JQL endpoint
    /rest/api/3/search/jql first, then falls back only for older/self-hosted compatible systems.
    """

    def __init__(self, creds: JiraCredentials):
        self.creds = creds
        missing = creds.missing()
        if missing:
            raise ValueError("Missing Jira configuration: " + ", ".join(missing))
        token = base64.b64encode(f"{creds.username}:{creds.api_token}".encode("utf-8")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else "/" + path
        return self.creds.base_url + path

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.get(self._url(path), headers=self.headers, params=params or {}, timeout=60)
        if resp.status_code >= 400:
            raise RuntimeError(f"Jira GET {path} failed: HTTP {resp.status_code}: {resp.text[:1500]}")
        return resp.json() if resp.text.strip() else {}

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(self._url(path), headers=self.headers, json=payload, timeout=90)
        if resp.status_code >= 400:
            raise RuntimeError(f"Jira POST {path} failed: HTTP {resp.status_code}: {resp.text[:1500]}")
        return resp.json() if resp.text.strip() else {}

    def myself(self) -> dict[str, Any]:
        return self.get("/rest/api/3/myself")

    def _issue_fields(self) -> list[str]:
        return list(JIRA_SEARCH_FIELDS)

    def search_issues(self, jql: str, max_results: int = 100) -> list[dict[str, Any]]:
        """Search Jira Cloud using current enhanced JQL endpoint.

        Returns all available issues up to max_results.  The new endpoint uses nextPageToken
        instead of startAt.  We keep a compatibility fallback for older Jira deployments only.
        """
        fields = self._issue_fields()
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        last_error: Exception | None = None

        # Current Jira Cloud endpoint. Old /rest/api/3/search returns HTTP 410 on many tenants.
        try:
            while len(issues) < max_results:
                batch_size = min(100, max_results - len(issues))
                payload: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": batch_size,
                    "fields": fields,
                    "fieldsByKeys": True,
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                data = self.post("/rest/api/3/search/jql", payload)
                issues.extend(data.get("issues", []) or [])
                next_page_token = data.get("nextPageToken")
                if data.get("isLast", True) or not next_page_token:
                    break
            return issues
        except Exception as exc:
            last_error = exc

        # Compatibility fallback: useful for older Data Center/proxy instances only.
        try:
            payload = {"jql": jql, "maxResults": max_results, "fields": fields, "fieldsByKeys": True}
            data = self.post("/rest/api/3/search", payload)
            return data.get("issues", []) or []
        except Exception as fallback_exc:
            raise RuntimeError(
                "Jira search failed on both enhanced and legacy endpoints. "
                f"Enhanced /rest/api/3/search/jql error: {last_error}. "
                f"Legacy /rest/api/3/search error: {fallback_exc}. "
                "For Jira Cloud, use /rest/api/3/search/jql and ensure the user has Browse Projects permission."
            )

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        fields = ",".join(self._issue_fields())
        return self.get(f"/rest/api/3/issue/{issue_key}", params={"fields": fields})

    def get_issue_full_enough(self, issue_key: str) -> dict[str, Any]:
        """Get issue, then return it with the standard testcase-generation fields."""
        return self.get_issue(issue_key)

    def agile_epic_issues(self, epic_key: str, max_results: int = 100) -> list[dict[str, Any]]:
        """Fallback for Jira Software tenants that expose the Agile epic issue endpoint.

        This catches company-managed/classic Jira projects where epic children can be returned
        by the Agile API even when custom Epic Link JQL differs by tenant.
        """
        collected: list[dict[str, Any]] = []
        start_at = 0
        while len(collected) < max_results:
            batch = min(50, max_results - len(collected))
            params = {
                "startAt": start_at,
                "maxResults": batch,
                "fields": ",".join(self._issue_fields()),
            }
            data = self.get(f"/rest/agile/1.0/epic/{epic_key}/issue", params=params)
            values = data.get("issues", []) or []
            collected.extend(values)
            if data.get("isLast") or not values:
                break
            start_at += len(values)
        return collected

    def fetch_epic_with_children(self, epic_key: str, max_results: int = 200) -> dict[str, Any]:
        epic_key = (epic_key or "").strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9]+-\d+$", epic_key):
            raise ValueError("Epic key should look like PROJECT-123")

        epic = self.get_issue(epic_key)
        project_key = epic_key.split("-", 1)[0]

        # For modern Jira Cloud team-managed projects, Child work items are normally fetched by parent.
        # For older company-managed projects, Epic Link/custom field and Agile API may be needed.
        jql_attempts = [
            f'parent = {epic_key} ORDER BY Rank ASC',
            f'project = {project_key} AND parent = {epic_key} ORDER BY Rank ASC',
            f'"Epic Link" = {epic_key} ORDER BY Rank ASC',
            f'cf[10014] = {epic_key} ORDER BY Rank ASC',
            f'issue in linkedIssues({epic_key}) ORDER BY Rank ASC',
        ]

        children: list[dict[str, Any]] = []
        errors: list[str] = []
        attempts: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_issue(issue: dict[str, Any], source: str) -> None:
            key = issue.get("key")
            if not key or key == epic_key or key in seen:
                return
            # Some Jira endpoints return partial issue objects. Fetch full object when fields are thin.
            fields = issue.get("fields") or {}
            if "description" not in fields or "issuetype" not in fields:
                try:
                    issue = self.get_issue_full_enough(key)
                except Exception as exc:
                    errors.append(f"full issue fetch {key} from {source}: {type(exc).__name__}: {exc}")
            children.append(issue)
            seen.add(key)

        for jql in jql_attempts:
            try:
                found = self.search_issues(jql, max_results=max_results)
                attempts.append({"method": "jql", "query": jql, "count": len(found), "ok": True})
                for issue in found:
                    add_issue(issue, source=jql)
            except Exception as exc:
                msg = f"{jql}: {type(exc).__name__}: {exc}"
                attempts.append({"method": "jql", "query": jql, "count": 0, "ok": False, "error": str(exc)[:1200]})
                errors.append(msg)

        # Include explicit subtasks on the epic if present.
        for sub in epic.get("fields", {}).get("subtasks", []) or []:
            key = sub.get("key")
            if key and key not in seen:
                try:
                    add_issue(self.get_issue_full_enough(key), source="epic.subtasks")
                except Exception as exc:
                    errors.append(f"subtask {key}: {type(exc).__name__}: {exc}")

        # Jira Software Agile API fallback is only needed when JQL did not return children.
        # Team-managed/next-gen Jira projects often return HTTP 400 from the Agile epic endpoint even
        # when the correct modern parent JQL has already returned all child work items.  In that case
        # the 400 is not a pipeline error and should not be shown as a red jql_error.
        if children:
            attempts.append({
                "method": "agile_epic_issues",
                "query": f"/rest/agile/1.0/epic/{epic_key}/issue",
                "count": 0,
                "ok": True,
                "skipped": True,
                "reason": "Skipped because parent JQL already returned child work items; avoids false next-gen Agile API warning.",
            })
        else:
            try:
                found = self.agile_epic_issues(epic_key, max_results=max_results)
                attempts.append({"method": "agile_epic_issues", "query": f"/rest/agile/1.0/epic/{epic_key}/issue", "count": len(found), "ok": True})
                for issue in found:
                    add_issue(issue, source="agile_epic_issues")
            except Exception as exc:
                attempts.append({"method": "agile_epic_issues", "query": f"/rest/agile/1.0/epic/{epic_key}/issue", "count": 0, "ok": False, "error": str(exc)[:1200]})
                errors.append(f"agile epic issues: {type(exc).__name__}: {exc}")

        # Keep deterministic ordering by issue number where possible.
        def issue_sort_key(issue: dict[str, Any]) -> tuple[str, int]:
            key = issue.get("key", "")
            m = re.match(r"([A-Z][A-Z0-9]+)-(\d+)", key)
            return (m.group(1), int(m.group(2))) if m else (key, 0)

        children.sort(key=issue_sort_key)
        return {
            "epic": epic,
            "children": children,
            "jql_errors": errors,
            "search_attempts": attempts,
            "count": len(children),
        }


def issue_to_testcase_text(issue: dict[str, Any]) -> str:
    fields = issue.get("fields", {}) or {}
    key = issue.get("key", "UNKNOWN")
    summary = fields.get("summary", "")
    issue_type = (fields.get("issuetype") or {}).get("name", "Issue")
    priority = (fields.get("priority") or {}).get("name", "")
    labels = ", ".join(fields.get("labels") or [])
    description = adf_to_text(fields.get("description"))
    status = (fields.get("status") or {}).get("name", "")
    parent = (fields.get("parent") or {}).get("key", "")
    parts = [
        f"Jira Key: {key}",
        f"Issue Type: {issue_type}",
        f"Parent: {parent}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"Labels: {labels}",
        f"Title: {summary}",
        "Description / Acceptance Criteria:",
        description or "No description found. Generate a smoke testcase from the title only and mark missing details.",
    ]
    return "\n".join(parts).strip()


def epic_to_source_text(epic_bundle: dict[str, Any]) -> str:
    epic = epic_bundle.get("epic", {})
    children = epic_bundle.get("children", []) or []
    blocks = ["# Jira Epic Testcase Generation Source", "", "## Epic", issue_to_testcase_text(epic), ""]
    blocks.append("## Epic Children / Stories / Tasks / Bugs")
    if not children:
        blocks.append("No child issues were returned for this epic. Generate testcase from epic summary/description only.")
    for issue in children:
        blocks.extend(["", "---", issue_to_testcase_text(issue)])
    return "\n".join(blocks).strip() + "\n"


def jira_status(base_url: str = "", username: str = "", api_token: str = "") -> dict[str, Any]:
    try:
        creds = JiraCredentials.from_values(base_url, username, api_token)
        missing = creds.missing()
        if missing:
            return {"ok": False, "missing": missing, "message": "Jira is not configured yet."}
        me = JiraClient(creds).myself()
        return {
            "ok": True,
            "base_url": creds.base_url,
            "account_id": me.get("accountId"),
            "display_name": me.get("displayName"),
            "email_available": bool(me.get("emailAddress")),
            "message": "Jira connection successful.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
