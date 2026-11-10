"""Case suggestions: CardCode, then contact email, then domain; exclusions; dismissed never return."""

from test_mcp_support import FakeMcp, client_for, company, contact, lead, use_mcp  # noqa: F401

from app.models import CaseSuggestion, Lead, LeadActivity, LeadCase
from app.services import matching


def _tools(**over):
    """A cases-mcp where every lookup finds something, keyed by conversation."""
    outlines = {
        "conv-email": {"conversation_id": "conv-email", "cases": [{"case_id": "uuid-1", "loop_case_id": "intake-email"}]},
        "conv-domain": {"conversation_id": "conv-domain", "cases": [{"loop_case_id": "intake-domain"}]},
        "conv-dup": {"cases": [{"loop_case_id": "intake-card"}]},
    }
    tools = {
        "customer_timeline": {"card_code": "C1", "cases": [{"case_id": "u", "loop_case_id": "intake-card", "rows": []}]},
        "search_mails": lambda a: {
            "mails": (
                [{"conversation_id": "conv-email", "from_addr": "ann@acme.de"},
                 {"conversation_id": "conv-dup", "from_addr": "ann@acme.de"}]
                if a["sender"] == "ann@acme.de"
                else [{"conversation_id": "conv-domain", "from_addr": "bob@acme.de"},
                      {"conversation_id": "conv-other", "from_addr": "x@acme.de.evil.cn"}]
            )
        },
        "list_senders": {"total": 1, "senders": [{"from_addr": "bob@acme.de"}]},
        "thread_outline": lambda a: outlines.get(a["conversation_id"], {"cases": []}),
    }
    tools.update(over)
    return tools


def _setup(db, **company_kw):
    company_kw.setdefault("sap_card_code", "C1")
    company_kw.setdefault("domain", "acme.de")
    c = company(db, **company_kw)
    ct = contact(db, c, email="Ann@Acme.de")
    lid = lead(db, c, contact_id=ct.id).id
    db.commit()
    return c, lid


def test_order_and_reasons(client, clean, db, use_mcp):  # noqa: F811
    _, lid = _setup(db)
    fake = FakeMcp(_tools())
    use_mcp(fake)
    r = client.get(f"/api/leads/{lid}/suggestions").json()
    assert r["available"] is True
    assert [(s["loop_case_id"], s["reason"]) for s in r["items"]] == [
        ("intake-card", "card_code"),
        ("intake-email", "contact_email"),
        ("intake-domain", "domain"),
    ]
    names = fake.tool_names()
    assert names[0] == "customer_timeline"
    assert names.index("list_senders") > names.index("thread_outline")  # domain after email
    # the outline of conv-email is fetched once even though it could come up twice
    assert [a for _, t, a in fake.calls if t == "search_mails"][0]["sender"] == "ann@acme.de"
    assert fake.calls[-1][2] == {"conversation_id": "conv-domain"}  # not the look-alike domain
    assert client.get(f"/api/leads/{lid}").json()["pending_suggestion_count"] == 3


def test_free_mail_domain_skipped_but_exact_email_matches(clean, db):
    c = company(db, domain="gmail.com")
    contact(db, c, email="ann@acme.de")
    db.commit()
    fake = FakeMcp(_tools())
    res = matching.find_cases(client_for(fake), c, ["ann@acme.de"])
    assert "list_senders" not in fake.tool_names()
    assert [cid for cid, _ in res.found] == ["intake-email", "intake-card"]
    assert {r for _, r in res.found} == {"contact_email"}


def test_own_domain_never_matches(clean, db):
    c = company(db, domain="dayo-tech.com")
    contact(db, c, email="vartan@dayo-tech.com")
    lid = lead(db, c).id
    db.commit()
    assert matching.lead_emails(db, db.get(Lead, lid)) == []
    fake = FakeMcp(_tools())
    matching.find_cases(client_for(fake), c, [])
    assert fake.tool_names() == []


def test_primary_email_domain_used_when_no_domain(clean, db):
    c = company(db, primary_email="info@acme.de")
    db.commit()
    fake = FakeMcp(_tools())
    res = matching.find_cases(client_for(fake), c, [])
    assert ("intake-domain", "domain") in res.found


def test_linked_skipped_and_dismissed_never_return(client, clean, db, use_mcp):  # noqa: F811
    _, lid = _setup(db)
    db.add(LeadCase(lead_id=lid, loop_case_id="intake-card", how="manual"))
    db.commit()
    use_mcp(FakeMcp(_tools()))
    items = client.get(f"/api/leads/{lid}/suggestions").json()["items"]
    assert [s["loop_case_id"] for s in items] == ["intake-email", "intake-domain"]

    sid = items[0]["id"]
    r = client.post(f"/api/leads/{lid}/suggestions/{sid}/dismiss")
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    again = client.get(f"/api/leads/{lid}/suggestions").json()["items"]
    assert [s["loop_case_id"] for s in again] == ["intake-domain"]
    db.expire_all()
    assert db.query(CaseSuggestion).filter_by(lead_id=lid, loop_case_id="intake-email").one().status == "dismissed"
    assert client.post(f"/api/leads/{lid}/suggestions/{sid}/accept").status_code == 409


def test_accept_links_as_suggested(client, clean, db, use_mcp):  # noqa: F811
    _, lid = _setup(db)
    use_mcp(FakeMcp(_tools()))
    sid = client.get(f"/api/leads/{lid}/suggestions").json()["items"][0]["id"]
    r = client.post(f"/api/leads/{lid}/suggestions/{sid}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    db.expire_all()
    link = db.query(LeadCase).filter_by(lead_id=lid).one()
    assert link.loop_case_id == "intake-card" and link.how == "suggested" and link.linked_by == "tester@dayo-tech.com"
    kinds = [a.kind for a in db.query(LeadActivity).filter_by(lead_id=lid)]
    assert kinds == ["suggestion_accepted"]
    left = client.get(f"/api/leads/{lid}/suggestions").json()["items"]
    assert "intake-card" not in [s["loop_case_id"] for s in left]


def test_nothing_links_automatically(client, clean, db, use_mcp):  # noqa: F811
    _, lid = _setup(db)
    use_mcp(FakeMcp(_tools()))
    client.get(f"/api/leads/{lid}/suggestions")
    db.expire_all()
    assert db.query(LeadCase).count() == 0


def test_mcp_down_suggestions_not_available(client, clean, db, use_mcp):  # noqa: F811
    import httpx

    _, lid = _setup(db)
    boom = httpx.ConnectError("down")
    use_mcp(FakeMcp({t: boom for t in ("customer_timeline", "search_mails", "list_senders", "thread_outline")}))
    r = client.get(f"/api/leads/{lid}/suggestions")
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["items"] == [] and "not reachable" in r.json()["reason"]


def test_parsers_are_defensive():
    assert matching.intake_ids({"cases": [{"case_id": "8f1e-uuid"}]}) == []  # today's uuid case_id: no match
    assert matching.intake_ids([{"id": "intake-1"}, {"nested": {"case_id": "intake-2"}}, {"id": "intake-1"}]) == [
        "intake-1",
        "intake-2",
    ]
    assert matching.case_ids_from_timeline(None) == []
    assert matching.conversations_from_mails({"mails": "garbage"}, lambda s: True) == []
    assert matching.senders_from(None) == []
