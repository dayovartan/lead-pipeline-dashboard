"""Excel intake (LEADS_PLAN 7 and 18): dedupe, dry run, re-import rules, contacts, leads."""

from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    AppearanceMapping,
    AppearanceTag,
    Company,
    Contact,
    ConventionAppearance,
    DispatchAssignment,
    HardwareTag,
    ImportBatch,
    Lead,
    LeadActivity,
    Meeting,
)
from fixtures.workbooks import SLUG, XLSX, base_contacts, base_rows, exhibitor, make_convention, upload

VIEWER = {"x-forwarded-email": "viewer@dayo-tech.com", "x-forwarded-groups": "leads_viewer"}


@pytest.fixture
def conv(clean, client):
    return make_convention(client)


def count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def company(db, name_normalized: str) -> Company:
    db.expire_all()
    return db.scalar(select(Company).where(Company.name_normalized == name_normalized))


# ---- dry run ----


def test_dry_run_writes_only_the_batch_row(conv, client, db):
    b = upload(client, base_rows(), base_contacts(), dry_run=True)
    assert b["dry_run"] is True
    assert b["created"] == 4 and b["rows"] == 4
    assert b["report"]["sheets"]["contacts"]["created"] == 2
    for model in (Company, ConventionAppearance, Contact, Lead, AppearanceMapping):
        assert count(db, model) == 0
    assert count(db, ImportBatch) == 1
    assert b["file"].startswith(f"imports/{b['id']}-")


def test_dry_run_counts_equal_real_run(conv, client, db):
    rows = base_rows() + [exhibitor("Acme Memory", website="acme-memory.de", owner="Vartan")]
    dry = upload(client, rows, base_contacts(), dry_run=True)
    r = client.post(f"/api/imports/{dry['id']}/apply")
    assert r.status_code == 200, r.text
    real = r.json()
    assert real["dry_run"] is False and real["report"]["from_batch_id"] == dry["id"]
    for k in ("rows", "created", "updated", "skipped", "conflicts"):
        assert dry[k] == real[k], k
    assert dry["report"]["sheets"] == real["report"]["sheets"]
    assert dry["report"]["leads_created"] == real["report"]["leads_created"]
    assert count(db, Company) == 4
    # applying the same dry run twice is refused
    assert client.post(f"/api/imports/{dry['id']}/apply").status_code == 409
    assert client.post(f"/api/imports/{real['id']}/apply").status_code == 409


def test_dry_run_of_reimport_matches_real_reimport(conv, client, db):
    upload(client, base_rows(), base_contacts())
    db.query(Company).filter(Company.name_normalized == "acme memory").update(
        {"edited_fields": ["phone"], "phone": "app phone"})
    db.commit()
    rows = base_rows()
    rows[0]["phone"] = "+49 89 999"
    rows[1]["description"] = "new text"
    dry = upload(client, rows, base_contacts(), dry_run=True)
    real = client.post(f"/api/imports/{dry['id']}/apply").json()
    assert (dry["updated"], dry["conflicts"]) == (real["updated"], real["conflicts"]) == (1, 1)
    assert dry["report"]["conflicts"] == real["report"]["conflicts"]


# ---- dedupe ----


def test_upsert_on_dedupe_key(conv, client, db):
    rows = [
        exhibitor("Acme Memory GmbH", website="https://www.acme-memory.de"),
        exhibitor("ACME Memory Europe", primary_email="eu@acme-memory.de"),  # same domain, other name
        exhibitor("Foo Elec Co., Ltd."),
        exhibitor("foo elec"),  # same normalized name, no domain
        exhibitor("Gee One", primary_email="gee@gmail.com"),  # free mail: no domain key
        exhibitor("Gee Two", primary_email="two@gmail.com"),
        exhibitor("Same Name", website="same-a.com"),
        exhibitor("Same Name", website="same-b.com"),  # different domains stay apart
        exhibitor("", website="nobody.com"),  # no name: skipped
    ]
    b = upload(client, rows)
    ex = b["report"]["sheets"]["exhibitors"]
    assert ex["created"] == 6 and ex["duplicates"] == 2 and ex["skipped"] == 1
    assert count(db, Company) == 6
    assert count(db, ConventionAppearance) == 6
    assert company(db, "gee one").domain is None
    # second import of the same file: nothing new, nothing changed
    b2 = upload(client, rows)
    assert (b2["created"], b2["updated"]) == (0, 0)
    assert b2["report"]["sheets"]["exhibitors"]["unchanged"] == 6
    assert count(db, Company) == 6


def test_merged_company_is_followed(conv, client, db):
    upload(client, [exhibitor("Old Name", website="old.com"), exhibitor("New Name", website="new.com")])
    old, new = company(db, "old name"), company(db, "new name")
    old.merged_into_id = new.id
    db.commit()
    upload(client, [exhibitor("Old Name", website="old.com", phone="123")], dry_run=False)
    assert company(db, "new name").phone == "123"


def test_hall_booth_on_appearance(conv, client, db):
    upload(client, base_rows())
    db.expire_all()
    got = {(a.hall, a.booth, a.hall_booth_raw) for a in db.scalars(select(ConventionAppearance))}
    assert got == {("A3", "123", "A3.123"), ("B4", "411", "Hall B4 / 411"), ("C5", "210", "C5-210"),
                   ("A3", "200", "A3.200")}


# ---- re-import rules ----


def test_reimport_refreshes_raw_and_unedited_columns(conv, client, db):
    upload(client, base_rows())
    rows = base_rows()
    rows[0].update(phone="+49 89 2", description="Now also SSDs", hall_booth="A4.100", meeting_note="notes/acme.md")
    rows[0]["phone"] = "+49 89 2"
    rows[2]["address"] = None  # blank never clears
    b = upload(client, rows)
    assert b["updated"] == 1 and b["conflicts"] == 0
    c = company(db, "acme memory")
    assert c.phone == "+49 89 2" and c.description == "Now also SSDs"
    assert c.raw["Phone"] == "+49 89 2"
    assert c.raw["Meeting note"] == "notes/acme.md"  # kept in raw only
    a = db.scalar(select(ConventionAppearance).where(ConventionAppearance.company_id == c.id))
    assert (a.hall, a.booth) == ("A4", "100")


def test_edited_and_app_owned_fields_stay_and_show_as_conflicts(conv, client, db):
    upload(client, base_rows())
    c = company(db, "acme memory")
    c.phone = "app phone"
    c.edited_fields = ["phone"]
    c.sap_card_code = "C1000"
    a = db.scalar(select(ConventionAppearance).where(ConventionAppearance.company_id == c.id))
    a.role, a.priority = "supplier", "must_visit"
    a.edited_fields = ["hall_booth"]
    a.hall, a.booth, a.hall_booth_raw = "A1", "1", "A1.1"
    tag = HardwareTag(name="RAM")
    db.add(tag)
    db.flush()
    db.add(AppearanceTag(appearance_id=a.id, tag_id=tag.id, suggested=False, confirmed=True))
    db.add(DispatchAssignment(appearance_id=a.id, assignee="Yossi", visited=True, note="seen"))
    m = db.get(AppearanceMapping, a.id)  # created by the suggestions that ran on apply
    m.confirmed_by, m.confirmed_at = "x@y", func.now()
    db.commit()

    rows = base_rows()
    rows[0].update(phone="+49 89 777", hall_booth="A3.999", website="https://acme-memory.de")
    b = upload(client, rows)
    fields = {(x["company"], x["field"]): x for x in b["report"]["conflicts"]}
    assert ("Acme Memory GmbH", "phone") in fields
    assert fields[("Acme Memory GmbH", "phone")]["app_value"] == "app phone"
    assert fields[("Acme Memory GmbH", "phone")]["file_value"] == "+49 89 777"
    assert ("Acme Memory GmbH", "hall_booth") in fields
    assert b["conflicts"] == 2

    db.expire_all()
    c = company(db, "acme memory")
    assert c.phone == "app phone" and c.sap_card_code == "C1000"
    assert c.raw["Phone"] == "+49 89 777"  # raw is always the latest source row
    a = db.get(ConventionAppearance, a.id)
    assert (a.role, a.priority, a.hall_booth_raw) == ("supplier", "must_visit", "A1.1")
    assert db.get(DispatchAssignment, a.id).assignee == "Yossi"
    at = db.get(AppearanceTag, (a.id, tag.id))
    assert at.confirmed and not at.suggested
    assert db.get(AppearanceMapping, a.id).confirmed_by == "x@y"


def test_contacts_upsert_and_are_never_deleted(conv, client, db):
    upload(client, base_rows(), base_contacts())
    acme = company(db, "acme memory")
    db.add(Contact(company_id=acme.id, name="App Only", email="app@acme-memory.de", source="app"))
    db.commit()
    contacts = [
        # same email in another case: an update, not a new contact
        {"company": "Acme Memory GmbH", "name": "Anna Acme", "title": "Head of Sales", "email": "anna@ACME-memory.de"},
        {"company": "Acme Memory", "name": "Carl New", "email": "carl@acme-memory.de"},
        {"company": "Nobody GmbH", "name": "Ghost", "email": "g@nobody.com"},
    ]  # Bob Blue is gone from the file
    b = upload(client, base_rows(), contacts)
    ct = b["report"]["sheets"]["contacts"]
    assert (ct["created"], ct["updated"], ct["skipped"]) == (1, 1, 1)
    db.expire_all()
    emails = {c.email.lower() for c in db.scalars(select(Contact))}
    assert emails == {"anna@acme-memory.de", "bob@bluegpu.com", "app@acme-memory.de", "carl@acme-memory.de"}
    anna = db.scalar(select(Contact).where(func.lower(Contact.email) == "anna@acme-memory.de"))
    assert anna.title == "Head of Sales"


def test_edited_contact_field_is_a_conflict(conv, client, db):
    upload(client, base_rows(), base_contacts())
    bob = db.scalar(select(Contact).where(Contact.email == "bob@bluegpu.com"))
    bob.title, bob.edited_fields = "CTO", ["title"]
    db.commit()
    contacts = base_contacts()
    contacts[1]["title"] = "Sales"
    b = upload(client, base_rows(), contacts)
    assert [x["field"] for x in b["report"]["conflicts"]] == ["contact.title"]
    db.expire_all()
    assert db.get(Contact, bob.id).title == "CTO"


# ---- leads ----


def test_leads_only_on_first_import(conv, client, db):
    rows = base_rows()
    rows[0].update(met_at_booth="yes", lead_status="Follow up", owner="Vartan", notes="wants DDR5 quote",
                   follow_up_date=date(2026, 11, 20))
    rows[1].update(lead_status="Hot!!", owner="Yossi")
    rows[2].update(met_at_booth="x")
    b = upload(client, rows)
    assert b["report"]["leads_created"] == 3
    db.expire_all()
    leads = {l.company_id: l for l in db.scalars(select(Lead))}
    acme = leads[company(db, "acme memory").id]
    assert (acme.status, acme.owner, acme.notes, acme.follow_up_on) == ("follow_up", "Vartan", "wants DDR5 quote",
                                                                         date(2026, 11, 20))
    assert acme.appearance_id is not None
    blue = leads[company(db, "blue gpu").id]
    assert blue.status == "new" and "Hot!!" in blue.notes
    assert leads[company(db, "cee connectors").id].status == "met"
    acts = list(db.scalars(select(LeadActivity)))
    assert len(acts) == 3 and {a.kind for a in acts} == {"opened"} and {a.actor for a in acts} == {"import"}
    assert any(a.data.get("excel_lead_status") == "Hot!!" for a in acts)
    a = db.scalar(select(ConventionAppearance).where(ConventionAppearance.company_id == acme.company_id))
    assert a.met_at_booth is True

    # Re-import with different lead activity: no new leads, lead fields untouched.
    rows[0].update(lead_status="parked", owner="Someone else", notes="changed")
    rows[3].update(owner="Vartan")  # existing appearance, new activity: still no lead
    rows.append(exhibitor("Brand New Co", website="brandnew.io", owner="Yossi"))  # new at this show: still no lead (LEADS_PLAN 7)
    b2 = upload(client, rows)
    assert b2["report"]["leads_created"] == 0
    db.expire_all()
    assert count(db, Lead) == 3
    acme = db.get(Lead, acme.id)
    assert (acme.status, acme.owner, acme.notes) == ("follow_up", "Vartan", "wants DDR5 quote")


def test_bad_follow_up_date_is_reported(conv, client, db):
    rows = [exhibitor("Acme", website="acme.de", follow_up_date="next week")]
    b = upload(client, rows)
    assert b["report"]["leads_created"] == 1
    assert any("Follow-up date" in e["message"] for e in b["report"]["errors"])
    db.expire_all()
    assert db.scalar(select(Lead)).follow_up_on is None


def test_import_writes_no_meetings(conv, client, db):
    rows = [exhibitor("Acme", website="acme.de", meeting_note="Conventions/electronica-2026/Acme.md")]
    upload(client, rows)
    assert count(db, Meeting) == 0


# ---- mapping suggestions on apply ----


def test_apply_suggests_but_never_confirms(conv, client, db):
    tag = client.post(f"/api/conventions/{SLUG}/tags", json={"name": "RAM"}).json()
    client.post(f"/api/conventions/{SLUG}/category-rules", json={"category": "DRAM", "tag_id": tag["id"]})
    b = upload(client, base_rows())
    assert b["report"]["suggested"]["tags_suggested"] >= 1
    db.expire_all()
    acme = company(db, "acme memory")
    a = db.scalar(select(ConventionAppearance).where(ConventionAppearance.company_id == acme.id))
    at = db.get(AppearanceTag, (a.id, tag["id"]))
    assert at.suggested and not at.confirmed
    m = db.get(AppearanceMapping, a.id)
    assert m.suggested_role == "supplier" and m.confirmed_at is None and a.role is None
    assert client.get(f"/api/conventions/{SLUG}").json()["counts"]["mapped"] == 0
    assert b["report"]["venue"]["halls"] == 3


# ---- endpoints ----


def test_batches_list_and_get(conv, client):
    b = upload(client, base_rows(), dry_run=True)
    lst = client.get(f"/api/imports?convention_slug={SLUG}").json()
    assert [x["id"] for x in lst] == [b["id"]]
    assert "conflicts" not in lst[0]["report"]
    one = client.get(f"/api/imports/{b['id']}").json()
    assert one["report"]["sheets"]["exhibitors"]["created"] == 4
    assert client.get("/api/imports/999").status_code == 404


def test_template(client):
    r = client.get("/api/imports/template.xlsx")
    assert r.status_code == 200
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["Exhibitors", "Contacts"]
    headers = [c.value for c in wb["Exhibitors"][1]]
    assert headers[:3] == ["Company", "Country", "City"] and "Meeting note" in headers
    assert [c.value for c in wb["Contacts"][1]] == ["Company", "Name", "Title", "Email", "Phone"]


def test_headers_case_insensitive(conv, client, db):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "exhibitors"
    ws.append(["COMPANY", "website", "hall / booth"])
    ws.append(["Acme", "acme.de", "A1.5"])
    buf = BytesIO()
    wb.save(buf)
    r = client.post("/api/imports", files={"file": ("a.xlsx", buf.getvalue(), XLSX)},
                    data={"convention_slug": SLUG, "dry_run": "false"})
    assert r.json()["created"] == 1
    db.expire_all()
    assert db.scalar(select(ConventionAppearance)).hall == "A1"


def test_bad_uploads(conv, client, db):
    r = client.post("/api/imports", files={"file": ("a.xlsx", b"not excel", XLSX)}, data={"convention_slug": SLUG})
    assert r.status_code == 400
    assert count(db, ImportBatch) == 0
    r = client.post("/api/imports", files={"file": ("a.xlsx", b"x", XLSX)}, data={"convention_slug": "nope"})
    assert r.status_code == 404


def test_viewer_cannot_import(conv, client):
    from app.services.xlsx import write_import_workbook

    r = client.post("/api/imports", files={"file": ("a.xlsx", write_import_workbook(base_rows()), XLSX)},
                    data={"convention_slug": SLUG}, headers=VIEWER)
    assert r.status_code == 403
    assert client.get("/api/imports", headers=VIEWER).status_code == 200
