"""Shared helpers for the companies/leads/meetings/search/MCP tests: data factories written
straight through the models (the importer is built elsewhere) and a fake MCP server on
httpx.MockTransport. Never talks to the real MCPs."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.models import Company, Contact, Convention, ConventionAppearance, Lead
from app.services.mcp import McpClient, extract_raw

VIEWER = {"x-forwarded-email": "viewer@dayo-tech.com", "x-forwarded-groups": "leads_viewer"}
EDITOR = {"x-forwarded-email": "ed@dayo-tech.com", "x-forwarded-groups": "leads_editor"}


# ---- Factories -----------------------------------------------------------------------------


def convention(db, slug="electronica-2026", name="electronica 2026", starts_on=date(2026, 11, 10)):
    c = Convention(slug=slug, name=name, starts_on=starts_on)
    db.add(c)
    db.flush()
    return c


def company(db, name="Acme GmbH", **kw):
    kw.setdefault("name_normalized", name.lower().replace(" gmbh", "").strip())
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def appearance(db, comp, conv, role=None, **kw):
    a = ConventionAppearance(company_id=comp.id, convention_id=conv.id, role=role, **kw)
    db.add(a)
    db.flush()
    return a


def contact(db, comp, name="Ann Example", email=None, **kw):
    c = Contact(company_id=comp.id, name=name, email=email, **kw)
    db.add(c)
    db.flush()
    return c


def lead(db, comp, **kw):
    lead = Lead(company_id=comp.id, **kw)
    db.add(lead)
    db.flush()
    return lead


# ---- Fake MCP ------------------------------------------------------------------------------


def as_markdown(raw: dict) -> str:
    """What dbotOrchestra's shared markdown_response produces."""
    return f"# Title\n\n## Briefing\nok\n\n## Raw data\n```json\n{json.dumps(raw, indent=2)}\n```"


class FakeMcp:
    """A JSON-RPC MCP on httpx.MockTransport. `tools` maps tool name -> dict | callable(args) | Exception."""

    def __init__(self, tools: dict | None = None, sse: bool = False):
        self.tools = tools or {}
        self.sse = sse
        self.calls: list[tuple[str, str, dict]] = []  # (host:port, tool, args)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            return self._reply(body["id"], {"protocolVersion": "2025-03-26", "capabilities": {}}, {"mcp-session-id": "s1"})
        if method and method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "tools/call":
            name = body["params"]["name"]
            args = body["params"].get("arguments") or {}
            self.calls.append((request.url.port, name, args))
            spec = self.tools.get(name, {})
            if isinstance(spec, Exception):
                raise spec
            raw = spec(args) if callable(spec) else spec
            text = raw if isinstance(raw, str) else as_markdown(raw)
            return self._reply(body["id"], {"content": [{"type": "text", "text": text}], "isError": False})
        return httpx.Response(400)

    def _reply(self, rid, result, headers=None):
        msg = {"jsonrpc": "2.0", "id": rid, "result": result}
        if self.sse:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream", **(headers or {})},
                text=f"event: message\ndata: {json.dumps(msg)}\n\n",
            )
        return httpx.Response(200, headers=headers or {}, json=msg)

    def tool_names(self) -> list[str]:
        return [t for _, t, _ in self.calls]


def settings(**kw) -> Settings:
    kw.setdefault("mcp_token", "test-token")
    return Settings(mcp_token_file=None, **kw)


def client_for(fake: FakeMcp, **kw) -> McpClient:
    return McpClient(settings=settings(**kw), transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def use_mcp():
    """Install an McpClient on a FakeMcp as the app's MCP dependency."""
    from app.main import app
    from app.services.mcp import get_mcp

    def install(fake: FakeMcp, **kw) -> McpClient:
        c = client_for(fake, **kw)
        app.dependency_overrides[get_mcp] = lambda: c
        return c

    yield install
    app.dependency_overrides.pop(get_mcp, None)


def test_fake_renders_like_the_real_tools():
    assert extract_raw(as_markdown({"a": [1]})) == {"a": [1]}
