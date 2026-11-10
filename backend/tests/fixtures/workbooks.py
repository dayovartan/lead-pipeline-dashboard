"""Helpers that build small import workbooks and upload them, shared by the import and
exhibitions tests."""

from app.services.xlsx import write_import_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SLUG = "electronica-2026"


def exhibitor(name: str, **kw) -> dict:
    row = {"company": name, "country": "Germany", "city": "Munich"}
    row.update(kw)
    return row


def base_rows() -> list[dict]:
    return [
        exhibitor("Acme Memory GmbH", website="https://www.acme-memory.de", phone="+49 89 1",
                  hall_booth="A3.123", categories="DRAM; Memory modules", description="DDR5 memory modules"),
        exhibitor("Blue GPU Ltd.", website="bluegpu.com", hall_booth="Hall B4 / 411",
                  categories="Graphics cards", primary_email="sales@bluegpu.com"),
        exhibitor("Cee Connectors Inc", primary_email="info@cee-conn.com", hall_booth="C5-210",
                  categories="Connectors, Cables"),
        exhibitor("Delta Systems", primary_email="delta@gmail.com", hall_booth="A3.200",
                  description="System integrator for industrial PCs"),
    ]


def base_contacts() -> list[dict]:
    return [
        {"company": "Acme Memory GmbH", "name": "Anna Acme", "title": "Sales", "email": "Anna@acme-memory.de"},
        {"company": "Blue GPU Ltd.", "name": "Bob Blue", "email": "bob@bluegpu.com"},
    ]


def make_convention(client, slug: str = SLUG) -> dict:
    r = client.post("/api/conventions", json={"name": "electronica 2026", "slug": slug, "city": "Munich",
                                               "country": "Germany", "starts_on": "2026-11-10",
                                               "ends_on": "2026-11-13"})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, rows, contacts=(), dry_run: bool = False, slug: str = SLUG, headers=None) -> dict:
    data = write_import_workbook(list(rows), list(contacts))
    r = client.post(
        "/api/imports",
        files={"file": ("electronica.xlsx", data, XLSX)},
        data={"convention_slug": slug, "dry_run": "true" if dry_run else "false"},
        headers=headers or {},
    )
    assert r.status_code == 200, r.text
    return r.json()
