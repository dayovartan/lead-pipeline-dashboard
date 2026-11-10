from datetime import date

from test_mcp_support import company, contact

from app.models import Company, Meeting


def test_search_everything(client, clean, db):
    acme = company(db, name="Acme Sensors GmbH", name_normalized="acme sensors", domain="acme.de", country="Germany")
    company(db, name="Beta", name_normalized="beta", domain="beta-acme.com")
    merged = company(db, name="Acme Old", name_normalized="acme old")
    db.flush()
    merged.merged_into_id = acme.id
    contact(db, acme, name="Ann Acmeson", email="ann@acme.de")
    db.add(Meeting(company_id=acme.id, met_on=date(2026, 11, 11), summary_md="They want piezo buzzers in bulk."))
    db.add(Meeting(company_id=acme.id, met_on=date(2026, 11, 12), summary_md="Nothing to see", place="Hall A3"))
    db.commit()

    r = client.get("/api/search?q=acme").json()
    assert [c["name"] for c in r["companies"]] == ["Acme Sensors GmbH", "Beta"]  # prefix first, merged hidden
    assert r["companies"][0] == {"id": acme.id, "name": "Acme Sensors GmbH", "country": "Germany"}
    assert r["contacts"][0]["company_name"] == "Acme Sensors GmbH"

    hits = client.get("/api/search?q=buzzers").json()["meetings"]
    assert len(hits) == 1 and "**buzzers**" in hits[0]["snippet"] and hits[0]["company_name"] == "Acme Sensors GmbH"
    assert len(client.get("/api/search?q=hall a3").json()["meetings"]) == 1  # ILIKE on place
    assert len(client.get("/api/search?q=piez").json()["meetings"]) == 1  # ILIKE catches partial words


def test_search_empty_and_wildcards(client, clean, db):
    company(db, name="100% Cotton", name_normalized="100 cotton")
    company(db, name="1000 Parts", name_normalized="1000 parts")
    db.commit()
    assert client.get("/api/search?q=").json() == {"companies": [], "contacts": [], "meetings": []}
    assert [c["name"] for c in client.get("/api/search?q=100%25").json()["companies"]] == ["100% Cotton"]
    assert db.query(Company).count() == 2
