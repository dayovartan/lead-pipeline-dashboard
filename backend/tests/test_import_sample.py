"""End to end with the synthetic sample workbooks from scripts/make_sample_xlsx.py."""

import sys
from pathlib import Path

from sqlalchemy import func, select

from app.models import Company, Contact, Lead
from fixtures.workbooks import make_convention, upload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from make_sample_xlsx import make  # noqa: E402


def test_sample_v1_then_v2(clean, client, db):
    make_convention(client)
    ex1, ct1, ex2, ct2 = make(200, 2026)
    dry = upload(client, ex1, ct1, dry_run=True)
    real = client.post(f"/api/imports/{dry['id']}/apply").json()
    assert dry["created"] == real["created"] and real["report"]["sheets"]["exhibitors"]["duplicates"] >= 8
    assert real["created"] >= 190
    db.expire_all()
    leads_after_v1 = db.scalar(select(func.count()).select_from(Lead))
    contacts_after_v1 = db.scalar(select(func.count()).select_from(Contact))
    assert leads_after_v1 == real["report"]["leads_created"] > 0

    # someone edits every phone in the app
    for c in db.scalars(select(Company)):
        c.phone, c.edited_fields = "app", ["phone"]
    db.commit()

    v2 = upload(client, ex2, ct2)
    assert v2["created"] == 5
    assert v2["conflicts"] >= 20
    assert {x["field"] for x in v2["report"]["conflicts"]} >= {"phone"}
    db.expire_all()
    # re-imports never create leads, even for exhibitors new to the show (LEADS_PLAN 7)
    assert db.scalar(select(func.count()).select_from(Lead)) == leads_after_v1  # re-imports never create leads
    assert db.scalar(select(func.count()).select_from(Contact)) >= contacts_after_v1
    assert set(db.scalars(select(Company.phone).where(Company.phone != "app"))) <= {None} | {
        r.get("phone") for r in ex2 if r["company"].startswith("Newcomer")}
