from datetime import date, timedelta

import httpx
from test_mcp_support import VIEWER, FakeMcp, appearance, company, contact, convention, lead, use_mcp  # noqa: F401

from app.models import LeadActivity, LeadCase


def _activity(db, lead_id):
    db.expire_all()
    return [(a.kind, a.actor) for a in db.query(LeadActivity).filter_by(lead_id=lead_id).order_by(LeadActivity.id)]


def test_follow_creates_lead_every_time(client, clean, db):
    show = convention(db)
    c = company(db)
    ap = appearance(db, c, show, role="lead")
    ct = contact(db, c, email="ann@acme.de")
    db.commit()
    body = {"owner": "vartan", "contact_id": ct.id, "appearance_id": ap.id, "notes": "hot"}
    r = client.post(f"/api/companies/{c.id}/leads", json=body)
    assert r.status_code == 201
    first = r.json()
    assert first["status"] == "new" and first["owner"] == "vartan"
    assert first["company"] == {"id": c.id, "name": "Acme GmbH"}
    assert first["contact"] == {"id": ct.id, "name": "Ann Example", "email": "ann@acme.de"}
    assert first["convention_slug"] == "electronica-2026"
    assert first["linked_case_count"] == 0 and first["overdue"] is False
    # No uniqueness rule: following again makes a second lead.
    second = client.post(f"/api/companies/{c.id}/leads", json={}).json()
    assert second["id"] != first["id"]
    assert _activity(db, first["id"]) == [("opened", "tester@dayo-tech.com")]


def test_follow_rejects_foreign_contact(client, clean, db):
    a, b = company(db), company(db, name="Other", name_normalized="other")
    ct = contact(db, b, email="x@other.com")
    db.commit()
    assert client.post(f"/api/companies/{a.id}/leads", json={"contact_id": ct.id}).status_code == 422
    assert client.post("/api/companies/999999/leads", json={}).status_code == 404


def test_board_filters_and_overdue_sort(client, clean, db):
    show = convention(db)
    other_show = convention(db, slug="embedded-2027", name="embedded world")
    today = date.today()
    a = company(db, name="Alpha", name_normalized="alpha")
    b = company(db, name="Bravo", name_normalized="bravo")
    c = company(db, name="Charlie", name_normalized="charlie")
    appearance(db, a, show)
    appearance(db, b, show)
    appearance(db, c, other_show)
    late = lead(db, a, owner="Vartan", status="follow_up", follow_up_on=today - timedelta(days=3))
    soon = lead(db, b, owner="yossi", status="talking", follow_up_on=today + timedelta(days=2))
    undated = lead(db, a, owner="vartan", status="new")
    parked = lead(db, c, owner="vartan", status="parked", follow_up_on=today - timedelta(days=10))
    db.commit()

    def ids(qs=""):
        return [i["id"] for i in client.get(f"/api/leads?{qs}").json()["items"]]

    # Parked hidden by default; follow_up_on ascending, nulls last -> overdue first.
    assert ids() == [late.id, soon.id, undated.id]
    items = client.get("/api/leads").json()["items"]
    assert [i["overdue"] for i in items] == [True, False, False]
    assert ids("include_parked=true") == [parked.id, late.id, soon.id, undated.id]
    assert ids("status=parked") == [parked.id]
    assert ids("status=new,talking") == [soon.id, undated.id]
    assert ids("owner=vartan") == [late.id, undated.id]  # case-insensitive
    assert ids("convention=embedded-2027&include_parked=true") == [parked.id]
    assert ids("q=bravo") == [soon.id]
    assert client.get("/api/leads?status=won").status_code == 422
    r = client.get("/api/leads?page_size=1&page=2").json()
    assert r["total"] == 3 and [i["id"] for i in r["items"]] == [soon.id]


def test_patch_lead_writes_activity(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    r = client.patch(f"/api/leads/{lid}", json={"status": "talking", "owner": "yossi", "follow_up_on": "2026-12-01"})
    assert r.status_code == 200
    assert r.json()["status"] == "talking" and r.json()["follow_up_on"] == "2026-12-01"
    db.expire_all()
    act = db.query(LeadActivity).filter_by(lead_id=lid).one()
    assert act.kind == "edited" and act.actor == "tester@dayo-tech.com"
    assert act.data == {
        "changes": {"status": ["new", "talking"], "owner": [None, "yossi"], "follow_up_on": [None, "2026-12-01"]},
        "auto": False,
    }
    assert client.patch(f"/api/leads/{lid}", json={"status": "won"}).status_code == 422
    assert client.patch(f"/api/leads/{lid}", json={"status": "talking"}).status_code == 200
    assert len(_activity(db, lid)) == 1  # no change, no activity
    hist = client.get(f"/api/leads/{lid}/activity").json()
    assert hist[0]["kind"] == "edited" and hist[0]["data"]["changes"]["owner"] == [None, "yossi"]


def test_link_and_unlink(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    r = client.post(f"/api/leads/{lid}/cases", json={"loop_case_id": "intake-abc"})
    assert r.status_code == 201 and r.json()["how"] == "manual"
    assert client.post(f"/api/leads/{lid}/cases", json={"loop_case_id": "intake-abc"}).status_code == 201  # idempotent
    assert client.post(f"/api/leads/{lid}/cases", json={"loop_case_id": "has space"}).status_code == 422
    assert client.get(f"/api/leads/{lid}").json()["linked_case_count"] == 1
    assert client.delete(f"/api/leads/{lid}/cases/intake-abc").status_code == 204
    assert client.delete(f"/api/leads/{lid}/cases/intake-abc").status_code == 404
    assert [k for k, _ in _activity(db, lid)] == ["linked", "unlinked"]


def test_lead_cases_live_and_down(client, clean, db, use_mcp):  # noqa: F811
    c = company(db)
    lid = lead(db, c).id
    db.add(LeadCase(lead_id=lid, loop_case_id="intake-1", how="manual", linked_by="x"))
    db.commit()
    use_mcp(
        FakeMcp(
            {
                "case_story": {
                    "loop_case_id": "intake-1",
                    "where": "quoting, waiting on supplier",
                    "standing": {"phase": "quoting"},
                    "events": [{"at": "2026-11-01T10:00:00", "sentence": "RFQ sent"}],
                    "mails": [],
                },
                "find_quotation": '{"found": true, "doc": {"doc_num": 301234, "total": 99.5}}',
                "find_order": '{"found": false}',
            }
        )
    )
    [row] = client.get(f"/api/leads/{lid}/cases").json()
    assert row["available"] is True
    assert row["story"]["where"].startswith("quoting") and row["story"]["last_activity"] == "RFQ sent"
    assert row["quotation"] == {"doc_num": 301234, "total": 99.5}
    assert row["order"] is None and row["how"] == "manual"

    use_mcp(FakeMcp({"case_story": httpx.ReadTimeout("slow"), "find_quotation": httpx.ReadTimeout("slow"),
                     "find_order": httpx.ReadTimeout("slow")}))
    r = client.get(f"/api/leads/{lid}/cases")
    assert r.status_code == 200
    [row] = r.json()
    assert row["available"] is False and row["story"] is None and "timed out" in row["reason"]


def test_viewer_cannot_write_leads(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    for method, url, body in [
        ("patch", f"/api/leads/{lid}", {"status": "met"}),
        ("post", f"/api/leads/{lid}/cases", {"loop_case_id": "intake-1"}),
        ("delete", f"/api/leads/{lid}/cases/intake-1", None),
        ("post", f"/api/leads/{lid}/suggestions/1/accept", None),
        ("post", f"/api/leads/{lid}/suggestions/1/dismiss", None),
    ]:
        kw = {"headers": VIEWER}
        if body is not None:
            kw["json"] = body
        assert getattr(client, method)(url, **kw).status_code == 403, url
    assert client.get("/api/leads", headers=VIEWER).status_code == 200
    assert client.get(f"/api/leads/{lid}", headers=VIEWER).status_code == 200
