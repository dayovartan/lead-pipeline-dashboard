"""Exhibitions router: conventions, map, tags, coverage, dispatch and the floor list."""

from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import Contact, DispatchAssignment, Lead, LeadActivity, Meeting, MeetingContact, VenueNode
from fixtures.workbooks import SLUG, base_contacts, base_rows, make_convention, upload

VIEWER = {"x-forwarded-email": "viewer@dayo-tech.com", "x-forwarded-groups": "leads_viewer"}
P = f"/api/conventions/{SLUG}"


@pytest.fixture
def show(clean, client):
    make_convention(client)
    upload(client, base_rows(), base_contacts())
    items = client.get(P + "/appearances?page_size=100").json()["items"]
    return {it["company"]["name"]: it for it in items}


# ---- conventions ----


def test_conventions(clean, client):
    c = make_convention(client)
    assert c["counts"] == {"appearances": 0, "mapped": 0, "visited": 0, "leads": 0}
    assert c["venue_map_url"] is None
    assert client.post("/api/conventions", json={"name": "x", "slug": SLUG}).status_code == 409
    assert client.post("/api/conventions", json={"name": "x", "slug": "Bad Slug"}).status_code == 422
    assert client.post("/api/conventions", json={"name": "x", "slug": "other"}, headers=VIEWER).status_code == 403
    assert [x["slug"] for x in client.get("/api/conventions").json()] == [SLUG]
    assert client.get("/api/conventions/nope").status_code == 404


def test_venue_map_upload(clean, client):
    make_convention(client)
    r = client.post(P + "/venue-map", files={"file": ("hall plan.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 200
    assert r.json()["venue_map_url"] == P + "/venue-map"
    got = client.get(P + "/venue-map")
    assert got.status_code == 200 and got.content == b"\x89PNG fake"


# ---- map ----


def test_appearances_list_shape_and_filters(show, client):
    acme = show["Acme Memory GmbH"]
    assert acme["hall"] == "A3" and acme["booth"] == "123" and acme["hall_booth_raw"] == "A3.123"
    assert acme["company"]["categories"] == ["DRAM", "Memory modules"]
    assert acme["role"] is None and acme["dispatch"] is None and acme["lead_id"] is None
    assert acme["mapping"]["confirmed_at"] is None  # suggestions ran on import
    r = client.get(P + "/appearances?hall=a3").json()
    assert r["total"] == 2 and [i["booth"] for i in r["items"]] == ["123", "200"]
    assert client.get(P + "/appearances?q=gpu").json()["total"] == 1
    assert client.get(P + "/appearances?mapped=false").json()["total"] == 4
    assert client.get(P + "/appearances?role=none").json()["total"] == 4
    assert client.get(P + "/appearances?category=DRAM").json()["total"] == 1
    page = client.get(P + "/appearances?page=2&page_size=3&sort=name").json()
    assert page["total"] == 4 and len(page["items"]) == 1 and page["page"] == 2


def test_patch_confirms_mapping(show, client):
    acme = show["Acme Memory GmbH"]
    r = client.patch(P + f"/appearances/{acme['id']}", json={"role": "supplier", "priority": "must_visit"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "supplier" and body["mapping"]["confirmed_by"] == "tester@dayo-tech.com"
    assert client.get(P).json()["counts"]["mapped"] == 1
    assert client.get(P + "/appearances?mapped=true").json()["total"] == 1
    # met_at_booth alone does not confirm
    blue = show["Blue GPU Ltd."]
    r = client.patch(P + f"/appearances/{blue['id']}", json={"met_at_booth": True}).json()
    assert r["met_at_booth"] is True and r["mapping"]["confirmed_at"] is None
    assert client.patch(P + f"/appearances/{blue['id']}", json={"role": "nope"}).status_code == 422
    assert client.patch(P + f"/appearances/{blue['id']}", json={"role": "lead"}, headers=VIEWER).status_code == 403


def test_tags_and_rules(show, client):
    g = client.post(P + "/tag-groups", json={"name": "Memory"}).json()
    assert client.post(P + "/tag-groups", json={"name": "Memory"}).status_code == 409
    ram = client.post(P + "/tags", json={"name": "RAM", "group_id": g["id"]}).json()
    gpu = client.post(P + "/tags", json={"name": "GPU"}).json()
    assert client.post(P + "/tags", json={"name": "GPU"}).status_code == 409
    rule = client.post(P + "/category-rules", json={"category": "DRAM", "tag_id": ram["id"]}).json()
    assert client.post(P + "/category-rules", json={"category": "DRAM", "tag_id": ram["id"]}).json()["id"] == rule["id"]

    cats = {c["category"]: c for c in client.get(P + "/categories").json()}
    assert cats["DRAM"]["count"] == 1 and cats["DRAM"]["tag_ids"] == [ram["id"]]
    assert cats["Graphics cards"]["tag_ids"] == []

    counts = client.post(P + "/suggest").json()
    assert counts["appearances"] == 4 and counts["tags_suggested"] >= 2  # DRAM rule + built-in GPU keyword
    items = {i["company"]["name"]: i for i in client.get(P + "/appearances").json()["items"]}
    acme_tags = items["Acme Memory GmbH"]["tags"]
    assert [(t["name"], t["group"], t["suggested"], t["confirmed"]) for t in acme_tags] == [("RAM", "Memory", True, False)]
    assert items["Blue GPU Ltd."]["tags"][0]["name"] == "GPU"
    assert items["Delta Systems"]["mapping"]["suggested_role"] == "lead"

    tags = client.get(P + "/tags").json()
    assert tags["groups"][0]["tags"][0] == {"id": ram["id"], "name": "RAM", "group_id": g["id"], "count": 1,
                                            "confirmed_count": 0}
    assert [t["name"] for t in tags["ungrouped"]] == ["GPU"]

    acme_id = items["Acme Memory GmbH"]["id"]
    r = client.post(P + f"/appearances/{acme_id}/tags/{ram['id']}/confirm").json()
    assert r["tags"][0]["confirmed"] is True
    r = client.post(P + f"/appearances/{acme_id}/tags", json={"tag_id": gpu["id"]}).json()
    assert {(t["name"], t["suggested"], t["confirmed"]) for t in r["tags"]} == {("RAM", True, True), ("GPU", False, True)}
    r = client.delete(P + f"/appearances/{acme_id}/tags/{gpu['id']}").json()
    assert [t["name"] for t in r["tags"]] == ["RAM"]
    assert client.get(P + f"/appearances?tag={ram['id']}").json()["total"] == 1
    assert client.get(P + f"/appearances?group={g['id']}").json()["total"] == 1

    # deleting the rule and re-running removes the unconfirmed suggestion only
    client.delete(P + f"/category-rules/{rule['id']}")
    client.patch(P + f"/tags/{gpu['id']}", json={"group_id": g["id"]})
    client.post(P + "/suggest")
    items = {i["company"]["name"]: i for i in client.get(P + "/appearances").json()["items"]}
    assert [t["name"] for t in items["Acme Memory GmbH"]["tags"]] == ["RAM"]  # confirmed: kept


def test_bulk(show, client, db):
    ids = [show["Acme Memory GmbH"]["id"], show["Blue GPU Ltd."]["id"]]
    tag = client.post(P + "/tags", json={"name": "Hot"}).json()
    r = client.post(P + "/appearances/bulk", json={"ids": ids, "priority": "must_visit",
                                                    "add_tag_ids": [tag["id"]], "assignee": "Vartan"})
    assert r.json() == {"updated": 2}
    items = {i["id"]: i for i in client.get(P + "/appearances?assignee=vartan").json()["items"]}
    assert set(items) == set(ids)
    for it in items.values():
        assert it["priority"] == "must_visit" and it["dispatch"]["assignee"] == "Vartan"
        assert it["mapping"]["confirmed_at"] is not None
        assert [t["name"] for t in it["tags"]] == ["Hot"]

    # confirm=true accepts the suggested role
    delta = show["Delta Systems"]["id"]
    assert client.post(P + "/appearances/bulk", json={"ids": [delta], "confirm": True}).status_code == 200
    it = client.get(P + "/appearances?q=delta").json()["items"][0]
    assert it["role"] == "lead" and it["mapping"]["confirmed_by"] == "tester@dayo-tech.com"

    client.post(P + "/appearances/bulk", json={"ids": ids, "remove_tag_ids": [tag["id"]], "assignee": None})
    db.expire_all()
    assert {d.assignee for d in db.scalars(select(DispatchAssignment))} == {None}
    assert client.post(P + "/appearances/bulk", json={"ids": [99999]}).status_code == 404
    assert client.post(P + "/appearances/bulk", json={"ids": ids, "role": "lead"}, headers=VIEWER).status_code == 403


# ---- coverage ----


def test_coverage_and_rebuild_keep_positions(show, client, db):
    cov = client.get(P + "/coverage").json()
    kinds = sorted(n["kind"] for n in cov["nodes"])
    assert kinds.count("floor") == 3 and kinds.count("hall") == 3 and kinds.count("booth") == 4
    a3 = next(n for n in cov["nodes"] if n["label"] == "A3")
    assert a3["stats"]["total"] == 2
    floor_a = next(n for n in cov["nodes"] if n["kind"] == "floor" and n["label"] == "A")
    assert a3["parent_id"] == floor_a["id"]
    assert len(cov["booths"]) == 4

    acme = show["Acme Memory GmbH"]
    # booths carry role, suggested role and tags so the legend can filter
    tag = client.post(P + "/tags", json={"name": "COV_RAM"}).json()
    client.post(P + f"/appearances/{acme['id']}/tags", json={"tag_id": tag["id"]})
    client.patch(P + f"/appearances/{acme['id']}", json={"role": "supplier"})
    b = next(x for x in client.get(P + "/coverage").json()["booths"] if x["appearance_id"] == acme["id"])
    assert b["role"] == "supplier" and {"tag_id": tag["id"], "confirmed": True} in b["tags"] and "suggested_role" in b
    client.patch(P + f"/appearances/{acme['id']}", json={"priority": "must_visit"})
    assert client.patch(P + f"/venue/nodes/{a3['id']}", json={"x": 10, "y": 20}).status_code == 200
    client.put(P + f"/appearances/{show['Delta Systems']['id']}/dispatch", json={"visited": True})
    assert client.post(P + "/venue/rebuild").json()["created"] == 0
    cov = client.get(P + "/coverage").json()
    a3 = next(n for n in cov["nodes"] if n["label"] == "A3")
    assert (a3["x"], a3["y"]) == (10, 20)
    assert a3["stats"] == {"total": 2, "visited": 1, "must_visit_uncovered": 1, "skipped": 0}

    # a booth no one uses any more disappears on rebuild
    upload(client, [dict(base_rows()[0], hall_booth="A3.555")] + base_rows()[1:])
    db.expire_all()
    labels = {n.label for n in db.scalars(select(VenueNode).where(VenueNode.kind == "booth"))}
    assert "555" in labels and "123" not in labels


# ---- dispatch ----


def test_dispatch_and_export(show, client):
    for name in ("Acme Memory GmbH", "Delta Systems", "Cee Connectors Inc"):
        client.put(P + f"/appearances/{show[name]['id']}/dispatch", json={"assignee": "Yossi"})
    d = client.get(P + "/dispatch?assignee=Yossi").json()
    assert [(h["hall"], [a["booth"] for a in h["appearances"]]) for h in d["halls"]] == [
        ("A3", ["123", "200"]), ("C5", ["210"])]
    r = client.put(P + f"/appearances/{show['Acme Memory GmbH']['id']}/dispatch", json={"visited": True, "note": "ok"})
    assert r.json()["visited"] is True and r.json()["visited_at"] and r.json()["assignee"] == "Yossi"
    r = client.put(P + f"/appearances/{show['Acme Memory GmbH']['id']}/dispatch", json={"visited": False})
    assert r.json()["visited_at"] is None and r.json()["note"] == "ok"

    x = client.get(P + "/dispatch/export.xlsx?assignee=Yossi")
    assert x.status_code == 200 and "Yossi" in x.headers["content-disposition"]
    ws = load_workbook(BytesIO(x.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][:3] == ("Hall", "Booth", "Company") and len(rows) == 4
    assert rows[1][:3] == ("A3", "123", "Acme Memory GmbH")


# ---- floor ----


def test_floor_list(show, client):
    client.put(P + f"/appearances/{show['Blue GPU Ltd.']['id']}/dispatch", json={"assignee": "Vartan"})
    client.put(P + f"/appearances/{show['Acme Memory GmbH']['id']}/dispatch", json={"assignee": "vartan"})
    f = client.get(P + "/floor/Vartan").json()
    assert f["halls"] == ["A3", "B4"] and [i["company"]["name"] for i in f["items"]] == ["Acme Memory GmbH", "Blue GPU Ltd."]
    assert [i["hall"] for i in client.get(P + "/floor/Vartan?hall=B4").json()["items"]] == ["B4"]
    client.patch(P + f"/appearances/{show['Delta Systems']['id']}", json={"priority": "skip"})
    assert len(client.get(P + "/floor/all").json()["items"]) == 3


def test_floor_note(show, client, db):
    acme = show["Acme Memory GmbH"]
    body = {"text": "Wants **DDR5** prices", "contact": {"name": "Anna Acme", "email": "ANNA@acme-memory.de",
                                                          "title": "VP Sales"}}
    r = client.post(P + f"/floor/{acme['id']}/note", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["dispatch"]["visited"] is True and out["dispatch"]["note"] == "Wants **DDR5** prices"
    db.expire_all()
    m = db.get(Meeting, out["meeting"]["id"])
    assert (m.source, m.met_on, m.appearance_id, m.company_id, m.created_by) == (
        "floor", date.today(), acme["id"], acme["company"]["id"], "tester@dayo-tech.com")
    # the existing Excel contact was updated, not duplicated, and is now an app edit
    anna = db.scalars(select(Contact).where(func.lower(Contact.email) == "anna@acme-memory.de")).all()
    assert len(anna) == 1 and anna[0].title == "VP Sales" and "title" in anna[0].edited_fields
    assert db.get(MeetingContact, (m.id, anna[0].id)) is not None

    r = client.post(P + f"/floor/{acme['id']}/note", json={"text": "second", "contact": {"name": "New Person"}})
    db.expire_all()
    new = db.scalar(select(Contact).where(Contact.name == "New Person"))
    assert new.source == "floor"
    assert client.post(P + f"/floor/{acme['id']}/note", json={"text": ""}).status_code == 422
    assert client.post(P + f"/floor/{acme['id']}/note", json={"text": "x"}, headers=VIEWER).status_code == 403
    assert client.get(P).json()["counts"]["visited"] == 1


def test_floor_follow(show, client, db):
    blue, acme = show["Blue GPU Ltd."], show["Acme Memory GmbH"]
    r = client.post(P + f"/floor/{blue['id']}/follow")
    assert r.status_code == 200, r.text
    lead = r.json()
    assert lead["status"] == "new" and lead["created"] is True and lead["appearance_id"] == blue["id"]
    again = client.post(P + f"/floor/{blue['id']}/follow").json()
    assert again["id"] == lead["id"] and again["created"] is False

    client.post(P + f"/floor/{acme['id']}/note", json={"text": "met them"})
    lead2 = client.post(P + f"/floor/{acme['id']}/follow", json={"owner": "Yossi"}).json()
    assert lead2["status"] == "met" and lead2["owner"] == "Yossi"
    db.expire_all()
    acts = list(db.scalars(select(LeadActivity).where(LeadActivity.lead_id == lead2["id"])))
    assert [a.kind for a in acts] == ["opened"] and acts[0].data["source"] == "floor"
    assert db.scalar(select(func.count()).select_from(Lead)) == 2
    item = client.get(P + "/appearances?q=blue").json()["items"][0]
    assert item["lead_id"] == lead["id"]
    assert client.get(P).json()["counts"]["leads"] == 2
