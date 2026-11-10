"""Write synthetic electronica-like import workbooks (all companies are made up).

    cd backend
    .venv/bin/python scripts/make_sample_xlsx.py --out /tmp/sample --count 200

Writes two files in the import format (docs/API.md "Imports"):
- electronica-sample-v1.xlsx: ~200 exhibitors over halls A1-C6, some listed twice under another
  name but the same domain, some with free-mail emails, a few with lead activity, and a
  Contacts sheet.
- electronica-sample-v2.xlsx: the same list a week later: new phones, moved booths, new
  descriptions, a few new exhibitors and contacts, one contact gone. Edit some of those fields in
  the app after loading v1, then dry-run v2 to see conflicts.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.xlsx import write_import_workbook  # noqa: E402

PREFIXES = ["Nova", "Apex", "Shenzhen", "Taipei", "Bavaria", "Nordic", "Delta", "Quantum", "Silicon", "Volt",
            "Helix", "Orion", "Kappa", "Lumen", "Vector", "Zenith", "Polar", "Atlas", "Fusion", "Pioneer"]
CORES = ["Memory", "Micro", "Semi", "Connect", "Power", "Display", "Storage", "Sensor", "Circuit", "Systems",
         "Electronics", "Devices", "Logic", "Tech", "Components", "Optics", "Cable", "Thermal"]
SUFFIXES = ["GmbH", "Co., Ltd.", "Inc.", "Ltd", "AG", "S.A.", "B.V.", "GmbH & Co. KG", "Corp.", 'בע"מ', ""]
COUNTRIES = [("Germany", "Munich"), ("China", "Shenzhen"), ("Taiwan", "Taipei"), ("USA", "San Jose"),
             ("Israel", "Tel Aviv"), ("Netherlands", "Eindhoven"), ("Japan", "Osaka"), ("Korea", "Seoul"),
             ("Italy", "Milan"), ("France", "Grenoble")]
CATEGORIES = ["DRAM", "Memory modules", "NAND flash", "SSD", "HDD", "Graphics cards", "GPU", "Connectors",
              "Cable assemblies", "Power supplies", "Passive components", "Sensors", "Displays", "PCB",
              "EMS", "Semiconductors", "Microcontrollers", "Embedded systems", "Test & measurement",
              "Thermal management", "Fans", "Distribution"]
DESCRIPTIONS = [
    "Manufacturer of {c} for industrial and automotive markets.",
    "Distributor of {c} with stock in Europe and Asia.",
    "System integrator building rugged PCs with {c}.",
    "OEM supplier of {c}; custom designs on request.",
    "Leading provider of {c} and related services.",
]
FREE_MAIL = ["gmail.com", "163.com", "qq.com", "outlook.com", "web.de"]
FIRST = ["Anna", "Ben", "Chen", "Dana", "Eli", "Fang", "Gil", "Hana", "Ivan", "Jun", "Kai", "Lea", "Moshe", "Noa"]
LAST = ["Schmidt", "Li", "Wang", "Cohen", "Levi", "Müller", "Tanaka", "Kim", "Rossi", "Dubois", "Chen"]


def slugify(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def make(count: int, seed: int) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    rnd = random.Random(seed)
    halls = [f"{row}{n}" for row in "ABC" for n in range(1, 7)]
    used_names: set[str] = set()
    exhibitors: list[dict] = []
    contacts: list[dict] = []
    for i in range(count):
        for attempt in range(1000):
            base = f"{rnd.choice(PREFIXES)} {rnd.choice(CORES)}"
            if attempt > 20:  # the name pool is small; number the rest
                base = f"{base} {i}"
            if base not in used_names:
                used_names.add(base)
                break
        name = f"{base} {rnd.choice(SUFFIXES)}".strip()
        domain = slugify(base) + rnd.choice([".com", ".de", ".com.tw", ".cn", ".co.il", ".eu"])
        country, city = rnd.choice(COUNTRIES)
        cats = rnd.sample(CATEGORIES, rnd.randint(1, 4))
        hall = rnd.choice(halls)
        free = rnd.random() < 0.08
        row = {
            "company": name,
            "country": country,
            "city": city,
            "address": f"{rnd.randint(1, 200)} {rnd.choice(['Main', 'Industrial', 'Tech', 'Harbor'])} Road",
            "phone": f"+{rnd.randint(1, 99)} {rnd.randint(100, 999)} {rnd.randint(100000, 999999)}",
            "primary_email": f"info@{rnd.choice(FREE_MAIL) if free else domain}",
            "website": "" if free else rnd.choice([f"https://www.{domain}", f"{domain}", f"http://{domain}/en/"]),
            "hall_booth": rnd.choice([f"{hall}.{rnd.randint(100, 699)}", f"Hall {hall} / {rnd.randint(100, 699)}",
                                      f"{hall}-{rnd.randint(100, 699)}"]),
            "categories": "; ".join(cats),
            "description": rnd.choice(DESCRIPTIONS).format(c=cats[0].lower()),
            "profile_url": f"https://exhibitors.example.test/electronica-2026/{slugify(base)}",
        }
        if rnd.random() < 0.06:  # a few rows that already have lead activity
            row.update(met_at_booth="yes" if rnd.random() < 0.5 else "",
                       lead_status=rnd.choice(["new", "Follow up", "talking", "hot", ""]),
                       owner=rnd.choice(["Vartan", "Yossi"]),
                       notes="Interested in volume pricing",
                       follow_up_date=date(2026, 11, 20) + timedelta(days=rnd.randint(0, 20)))
        if rnd.random() < 0.05:
            row["meeting_note"] = f"Conventions/electronica-2026/{base}.md"
        exhibitors.append(row)
        for _ in range(rnd.randint(0, 3)):
            first, last = rnd.choice(FIRST), rnd.choice(LAST)
            email_domain = rnd.choice(FREE_MAIL) if free else domain
            contacts.append({"company": name, "name": f"{first} {last}",
                             "title": rnd.choice(["Sales Manager", "CEO", "FAE", "Key Account", ""]),
                             "email": f"{first.lower()}.{slugify(last)}@{email_domain}",
                             "phone": f"+{rnd.randint(1, 99)} {rnd.randint(1000000, 9999999)}"})

    # Same company listed again under another name (e.g. a sister brand): same domain.
    for row in rnd.sample([r for r in exhibitors if r["website"]], 8):
        dup = dict(row, company=row["company"].split()[0] + " Group", hall_booth=row["hall_booth"])
        dup.pop("lead_status", None)
        exhibitors.append(dup)
    rnd.shuffle(exhibitors)

    # v2: a week later.
    v2 = [dict(r) for r in exhibitors]
    for r in rnd.sample(v2, 20):
        r["phone"] = f"+{rnd.randint(1, 99)} {rnd.randint(100, 999)} {rnd.randint(100000, 999999)}"
    for r in rnd.sample(v2, 10):
        r["hall_booth"] = f"{rnd.choice(halls)}.{rnd.randint(100, 699)}"
    for r in rnd.sample(v2, 10):
        r["description"] = r["description"] + " Now shipping DDR5 and PCIe 5.0 SSDs."
    for r in rnd.sample(v2, 5):
        r["lead_status"], r["owner"] = "talking", "Vartan"  # must not create or change leads
    for i in range(5):
        v2.append({"company": f"Newcomer {i + 1} GmbH", "country": "Germany", "city": "Munich",
                   "website": f"newcomer{i + 1}.de", "hall_booth": f"C{i + 1}.{500 + i}",
                   "categories": "Sensors", "owner": "Yossi" if i == 0 else ""})
    v2_contacts = [dict(c) for c in contacts]
    if v2_contacts:
        v2_contacts.pop(0)  # gone from the file, must stay in the app
        v2_contacts[0]["title"] = "Head of Sales"
    v2_contacts.append({"company": "Newcomer 1 GmbH", "name": "Nina New", "email": "nina@newcomer1.de"})
    return exhibitors, contacts, v2, v2_contacts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=".", help="directory to write the two workbooks to")
    ap.add_argument("--count", type=int, default=200, help="number of distinct companies")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ex1, ct1, ex2, ct2 = make(args.count, args.seed)
    (out / "electronica-sample-v1.xlsx").write_bytes(write_import_workbook(ex1, ct1))
    (out / "electronica-sample-v2.xlsx").write_bytes(write_import_workbook(ex2, ct2))
    print(f"wrote {out}/electronica-sample-v1.xlsx ({len(ex1)} exhibitor rows, {len(ct1)} contacts)")
    print(f"wrote {out}/electronica-sample-v2.xlsx ({len(ex2)} exhibitor rows, {len(ct2)} contacts)")


if __name__ == "__main__":
    main()
