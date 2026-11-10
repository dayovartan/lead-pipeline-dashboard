"""MCP client for cases-mcp and sap-mcp: read tools only (LEADS_PLAN 5, 12).

Speaks MCP streamable HTTP (JSON-RPC 2.0 over POST): `initialize`, the `notifications/initialized`
notification, then `tools/call`. The server may answer with plain JSON or with an SSE stream; both
are handled. The session id the server hands out on `initialize` is reused until it is refused.

Rules:
- Only tool names in ALLOWLIST can be called. Anything else raises ToolNotAllowed before a single
  byte leaves the process, token or not. The token behind settings.mcp_bearer can also write, so
  this list is the only thing keeping Leads read-only on the MCP side.
- No token, MCP down, timeout, protocol error or a tool-level error -> {"available": False,
  "reason": ...}. Callers show "not available" and the page keeps working.
- Successful results are cached in-process for settings.mcp_cache_ttl_s seconds.

The tools return markdown with a "## Raw data" fenced JSON block (dbotOrchestra shared
markdown_response); some sap-mcp tools return bare JSON. `extract_raw` handles both.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings

CASES_READ_TOOLS = frozenset(
    {
        "customer_timeline",
        "search_mails",
        "list_senders",
        "thread_outline",
        "get_case",
        "case_story",
        "latest_supplier_prices",
    }
)
SAP_READ_TOOLS = frozenset(
    {
        "resolve_customer",
        "get_customer_card",
        "find_quotation",
        "find_order",
        "get_document",
        "list_documents",
    }
)
ALLOWLIST: dict[str, frozenset[str]] = {"cases": CASES_READ_TOOLS, "sap": SAP_READ_TOOLS}

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "leads", "version": "0.1.0"}


class ToolNotAllowed(Exception):
    """A tool outside the read allowlist was requested. Never caught by this module."""


class McpUnavailable(Exception):
    """The MCP could not be used: down, timed out, refused, or answered garbage."""


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def check_allowed(server: str, tool: str) -> None:
    allowed = ALLOWLIST.get(server)
    if allowed is None:
        raise ToolNotAllowed(f"unknown MCP server {server!r}")
    if tool not in allowed:
        raise ToolNotAllowed(f"{server}-mcp tool {tool!r} is not on the Leads read allowlist")


# ---- Parsing ---------------------------------------------------------------------------

_RAW_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def extract_raw(text: str) -> Any:
    """The structured part of a tool answer: the last ```json block, or the whole text as JSON."""
    blocks = _RAW_BLOCK.findall(text or "")
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except ValueError:
            continue
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def tool_error(data: Any) -> str | None:
    """cases-mcp failures carry error_code/error_message; sap-mcp ones carry error."""
    if not isinstance(data, dict):
        return None
    if data.get("error_code"):
        return f"{data['error_code']}: {data.get('error_message') or ''}".strip()
    if data.get("error"):
        return str(data["error"])
    return None


def _parse_sse(body: str) -> list[dict]:
    messages, data_lines = [], []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "" and data_lines:
            try:
                messages.append(json.loads("\n".join(data_lines)))
            except ValueError:
                pass
            data_lines = []
    return messages


def _jsonrpc_reply(response: httpx.Response, request_id: int) -> dict:
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        messages = _parse_sse(response.text)
    else:
        try:
            body = response.json()
        except ValueError as e:
            raise McpUnavailable("answer is not JSON") from e
        messages = body if isinstance(body, list) else [body]
    for m in messages:
        if isinstance(m, dict) and m.get("id") == request_id:
            if "error" in m:
                err = m["error"] or {}
                raise McpUnavailable(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
            return m.get("result") or {}
    raise McpUnavailable("no JSON-RPC reply in the answer")


# ---- Client ----------------------------------------------------------------------------


class McpClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings or get_settings()
        self.transport = transport  # tests pass httpx.MockTransport
        self.clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        self._sessions: dict[str, str | None] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def _url(self, server: str) -> str:
        return self.settings.cases_mcp_url if server == "cases" else self.settings.sap_mcp_url

    def _http(self) -> httpx.Client:
        verify: Any = self.settings.mcp_ca_file or True
        return httpx.Client(timeout=self.settings.mcp_timeout_s, verify=verify, transport=self.transport)

    def _request_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _post(self, http: httpx.Client, server: str, token: str, payload: dict, session: str | None):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if session:
            headers["Mcp-Session-Id"] = session
        return http.post(self._url(server), headers=headers, json=payload)

    def _initialize(self, http: httpx.Client, server: str, token: str) -> str | None:
        rid = self._request_id()
        r = self._post(
            http,
            server,
            token,
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "initialize",
                "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
            },
            None,
        )
        if r.status_code != 200:
            raise McpUnavailable(f"initialize answered HTTP {r.status_code}")
        _jsonrpc_reply(r, rid)
        session = r.headers.get("mcp-session-id")
        self._post(http, server, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
        return session

    def _call_tool(self, server: str, tool: str, arguments: dict, token: str) -> dict:
        with self._http() as http:
            for attempt in (1, 2):
                if server not in self._sessions:
                    self._sessions[server] = self._initialize(http, server, token)
                session = self._sessions[server]
                rid = self._request_id()
                r = self._post(
                    http,
                    server,
                    token,
                    {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
                    session,
                )
                if r.status_code in (400, 404) and attempt == 1:
                    # Session expired or unknown: start a new one once.
                    self._sessions.pop(server, None)
                    continue
                if r.status_code in (401, 403):
                    raise McpUnavailable(f"token refused (HTTP {r.status_code})")
                if r.status_code != 200:
                    raise McpUnavailable(f"HTTP {r.status_code}")
                return _jsonrpc_reply(r, rid)
        raise McpUnavailable("session could not be established")

    def call(self, server: str, tool: str, arguments: dict | None = None) -> dict:
        """{available: True, data, text} or {available: False, reason}. Raises ToolNotAllowed."""
        check_allowed(server, tool)
        arguments = {k: v for k, v in (arguments or {}).items() if v is not None}
        token = self.settings.mcp_bearer
        if not token:
            return unavailable("no MCP token configured")

        key = json.dumps([server, tool, arguments], sort_keys=True, default=str)
        now = self.clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

        try:
            result = self._call_tool(server, tool, arguments, token)
        except httpx.TimeoutException:
            self._sessions.pop(server, None)
            return unavailable(f"{server}-mcp timed out")
        except httpx.HTTPError as e:
            self._sessions.pop(server, None)
            return unavailable(f"{server}-mcp not reachable ({type(e).__name__})")
        except McpUnavailable as e:
            return unavailable(f"{server}-mcp: {e}")

        text = "\n".join(
            c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"
        )
        data = extract_raw(text)
        if data is None and isinstance(result.get("structuredContent"), dict):
            sc = result["structuredContent"]
            data = extract_raw(sc["result"]) if isinstance(sc.get("result"), str) else sc
        if result.get("isError"):
            return unavailable(f"{tool}: {text.strip()[:300] or 'tool error'}")
        err = tool_error(data)
        if err:
            return unavailable(f"{tool}: {err}")

        out = {"available": True, "data": data, "text": text}
        self._cache[key] = (now + self.settings.mcp_cache_ttl_s, out)
        return out


_client: McpClient | None = None


def get_mcp() -> McpClient:
    """FastAPI dependency. Tests override it with a client on an httpx.MockTransport."""
    global _client
    if _client is None:
        _client = McpClient()
    return _client
