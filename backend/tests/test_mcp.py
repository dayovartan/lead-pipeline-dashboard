import httpx
import pytest
from test_mcp_support import FakeMcp, client_for, company, settings, use_mcp  # noqa: F401

from app.services import mcp as mcp_mod
from app.services.mcp import ALLOWLIST, McpClient, ToolNotAllowed

WRITE_TOOLS = [
    ("cases", "save_case"),
    ("cases", "upsert_case"),
    ("cases", "mark_thread"),
    ("cases", "mark_threads_bulk"),
    ("cases", "save_supplier_item"),
    ("sap", "create_quotation"),
    ("sap", "create_order"),
    ("sap", "update_business_partner"),
    ("cases", "get_customer_card"),  # a sap tool on the wrong server
    ("nope", "case_story"),
]


@pytest.mark.parametrize("server,tool", WRITE_TOOLS)
def test_write_tools_can_never_be_called(server, tool):
    fake = FakeMcp()
    c = client_for(fake)
    with pytest.raises(ToolNotAllowed):
        c.call(server, tool, {})
    assert fake.requests == []  # nothing left the process


def test_write_tools_raise_even_without_token():
    c = McpClient(settings=settings(mcp_token=None))
    with pytest.raises(ToolNotAllowed):
        c.call("cases", "save_case", {})


def test_allowlist_is_exactly_the_read_tools():
    assert ALLOWLIST["cases"] == {
        "customer_timeline", "search_mails", "list_senders", "thread_outline",
        "get_case", "case_story", "latest_supplier_prices",
    }
    assert ALLOWLIST["sap"] == {
        "resolve_customer", "get_customer_card", "find_quotation", "find_order",
        "get_document", "list_documents",
    }
    for names in ALLOWLIST.values():
        assert not any(n.startswith(("save", "upsert", "mark", "create", "update", "delete")) for n in names)


def test_no_token_is_not_available():
    fake = FakeMcp()
    c = McpClient(settings=settings(mcp_token=None), transport=httpx.MockTransport(fake.handler))
    r = c.call("cases", "case_story", {"loop_case_id": "intake-1"})
    assert r == {"available": False, "reason": "no MCP token configured"}
    assert fake.requests == []


def test_call_handshake_bearer_and_raw_block():
    fake = FakeMcp({"case_story": {"loop_case_id": "intake-1", "where": "quoting"}})
    c = client_for(fake)
    r = c.call("cases", "case_story", {"loop_case_id": "intake-1"})
    assert r["available"] is True
    assert r["data"]["where"] == "quoting"
    methods = [q.content for q in fake.requests]
    assert b'"initialize"' in methods[0] and b"notifications/initialized" in methods[1]
    assert all(q.headers["authorization"] == "Bearer test-token" for q in fake.requests)
    assert fake.requests[-1].headers["mcp-session-id"] == "s1"
    assert fake.requests[-1].url.port == 7806  # cases-mcp


def test_sse_answers_and_bare_json_tools():
    fake = FakeMcp({"find_quotation": '{"found": true, "doc": {"doc_num": 301234}}'}, sse=True)
    r = client_for(fake).call("sap", "find_quotation", {"since": "2026-01-01", "case_id": "intake-1"})
    assert r["available"] and r["data"]["doc"]["doc_num"] == 301234
    assert fake.requests[-1].url.port == 7801  # sap-mcp


def test_timeout_is_not_available():
    fake = FakeMcp({"case_story": httpx.ReadTimeout("slow")})
    r = client_for(fake).call("cases", "case_story", {"loop_case_id": "intake-1"})
    assert r["available"] is False and "timed out" in r["reason"]


def test_down_is_not_available():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    c = McpClient(settings=settings(), transport=httpx.MockTransport(refuse))
    r = c.call("sap", "get_customer_card", {"card_code": "C1"})
    assert r["available"] is False and "not reachable" in r["reason"]


def test_http_error_and_tool_error_are_not_available():
    c = McpClient(settings=settings(), transport=httpx.MockTransport(lambda req: httpx.Response(502)))
    assert c.call("sap", "get_customer_card", {"card_code": "C1"})["available"] is False

    fake = FakeMcp({"get_case": {"error_code": "ValidationError", "error_message": "case 'x' not found"}})
    r = client_for(fake).call("cases", "get_case", {"loop_case_id": "x"})
    assert r["available"] is False and "not found" in r["reason"]


def test_cache_ttl():
    now = [1000.0]
    fake = FakeMcp({"case_story": {"where": "x"}})
    c = McpClient(settings=settings(mcp_cache_ttl_s=60), transport=httpx.MockTransport(fake.handler), clock=lambda: now[0])
    c.call("cases", "case_story", {"loop_case_id": "intake-1"})
    c.call("cases", "case_story", {"loop_case_id": "intake-1"})
    assert fake.tool_names() == ["case_story"]
    now[0] += 61
    c.call("cases", "case_story", {"loop_case_id": "intake-1"})
    assert fake.tool_names() == ["case_story", "case_story"]


def test_expired_session_is_renewed():
    fake = FakeMcp({"case_story": {"where": "x"}})
    state = {"first": True}

    def handler(request):
        if b"tools/call" in request.content and state["first"]:
            state["first"] = False
            return httpx.Response(404)
        return fake.handler(request)

    c = McpClient(settings=settings(), transport=httpx.MockTransport(handler))
    assert c.call("cases", "case_story", {"loop_case_id": "intake-1"})["available"] is True


def test_sap_card_endpoint_never_breaks(client, clean, db, use_mcp):  # noqa: F811
    c = company(db, sap_card_code="C100")
    db.commit()
    use_mcp(FakeMcp({"get_customer_card": httpx.ConnectError("down")}))
    r = client.get(f"/api/companies/{c.id}/sap-card")
    assert r.status_code == 200 and r.json()["available"] is False


def test_live_endpoints_without_token(client, clean, db, monkeypatch):
    c = company(db, sap_card_code="C100")
    db.commit()
    monkeypatch.setattr(mcp_mod, "_client", McpClient(settings=settings(mcp_token=None)))
    for path in ("sap-card", "sap-search?q=acme", "supplier-prices"):
        r = client.get(f"/api/companies/{c.id}/{path}")
        assert r.status_code == 200, path
        assert r.json() == {"available": False, "reason": "no MCP token configured"}


def test_live_endpoints_shapes(client, clean, db, use_mcp):  # noqa: F811
    c = company(db, sap_card_code="C100")
    db.commit()
    use_mcp(
        FakeMcp(
            {
                "get_customer_card": {"CardCode": "C100", "CardName": "Acme"},
                "resolve_customer": {"matches": [{"card_code": "C100"}], "more": 0},
                "latest_supplier_prices": {"prices": [{"supplier": "X", "price": 1.5}]},
            }
        )
    )
    card = client.get(f"/api/companies/{c.id}/sap-card").json()
    assert card["available"] and card["card"]["CardName"] == "Acme"
    found = client.get(f"/api/companies/{c.id}/sap-search").json()
    assert found["query"] == "Acme GmbH" and found["matches"][0]["card_code"] == "C100"
    prices = client.get(f"/api/companies/{c.id}/supplier-prices?q=resistor").json()
    assert prices["prices"][0]["price"] == 1.5
