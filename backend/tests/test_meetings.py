from test_mcp_support import VIEWER, appearance, company, contact, convention, lead

from app.models import Lead, LeadActivity


def _meeting(client, company_id, **kw):
    body = {"company_id": company_id, "met_on": "2026-11-11", **kw}
    r = client.post("/api/meetings", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _follow_up(db, lead_id):
    db.expire_all()
    return db.get(Lead, lead_id).follow_up_on


def test_create_list_and_shape(client, clean, db):
    show = convention(db)
    c = company(db)
    ap = appearance(db, c, show, hall="A3", booth="101")
    ann = contact(db, c, name="Ann", email="ann@acme.de")
    bob = contact(db, c, name="Bob", email="bob@acme.de")
    lid = lead(db, c).id
    other = company(db, name="Other", name_normalized="other")
    db.commit()
    m = _meeting(
        client,
        c.id,
        lead_id=lid,
        appearance_id=ap.id,
        place="Booth A3-101",
        met_by=["Vartan", "Yossi"],
        summary_md="Talked about **sensors**.",
        contact_ids=[ann.id],
        actions=[{"text": "Send datasheet", "owner": "vartan", "due_on": "2026-11-20"}],
    )
    assert m["company_name"] == "Acme GmbH" and m["source"] == "app" and m["created_by"] == "tester@dayo-tech.com"
    assert m["contacts"] == [{"id": ann.id, "name": "Ann", "email": "ann@acme.de", "title": None}]
    assert m["actions"][0]["text"] == "Send datasheet" and m["actions"][0]["done_at"] is None
    newer = _meeting(client, c.id, met_on="2026-11-12", contact_ids=[bob.id], source="floor")
    _meeting(client, other.id)

    assert [x["id"] for x in client.get(f"/api/meetings?company_id={c.id}").json()] == [newer["id"], m["id"]]
    assert [x["id"] for x in client.get(f"/api/meetings?contact_id={ann.id}").json()] == [m["id"]]
    assert [x["id"] for x in client.get(f"/api/meetings?lead_id={lid}").json()] == [m["id"]]
    assert len(client.get("/api/meetings").json()) == 3


def test_refs_must_belong_to_company(client, clean, db):
    a, b = company(db), company(db, name="B", name_normalized="b")
    ct = contact(db, b, email="x@b.com")
    lb = lead(db, b)
    db.commit()
    base = {"company_id": a.id, "met_on": "2026-11-11"}
    assert client.post("/api/meetings", json={**base, "contact_ids": [ct.id]}).status_code == 422
    assert client.post("/api/meetings", json={**base, "lead_id": lb.id}).status_code == 422
    assert client.post("/api/meetings", json={**base, "company_id": 999999}).status_code == 404


def test_patch_meeting_and_actions(client, clean, db):
    c = company(db)
    ann = contact(db, c, name="Ann", email="ann@acme.de")
    db.commit()
    m = _meeting(client, c.id, actions=[{"text": "Call back"}])
    r = client.patch(f"/api/meetings/{m['id']}", json={"summary_md": "New text", "contact_ids": [ann.id], "met_by": ["Yossi"]})
    assert r.status_code == 200
    body = r.json()
    assert body["summary_md"] == "New text" and body["met_by"] == ["Yossi"] and [x["id"] for x in body["contacts"]] == [ann.id]
    r = client.post(f"/api/meetings/{m['id']}/actions", json={"text": "Send quote", "due_on": "2026-12-01"})
    assert r.status_code == 201 and len(r.json()["actions"]) == 2
    aid = r.json()["actions"][1]["id"]
    done = client.patch(f"/api/meetings/{m['id']}/actions/{aid}", json={"done": True}).json()
    assert done["actions"][1]["done_at"] is not None
    undone = client.patch(f"/api/meetings/{m['id']}/actions/{aid}", json={"done": False, "owner": "yossi"}).json()
    assert undone["actions"][1]["done_at"] is None and undone["actions"][1]["owner"] == "yossi"
    assert client.patch(f"/api/meetings/{m['id']}/actions/999999", json={"done": True}).status_code == 404


def test_follow_up_defaults_to_earliest_open_action(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    m = _meeting(
        client,
        c.id,
        lead_id=lid,
        actions=[{"text": "later", "due_on": "2026-12-10"}, {"text": "sooner", "due_on": "2026-11-20"}, {"text": "undated"}],
    )
    assert str(_follow_up(db, lid)) == "2026-11-20"
    # Done -> next open action
    sooner = next(a for a in m["actions"] if a["text"] == "sooner")
    client.patch(f"/api/meetings/{m['id']}/actions/{sooner['id']}", json={"done": True})
    assert str(_follow_up(db, lid)) == "2026-12-10"
    # An earlier action moves it again
    client.post(f"/api/meetings/{m['id']}/actions", json={"text": "urgent", "due_on": "2026-11-15"})
    assert str(_follow_up(db, lid)) == "2026-11-15"
    acts = db.query(LeadActivity).filter_by(lead_id=lid).order_by(LeadActivity.id).all()
    assert all(a.kind == "edited" and a.data["auto"] is True for a in acts)
    assert acts[-1].data["changes"]["follow_up_on"] == ["2026-12-10", "2026-11-15"]


def test_hand_set_follow_up_is_kept(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    client.patch(f"/api/leads/{lid}", json={"follow_up_on": "2027-01-05"})
    m = _meeting(client, c.id, lead_id=lid, actions=[{"text": "x", "due_on": "2026-11-20"}])
    assert str(_follow_up(db, lid)) == "2027-01-05"
    # Clearing it by hand hands it back to the actions.
    r = client.patch(f"/api/leads/{lid}", json={"follow_up_on": None})
    assert r.json()["follow_up_on"] == "2026-11-20"
    client.post(f"/api/meetings/{m['id']}/actions", json={"text": "y", "due_on": "2026-11-18"})
    assert str(_follow_up(db, lid)) == "2026-11-18"


def test_imported_follow_up_is_treated_as_by_hand(client, clean, db):
    c = company(db)
    from datetime import date

    lid = lead(db, c, follow_up_on=date(2026, 12, 24)).id  # e.g. seeded by the Excel import
    db.commit()
    _meeting(client, c.id, lead_id=lid, actions=[{"text": "x", "due_on": "2026-11-20"}])
    assert str(_follow_up(db, lid)) == "2026-12-24"


def test_unattached_company_meeting_counts_for_its_leads(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    _meeting(client, c.id, actions=[{"text": "x", "due_on": "2026-11-21"}])
    assert str(_follow_up(db, lid)) == "2026-11-21"
    # and following later picks it up straight away
    new = client.post(f"/api/companies/{c.id}/leads", json={}).json()
    assert new["follow_up_on"] == "2026-11-21"


def test_last_note_on_board(client, clean, db):
    c = company(db)
    lid = lead(db, c).id
    db.commit()
    _meeting(client, c.id, lead_id=lid, met_on="2026-11-10", summary_md="old")
    _meeting(client, c.id, lead_id=lid, met_on="2026-11-12", summary_md="# Heading\n\nNewest line")
    item = client.get("/api/leads").json()["items"][0]
    assert item["last_note"] == "Heading"


def test_meeting_export_md(client, clean, db):
    show = convention(db)
    c = company(db, name="Acme GmbH")
    ap = appearance(db, c, show, hall="A3", booth="101")
    ann = contact(db, c, name="Ann", email="ann@acme.de", title="CTO")
    db.commit()
    m = _meeting(
        client,
        c.id,
        appearance_id=ap.id,
        met_by=["Vartan"],
        summary_md="Wants samples.",
        contact_ids=[ann.id],
        actions=[{"text": "Send samples", "owner": "vartan", "due_on": "2026-11-20"}, {"text": "Intro call"}],
    )
    client.patch(f"/api/meetings/{m['id']}/actions/{m['actions'][1]['id']}", json={"done": True})
    r = client.get(f"/api/meetings/{m['id']}/export.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "Acme%20GmbH%202026-11-11.md" in r.headers["content-disposition"]
    md = r.text
    fm = md.split("---\n")[1]
    for line in (
        'company: "Acme GmbH"',
        'contacts:\n  - "Ann"',
        'roles:\n  - "CTO"',
        'convention: "electronica-2026"',
        'stand: "A3 101"',
        "date: 2026-11-11",
        'met_by:\n  - "Vartan"',
        'next_step: "Send samples"',
        "next_step_due: 2026-11-20",
    ):
        assert line in fm, line
    assert "## Summary\n\nWants samples." in md
    assert "- [ ] Send samples (@vartan, due 2026-11-20)" in md and "- [x] Intro call" in md


def test_viewer_cannot_write_meetings(client, clean, db):
    c = company(db)
    db.commit()
    m = _meeting(client, c.id, actions=[{"text": "x"}])
    aid = m["actions"][0]["id"]
    for method, url, body in [
        ("post", "/api/meetings", {"company_id": c.id, "met_on": "2026-11-11"}),
        ("patch", f"/api/meetings/{m['id']}", {"place": "x"}),
        ("post", f"/api/meetings/{m['id']}/actions", {"text": "y"}),
        ("patch", f"/api/meetings/{m['id']}/actions/{aid}", {"done": True}),
    ]:
        assert getattr(client, method)(url, json=body, headers=VIEWER).status_code == 403, url
    assert client.get("/api/meetings", headers=VIEWER).status_code == 200
    assert client.get(f"/api/meetings/{m['id']}/export.md", headers=VIEWER).status_code == 200
