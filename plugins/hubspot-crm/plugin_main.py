"""Search, read, and manage HubSpot CRM records from Row-Bot.

Read tools (search / list / detail) are safe and run without approval.
Write tools (create / update / delete / log) mutate HubSpot data and are
declared destructive, so Row-Bot's approval gate asks the user to confirm
before they run.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from plugins.api import PluginTool

_API_BASE = "https://api.hubapi.com"
_REQUEST_TIMEOUT = 15
_USER_AGENT = "Row-Bot-HubSpot-CRM-Plugin/0.2"

_NO_TOKEN_MSG = (
    "HubSpot access token is not configured. Add a HubSpot Private App token "
    "in Plugin Center before using this tool."
)

# Singular command word -> plural CRM object type used in API paths.
_OBJECT_TYPES = {
    "contact": "contacts",
    "company": "companies",
    "deal": "deals",
    "ticket": "tickets",
}

# Properties requested per object type on reads. Kept minimal and non-sensitive.
_OBJECT_PROPS: dict[str, list[str]] = {
    "contacts": ["firstname", "lastname", "email", "phone", "company", "jobtitle", "lifecyclestage"],
    "companies": ["name", "domain", "industry", "city", "state", "numberofemployees"],
    "deals": ["dealname", "amount", "dealstage", "pipeline", "closedate"],
    "tickets": ["subject", "hs_pipeline_stage", "hs_ticket_priority", "createdate"],
}

_SEARCH_ACTIONS = {
    "search_contacts": "contacts",
    "search_companies": "companies",
    "search_deals": "deals",
    "search_tickets": "tickets",
}

_DETAIL_ACTIONS = {
    "contact": "contacts",
    "company": "companies",
    "deal": "deals",
    "ticket": "tickets",
}

_HELP_TEXT = (
    "HubSpot CRM (read). Commands:\n"
    "  search_contacts <query> [count]\n"
    "  search_companies <query> [count]\n"
    "  search_deals <query> [count]\n"
    "  search_tickets <query> [count]\n"
    "  list_deals [count]            - list deals and summarize the pipeline\n"
    "  contact <id> | company <id> | deal <id> | ticket <id>\n"
    "A bare query without a command searches contacts."
)


# ── Small pure helpers ───────────────────────────────────────────────────────
def _parse_int(value: str, default: int) -> int:
    value = (value or "").strip()
    if value.isdigit():
        return max(1, min(int(value), 30))
    return default


def _split_trailing_count(text: str, default_count: int) -> tuple[str, int]:
    """Split a trailing integer count off a query string."""
    tokens = (text or "").rsplit(None, 1)
    if len(tokens) == 2 and tokens[1].isdigit():
        return tokens[0].strip(), _parse_int(tokens[1], default_count)
    return (text or "").strip(), default_count


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _bad_object_message(word: str) -> str:
    return f"Unknown object type '{word}'. Use one of: contact, company, deal, ticket."


def _tokenize_kv(text: str) -> list[str]:
    """Split on whitespace while keeping quoted spans together."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in text or "":
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_properties(text: str) -> dict[str, str]:
    """Parse 'key=value key2="quoted value"' into a properties dict."""
    props: dict[str, str] = {}
    for token in _tokenize_kv(text):
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            props[key] = value
    return props


# ── Read: parsing ────────────────────────────────────────────────────────────
def _parse_query(query: str, default_count: int) -> tuple[str, dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return "help", {}

    parts = query.split(None, 1)
    action = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if action in _SEARCH_ACTIONS:
        if not rest:
            return "error", {"message": f"Please provide a search query. Usage: {action} <query>"}
        text, count = _split_trailing_count(rest, default_count)
        return "search", {"object_type": _SEARCH_ACTIONS[action], "query": text, "count": count}

    if action == "list_deals":
        count = _parse_int(rest, default_count) if rest else default_count
        return "list_deals", {"count": count}

    if action in _DETAIL_ACTIONS:
        if not rest:
            return "error", {"message": f"Please provide an id. Usage: {action} <id>"}
        return "detail", {"object_type": _DETAIL_ACTIONS[action], "record_id": rest.split()[0]}

    if action in ("help", "commands", "?"):
        return "help", {}

    text, count = _split_trailing_count(query, default_count)
    return "search", {"object_type": "contacts", "query": text, "count": count}


# ── Read: formatting ─────────────────────────────────────────────────────────
def _format_amount(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return f"{int(num):,}"
    return f"{num:,.2f}"


def _format_contact(result: dict[str, Any], index: int | None = None) -> str:
    props = result.get("properties") or {}
    first = (props.get("firstname") or "").strip()
    last = (props.get("lastname") or "").strip()
    name = (first + " " + last).strip() or (props.get("email") or "").strip() or "Unknown contact"
    prefix = f"[{index}] " if index is not None else ""
    lines = [f"{prefix}**{name}**  (id: {result.get('id', '')})"]
    if props.get("email"):
        lines.append(f"   Email: {props['email']}")
    if props.get("phone"):
        lines.append(f"   Phone: {props['phone']}")
    role = [b for b in [props.get("jobtitle"), props.get("company")] if b]
    if role:
        lines.append("   " + " @ ".join(role))
    if props.get("lifecyclestage"):
        lines.append(f"   Lifecycle: {props['lifecyclestage']}")
    return "\n".join(lines)


def _format_company(result: dict[str, Any], index: int | None = None) -> str:
    props = result.get("properties") or {}
    name = (props.get("name") or "").strip() or "Unknown company"
    prefix = f"[{index}] " if index is not None else ""
    lines = [f"{prefix}**{name}**  (id: {result.get('id', '')})"]
    if props.get("domain"):
        lines.append(f"   Domain: {props['domain']}")
    if props.get("industry"):
        lines.append(f"   Industry: {props['industry']}")
    location = [b for b in [props.get("city"), props.get("state")] if b]
    if location:
        lines.append("   Location: " + ", ".join(location))
    if props.get("numberofemployees"):
        lines.append(f"   Employees: {props['numberofemployees']}")
    return "\n".join(lines)


def _format_deal(result: dict[str, Any], index: int | None = None) -> str:
    props = result.get("properties") or {}
    dealname = (props.get("dealname") or "").strip() or "Untitled deal"
    prefix = f"[{index}] " if index is not None else ""
    lines = [f"{prefix}**{dealname}**  (id: {result.get('id', '')})"]
    if props.get("amount"):
        lines.append(f"   Amount: {_format_amount(props['amount'])}")
    if props.get("dealstage"):
        lines.append(f"   Stage: {props['dealstage']}")
    if props.get("closedate"):
        lines.append(f"   Close date: {props['closedate']}")
    return "\n".join(lines)


def _format_ticket(result: dict[str, Any], index: int | None = None) -> str:
    props = result.get("properties") or {}
    subject = (props.get("subject") or "").strip() or "Untitled ticket"
    prefix = f"[{index}] " if index is not None else ""
    lines = [f"{prefix}**{subject}**  (id: {result.get('id', '')})"]
    if props.get("hs_pipeline_stage"):
        lines.append(f"   Stage: {props['hs_pipeline_stage']}")
    if props.get("hs_ticket_priority"):
        lines.append(f"   Priority: {props['hs_ticket_priority']}")
    if props.get("createdate"):
        lines.append(f"   Created: {props['createdate']}")
    return "\n".join(lines)


_FORMATTERS = {
    "contacts": _format_contact,
    "companies": _format_company,
    "deals": _format_deal,
    "tickets": _format_ticket,
}


def _summarize_pipeline(deals: list[dict[str, Any]]) -> str:
    stage_counts: dict[str, int] = {}
    stage_totals: dict[str, float] = {}
    grand_total = 0.0
    for deal in deals:
        props = deal.get("properties") or {}
        stage = (props.get("dealstage") or "unknown").strip() or "unknown"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        try:
            value = float(props.get("amount"))
        except (TypeError, ValueError):
            value = 0.0
        stage_totals[stage] = stage_totals.get(stage, 0.0) + value
        grand_total += value
    lines = ["**Pipeline summary**"]
    for stage in sorted(stage_counts):
        lines.append(
            f"   {stage}: {stage_counts[stage]} deal(s), {_format_amount(stage_totals[stage])}"
        )
    lines.append(f"   Total: {len(deals)} deal(s), {_format_amount(grand_total)}")
    return "\n".join(lines)


# ── Network layer ────────────────────────────────────────────────────────────
def _api_request(
    method: str,
    path: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    url = _API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
    if not raw:
        return {}
    return json.loads(raw)


def _search_objects(object_type: str, query: str, count: int, token: str) -> tuple[list[dict], int]:
    body = {"query": query, "limit": count, "properties": _OBJECT_PROPS[object_type]}
    data = _api_request("POST", f"/crm/v3/objects/{object_type}/search", token, body=body)
    if not isinstance(data, dict):
        return [], 0
    results = [r for r in data.get("results", []) if isinstance(r, dict)]
    total = data.get("total", len(results))
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(results)
    return results, total


def _list_deal_records(count: int, token: str) -> list[dict[str, Any]]:
    params = {
        "limit": count,
        "properties": ",".join(_OBJECT_PROPS["deals"]),
        "archived": "false",
    }
    data = _api_request("GET", "/crm/v3/objects/deals", token, params=params)
    if not isinstance(data, dict):
        return []
    return [r for r in data.get("results", []) if isinstance(r, dict)]


def _get_record(object_type: str, record_id: str, token: str) -> dict[str, Any] | None:
    params = {"properties": ",".join(_OBJECT_PROPS[object_type])}
    data = _api_request("GET", f"/crm/v3/objects/{object_type}/{record_id}", token, params=params)
    return data if isinstance(data, dict) else None


# ── Read: runners ────────────────────────────────────────────────────────────
def _run_search(object_type: str, query: str, count: int, token: str) -> str:
    if not query:
        return "Please provide a search query."
    results, total = _search_objects(object_type, query, count, token)
    if not results:
        return f"No {object_type} found for: {query}"
    formatter = _FORMATTERS[object_type]
    header = f"Found {total} {object_type} (showing {len(results)}):"
    body = "\n\n".join(formatter(r, index=i) for i, r in enumerate(results, 1))
    return f"{header}\n\n{body}"


def _run_list_deals(count: int, token: str) -> str:
    deals = _list_deal_records(count, token)
    if not deals:
        return "No deals found."
    summary = _summarize_pipeline(deals)
    body = "\n\n".join(_format_deal(d, index=i) for i, d in enumerate(deals, 1))
    return f"{summary}\n\n{body}"


def _run_detail(object_type: str, record_id: str, token: str) -> str:
    record = _get_record(object_type, record_id, token)
    if not record or not record.get("id"):
        return f"Could not find {object_type[:-1]} with id {record_id}."
    return _FORMATTERS[object_type](record)


# ── Write: parsing ───────────────────────────────────────────────────────────
def _parse_object_and_props(query: str) -> tuple[str | None, dict[str, str]]:
    query = (query or "").strip()
    if not query:
        return None, {}
    parts = query.split(None, 1)
    return parts[0].lower(), _parse_properties(parts[1] if len(parts) > 1 else "")


def _parse_object_id_props(query: str) -> tuple[str | None, str | None, dict[str, str]]:
    parts = (query or "").split(None, 2)
    if len(parts) < 2:
        return None, None, {}
    obj = parts[0].lower()
    record_id = parts[1]
    return obj, record_id, _parse_properties(parts[2] if len(parts) > 2 else "")


def _parse_engagement(query: str) -> tuple[str, str, str, str] | None:
    parts = (query or "").split(None, 3)
    if len(parts) < 4:
        return None
    return parts[0].lower(), parts[1].lower(), parts[2], parts[3]


# ── Write: runners ───────────────────────────────────────────────────────────
def _run_create(object_word: str | None, props: dict[str, str], token: str) -> str:
    plural = _OBJECT_TYPES.get(object_word or "")
    if not plural:
        return _bad_object_message(object_word or "")
    if not props:
        return "Please provide at least one property. Usage: <object_type> key=value ..."
    data = _api_request("POST", f"/crm/v3/objects/{plural}", token, body={"properties": props})
    new_id = data.get("id") if isinstance(data, dict) else None
    if not new_id:
        return "HubSpot did not return a new record id."
    return f"Created {object_word} (id: {new_id})."


def _run_update(object_word: str | None, record_id: str | None, props: dict[str, str], token: str) -> str:
    plural = _OBJECT_TYPES.get(object_word or "")
    if not plural:
        return _bad_object_message(object_word or "")
    if not record_id:
        return "Please provide a record id. Usage: <object_type> <id> key=value ..."
    if not props:
        return "Please provide at least one property to update. Usage: <object_type> <id> key=value ..."
    _api_request("PATCH", f"/crm/v3/objects/{plural}/{record_id}", token, body={"properties": props})
    return f"Updated {object_word} {record_id} ({', '.join(sorted(props))})."


def _run_delete(object_word: str | None, record_id: str | None, token: str) -> str:
    plural = _OBJECT_TYPES.get(object_word or "")
    if not plural:
        return _bad_object_message(object_word or "")
    if not record_id:
        return "Please provide a record id. Usage: <object_type> <id>"
    _api_request("DELETE", f"/crm/v3/objects/{plural}/{record_id}", token)
    return f"Archived {object_word} {record_id} in HubSpot (soft delete)."


def _run_log_engagement(kind: str, object_word: str, record_id: str, text: str, token: str) -> str:
    plural = _OBJECT_TYPES.get(object_word)
    if not plural:
        return _bad_object_message(object_word)
    if kind == "note":
        engagement = "notes"
        props: dict[str, Any] = {"hs_timestamp": _now_ms(), "hs_note_body": text}
    elif kind == "task":
        engagement = "tasks"
        props = {
            "hs_timestamp": _now_ms(),
            "hs_task_subject": text[:200],
            "hs_task_body": text,
            "hs_task_status": "NOT_STARTED",
            "hs_task_type": "TODO",
        }
    else:
        return "First word must be 'note' or 'task'. Usage: <note|task> <object_type> <id> <text>"

    created = _api_request("POST", f"/crm/v3/objects/{engagement}", token, body={"properties": props})
    engagement_id = created.get("id") if isinstance(created, dict) else None
    if not engagement_id:
        return "HubSpot did not return an engagement id."
    # Associate to the target record using HubSpot's default association type.
    _api_request(
        "PUT",
        f"/crm/v3/objects/{engagement}/{engagement_id}/associations/default/{plural}/{record_id}",
        token,
    )
    return f"Logged {kind} on {object_word} {record_id} (id: {engagement_id})."


def _format_http_error(exc: urllib.error.HTTPError) -> str:
    code = getattr(exc, "code", None)
    if code == 401:
        return "HubSpot rejected the token (401 Unauthorized). Check the Private App access token."
    if code == 403:
        return (
            "HubSpot denied access (403 Forbidden). The Private App may be missing a required "
            "scope. Reads need *.read scopes; writes need the matching *.write scopes."
        )
    if code == 404:
        return "Record not found in HubSpot (404)."
    if code == 409:
        return "HubSpot reported a conflict (409). The record may already exist."
    if code == 429:
        return "HubSpot rate limit reached (429). Please wait a moment and try again."
    return f"HubSpot API error (HTTP {code})."


# ── Tools ────────────────────────────────────────────────────────────────────
class _HubSpotTool(PluginTool):
    """Shared token handling and error wrapping for all HubSpot tools."""

    def _run_guarded(self, fn: Callable[[str], str]) -> str:
        token = self.plugin_api.get_secret("access_token")
        if not token:
            return _NO_TOKEN_MSG
        try:
            return fn(token)
        except urllib.error.HTTPError as exc:
            return _format_http_error(exc)
        except urllib.error.URLError as exc:
            return f"Network error accessing HubSpot: {exc.reason}"
        except Exception as exc:
            return f"Error accessing HubSpot: {exc}"


class HubSpotCRMTool(_HubSpotTool):
    @property
    def name(self) -> str:
        return "hubspot_crm"

    @property
    def display_name(self) -> str:
        return "HubSpot CRM"

    @property
    def description(self) -> str:
        return (
            "Search and read HubSpot CRM records (read-only, no approval needed). Commands: "
            "search_contacts <query> [count], search_companies <query> [count], "
            "search_deals <query> [count], search_tickets <query> [count], "
            "list_deals [count], contact <id>, company <id>, deal <id>, ticket <id>. "
            "A bare query searches contacts."
        )

    def _default_count(self) -> int:
        raw = self.plugin_api.get_config("default_count", 10)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 10
        return max(1, min(value, 30))

    def execute(self, query: str) -> str:
        action, params = _parse_query(query, self._default_count())
        if action == "help":
            return _HELP_TEXT
        if action == "error":
            return params["message"]

        def _do(token: str) -> str:
            if action == "search":
                return _run_search(params["object_type"], params["query"], params["count"], token)
            if action == "list_deals":
                return _run_list_deals(params["count"], token)
            if action == "detail":
                return _run_detail(params["object_type"], params["record_id"], token)
            return f"Unknown command: {action}"

        return self._run_guarded(_do)


class HubSpotCreateRecordTool(_HubSpotTool):
    @property
    def name(self) -> str:
        return "hubspot_create_record"

    @property
    def display_name(self) -> str:
        return "HubSpot Create Record"

    @property
    def description(self) -> str:
        return (
            "Create a HubSpot record. Requires user approval before it runs. "
            "Usage: <contact|company|deal|ticket> key=value key2=\"value with spaces\". "
            "Example: contact email=jane@acme.com firstname=Jane lastname=Doe. "
            "Example: deal dealname=\"Acme renewal\" amount=15000 dealstage=qualified."
        )

    @property
    def destructive_tool_names(self) -> set[str]:
        return {"hubspot_create_record"}

    def execute(self, query: str) -> str:
        object_word, props = _parse_object_and_props(query)
        return self._run_guarded(lambda token: _run_create(object_word, props, token))


class HubSpotUpdateRecordTool(_HubSpotTool):
    @property
    def name(self) -> str:
        return "hubspot_update_record"

    @property
    def display_name(self) -> str:
        return "HubSpot Update Record"

    @property
    def description(self) -> str:
        return (
            "Update fields on a HubSpot record. Requires user approval before it runs. "
            "Usage: <contact|company|deal|ticket> <id> key=value key2=\"value\". "
            "Example: deal 12045 dealstage=closedwon amount=20000."
        )

    @property
    def destructive_tool_names(self) -> set[str]:
        return {"hubspot_update_record"}

    def execute(self, query: str) -> str:
        object_word, record_id, props = _parse_object_id_props(query)
        return self._run_guarded(lambda token: _run_update(object_word, record_id, props, token))


class HubSpotDeleteRecordTool(_HubSpotTool):
    @property
    def name(self) -> str:
        return "hubspot_delete_record"

    @property
    def display_name(self) -> str:
        return "HubSpot Delete Record"

    @property
    def description(self) -> str:
        return (
            "Delete (archive) a HubSpot record. Requires user approval before it runs. "
            "Usage: <contact|company|deal|ticket> <id>. Example: contact 501."
        )

    @property
    def destructive_tool_names(self) -> set[str]:
        return {"hubspot_delete_record"}

    def execute(self, query: str) -> str:
        object_word, record_id, _ = _parse_object_id_props(query)
        return self._run_guarded(lambda token: _run_delete(object_word, record_id, token))


class HubSpotLogEngagementTool(_HubSpotTool):
    @property
    def name(self) -> str:
        return "hubspot_log_engagement"

    @property
    def display_name(self) -> str:
        return "HubSpot Log Note/Task"

    @property
    def description(self) -> str:
        return (
            "Log a note or task against a HubSpot record. Requires user approval before it runs. "
            "Usage: <note|task> <contact|company|deal|ticket> <id> <text>. "
            "Example: note deal 12045 Spoke with the client, renewal confirmed."
        )

    @property
    def destructive_tool_names(self) -> set[str]:
        return {"hubspot_log_engagement"}

    def execute(self, query: str) -> str:
        parsed = _parse_engagement(query)
        if parsed is None:
            return "Usage: <note|task> <contact|company|deal|ticket> <id> <text>"
        kind, object_word, record_id, text = parsed
        return self._run_guarded(
            lambda token: _run_log_engagement(kind, object_word, record_id, text, token)
        )


def register(api):
    api.register_tool(HubSpotCRMTool(api))
    api.register_tool(HubSpotCreateRecordTool(api))
    api.register_tool(HubSpotUpdateRecordTool(api))
    api.register_tool(HubSpotDeleteRecordTool(api))
    api.register_tool(HubSpotLogEngagementTool(api))
