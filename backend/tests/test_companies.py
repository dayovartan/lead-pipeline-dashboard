from datetime import date

import pytest
from test_mcp_support import VIEWER, appearance, company, contact, convention, lead

from app.models import Company, Contact, Lead, Meeting, MeetingAction
from app.services.kind import derive_kind


@pytest.mark.parametrize(
    "roles,kind",
    [
        ([], "unmapped"),
        ([None, None], "unmapped"),
        (["ignore"], "ignore"),
        (["ignore", None], "ignore"),
        (["lead"], "lead"),
        (["lead", "ignore"], "lead"),
        (["supplier"], "supplier"),
        (["supplier", None, "ignore"], "supplier"),
        (["lead", "supplier"], "both"),
        (["both"], "both"),
        (["both", "supplier"], "both"),
    ],
)
def test_derive_kind(roles, kind):
    assert derive_kind(roles) == kind


def test_kind_filter_matches_python_rule(client, clean, db):
    s1, s2 = convention(db), convention(db, slug="embedded-2027", name="embedded world 2027")
    cases = {
        "only-lead": [("lead", s1)],
        "only-supplier": [("supplier", s1), ("ignore", s2)],
        "both-sides": [("lead", s1), ("supplier", s2)],
        "ignored": [("ignore", s1)],
        "unconfirmed": [(None, s1)],
        "no-show": [],
    }
    for name, roles in cases.items():
        c = company(db, name=name, name_normalized=name)
        for role, show in roles:
            appearance(db, c, show, role=role)
    db.commit()
    expected = {"only-lead": "lead", "only-supplier": "supplier", "both-sides": "both",
                "ignored": "ignore", "unconfirmed": "unmapped", "no-show": "unmapped"}
    items = client.get("/api/companies?page_size=50").json()["items"]
    assert {i["name"]: i["kind"] for i in items} == expected
    for kind in ("lead", "supplier", "both", "ignore", "unmapped"):
        got = {i["name"] for i in client.get(f"/api/companies?kind={kind}").json()["items"]}
        assert got == {n for n, k in expected.items() if k == kind}, kind


def test_list_filters_and_shape(client, clean, db):
    show = convention(db)
    a = company(db, name="Acme GmbH", country="Germany", categories=["Sensors", "PCB"], domain="acme.de")
    b = company(db, name="Beta Ltd", name_normalized="beta", country="Israel", sap_card_code="C7")
    company(db, name="Gamma", name_normalized="gamma", country="Germany")
    appearance(db, a, show, role="lead", hall="A3", booth="101", met_at_booth=True)
    appearance(db, b, show, role="supplier")
    contact(db, b, name="Dana Levi", email="dana@beta.co.il")
    lead(db, a, status="new")
    db.commit()

    def names(qs):
        return sorted(i["name"] for i in client.get(f"/api/companies?{qs}").json()["items"])

    assert names("q=acme") == ["Acme GmbH"]
    assert names("q=dana@") == ["Beta Ltd"]  # contact email
    assert names("q=acme.de") == ["Acme GmbH"]  # domain
    assert names("country=germany") == ["Acme GmbH", "Gamma"]
    assert names("category=PCB") == ["Acme GmbH"]
    assert names("convention=electronica-2026") == ["Acme GmbH", "Beta Ltd"]
    assert names("role=supplier") == ["Beta Ltd"]
    assert names("has_lead=true") == ["Acme GmbH"]
    assert names("has_lead=false") == ["Beta Ltd", "Gamma"]
    assert names("sap_linked=true") == ["Beta Ltd"]
    assert names("met=true") == ["Acme GmbH"]

    body = client.get("/api/companies?q=acme").json()
    assert body["total"] == 1 and body["page"] == 1 and body["page_size"] == 50
    item = body["items"][0]
    assert item["kind"] == "lead" and item["lead_status"] == "new" and item["lead_id"]
    assert item["appearances"] == [
        {"convention_slug": "electronica-2026", "hall": "A3", "booth": "101", "role": "lead", "priority": None}
    ]


def test_paging(client, clean, db):
    for i in range(7):
        company(db, name=f"Co {i}", name_normalized=f"co {i}")
    db.commit()
    r = client.get("/api/companies?page=2&page_size=3").json()
    assert r["total"] == 7 and [i["name"] for i in r["items"]] == ["Co 3", "Co 4", "Co 5"]


def test_facets(client, clean, db):
    show = convention(db)
    a = company(db, name="A", name_normalized="a", country="Germany", categories=["PCB"])
    b = company(db, name="B", name_normalized="b", country="Germany", categories=["PCB", "Sensors"])
    company(db, name="C", name_normalized="c", country="Israel")
    appearance(db, a, show, role="lead")
    appearance(db, b, show)
    db.commit()
    f = client.get("/api/companies/facets?convention=electronica-2026").json()
    assert f["countries"] == [{"value": "Germany", "count": 2}]
    assert f["categories"][0] == {"value": "PCB", "count": 2}
    assert {r["value"]: r["count"] for r in f["roles"]} == {"lead": 1, "unmapped": 1}
    assert len(client.get("/api/companies/facets").json()["countries"]) == 2


def test_detail(client, clean, db):
    show = convention(db)
    c = company(db, name="Acme GmbH", raw={"secret": 1})
    appearance(db, c, show, role="both", hall="B1", booth="7")
    contact(db, c, email="ann@acme.de")
    lead(db, c, owner="vartan")
    db.commit()
    d = client.get(f"/api/companies/{c.id}").json()
    assert "raw" not in d
    assert d["kind"] == "both" and d["edited_fields"] == []
    assert d["contacts"][0]["email"] == "ann@acme.de"
    ap = d["appearances"][0]
    assert ap["convention_slug"] == "electronica-2026" and ap["tags"] == [] and ap["mapping"] is None and ap["dispatch"] is None
    assert d["leads"][0]["owner"] == "vartan"
    assert client.get("/api/companies/999999").status_code == 404


def test_patch_adds_edited_fields(client, clean, db):
    c = company(db, name="Acme GmbH", phone="1")
    db.commit()
    r = client.patch(f"/api/companies/{c.id}", json={"phone": "2", "website": "https://acme.de", "categories": ["X"]})
    assert r.status_code == 200
    assert r.json()["edited_fields"] == ["categories", "phone", "website"]
    # unchanged values don't count; new ones add to the set
    r = client.patch(f"/api/companies/{c.id}", json={"phone": "2", "name": "ACME Systems GmbH"})
    body = r.json()
    assert body["edited_fields"] == ["categories", "name", "phone", "website"]
    assert body["name_normalized"] and "gmbh" not in body["name_normalized"]
    # sap_card_code is not a catalogue field
    client.patch(f"/api/companies/{c.id}", json={"sap_card_code": "C1"})
    db.expire_all()
    assert db.get(Company, c.id).sap_card_code is None


def test_contacts_create_and_patch(client, clean, db):
    c = company(db)
    db.commit()
    r = client.post(f"/api/companies/{c.id}/contacts", json={"name": "Ann", "email": "Ann@acme.de"})
    assert r.status_code == 201 and r.json()["source"] == "app"
    cid = r.json()["id"]
    assert client.post(f"/api/companies/{c.id}/contacts", json={"email": "ann@ACME.de"}).status_code == 409
    r = client.patch(f"/api/contacts/{cid}", json={"title": "CTO", "name": "Ann"})
    assert r.json()["edited_fields"] == ["title"]
    got = client.get(f"/api/contacts/{cid}").json()
    assert got["company"]["id"] == c.id and got["title"] == "CTO"


def test_sap_link(client, clean, db):
    c = company(db)
    db.commit()
    assert client.post(f"/api/companies/{c.id}/sap-link", json={"card_code": " C123 "}).json()["sap_card_code"] == "C123"
    assert client.get(f"/api/companies/{c.id}").json()["sap_card_code"] == "C123"
    assert client.delete(f"/api/companies/{c.id}/sap-link").json()["sap_card_code"] is None


def test_merge(client, clean, db):
    show = convention(db)
    src = company(db, name="Acme Ltd", name_normalized="acme", phone="555", sap_card_code="C9")
    dst = company(db, name="Acme GmbH")
    ap_src = appearance(db, src, show, role="lead")
    ap_dst = appearance(db, dst, show, role="supplier")
    dup_src = contact(db, src, email="ann@acme.de")
    twin = contact(db, dst, email="ANN@acme.de")
    other = contact(db, src, name="Bob", email="bob@acme.de")
    l1 = lead(db, src, contact_id=dup_src.id, appearance_id=ap_src.id)
    db.commit()
    dup_id, other_id, twin_id, l1_id = dup_src.id, other.id, twin.id, l1.id
    r = client.post(f"/api/companies/{src.id}/merge", json={"into_id": dst.id})
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == dst.id and d["phone"] == "555" and d["sap_card_code"] == "C9"
    assert sorted(x["email"] for x in d["contacts"]) == ["ANN@acme.de", "bob@acme.de"]
    db.expire_all()
    moved = db.get(Lead, l1_id)
    assert moved.company_id == dst.id and moved.contact_id == twin_id and moved.appearance_id == ap_dst.id
    assert db.get(Contact, other_id).company_id == dst.id
    assert db.get(Contact, dup_id) is None
    assert db.get(Company, src.id).merged_into_id == dst.id
    assert [i["name"] for i in client.get("/api/companies").json()["items"]] == ["Acme GmbH"]
    assert client.post(f"/api/companies/{src.id}/merge", json={"into_id": dst.id}).status_code == 409
    assert client.post(f"/api/companies/{dst.id}/merge", json={"into_id": dst.id}).status_code == 422


def test_viewer_cannot_write(client, clean, db):
    c = company(db)
    ct = contact(db, c, email="a@acme.de")
    db.commit()
    writes = [
        ("patch", f"/api/companies/{c.id}", {"phone": "1"}),
        ("post", f"/api/companies/{c.id}/contacts", {"name": "x"}),
        ("patch", f"/api/contacts/{ct.id}", {"name": "x"}),
        ("post", f"/api/companies/{c.id}/sap-link", {"card_code": "C1"}),
        ("delete", f"/api/companies/{c.id}/sap-link", None),
        ("post", f"/api/companies/{c.id}/merge", {"into_id": c.id}),
        ("post", f"/api/companies/{c.id}/leads", {}),
    ]
    for method, url, body in writes:
        kw = {"headers": VIEWER}
        if body is not None:
            kw["json"] = body
        assert getattr(client, method)(url, **kw).status_code == 403, url
    assert client.get(f"/api/companies/{c.id}", headers=VIEWER).status_code == 200
    assert client.get("/api/companies", headers=VIEWER).status_code == 200


def test_company_export_md(client, clean, db):
    show = convention(db)
    c = company(db, name='Acme "Quotes" GmbH', country="Germany", categories=["PCB"])
    appearance(db, c, show, role="lead", hall="A3", booth="101")
    contact(db, c, name="Ann", email="ann@acme.de", title="CTO")
    lead(db, c, status="talking", owner="vartan")
    m = Meeting(company_id=c.id, met_on=date(2026, 11, 11), summary_md="Wants **sensors**.",
                met_by=["Vartan"], place="Booth A3-101")
    db.add(m)
    db.flush()
    db.add(MeetingAction(meeting_id=m.id, text="Send datasheet", owner="vartan"))
    db.commit()
    r = client.get(f"/api/companies/{c.id}/export.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    md = r.text
    assert md.startswith("---\ncompany: \"Acme \\\"Quotes\\\" GmbH\"\n")
    assert "lead_status: \"talking\"" in md and "  - \"A3 101\"" in md
    assert "## Contacts" in md and "Ann · CTO · ann@acme.de" in md
    assert "Wants **sensors**." in md and "- [ ] Send datasheet (@vartan)" in md
