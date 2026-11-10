"""Excel intake (LEADS_PLAN 7, EXHIBITION_MAPPING_PLAN 3.1-3.2).

One code path for the dry run and the real run: the dry run does all the work inside the
transaction and then rolls it back, keeping only the import_batches row with the counts.

Rules:
- Company key: domain (website, else non-free-mail email), then normalized name.
- One convention_appearance per company per show; hall/booth live on the appearance.
- Catalogue columns update only when not in edited_fields. When the file disagrees with an
  edited field the app value stays and the field is listed in report.conflicts.
- A blank cell never clears a value that is already there.
- raw is always replaced with the latest source row.
- App-owned columns (sap_card_code, role, priority, tags, lead fields, meetings, assignments)
  are never written here.
- Contacts upsert on company + lower(email) and are never deleted.
- Leads are created only when the appearance is new in this batch (the first import of the
  company at this show) and the row has lead activity. Re-imports never create leads.
- "Meeting note" stays in raw only.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (
    Company,
    Contact,
    Convention,
    ConventionAppearance,
    ImportBatch,
    Lead,
    LeadActivity,
)
from . import suggest, venue
from .normalize import (
    clean,
    company_domain,
    json_safe,
    map_lead_status,
    normalize_name,
    parse_date,
    split_categories,
    split_hall_booth,
    truthy,
)
from .xlsx import read_import_workbook

COMPANY_FIELDS = (
    "name", "country", "city", "address", "phone", "primary_email", "website",
    "categories", "description", "profile_url",
)
CONTACT_FIELDS = ("name", "title", "email", "phone")
LOCATION_EDIT_MARKERS = {"hall", "booth", "hall_booth", "hall_booth_raw"}


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _same(old, new) -> bool:
    if isinstance(old, str) and isinstance(new, str):
        return old.strip() == new.strip()
    if isinstance(old, list) or isinstance(new, list):
        return list(old or []) == list(new or [])
    return old == new


def _raw(row: dict) -> dict:
    return {k: json_safe(v) for k, v in row["_raw"].items()}


class Importer:
    def __init__(self, db: Session, convention: Convention, batch: ImportBatch):
        self.db = db
        self.convention = convention
        self.batch = batch
        self.conflicts: list[dict] = []
        self.errors: list[dict] = []
        self.ex = dict(rows=0, created=0, updated=0, unchanged=0, skipped=0, duplicates=0,
                       appearances_created=0, conflicts=0)
        self.ct = dict(rows=0, created=0, updated=0, unchanged=0, skipped=0, duplicates=0, conflicts=0)
        self.leads_created = 0
        # LEADS_PLAN 7: only the first real import of a show creates leads; later re-imports never do.
        self.first_import = not db.scalar(
            select(ImportBatch.id).where(
                ImportBatch.convention_id == convention.id,
                ImportBatch.dry_run.is_(False),
                ImportBatch.id != batch.id,
                ImportBatch.id < (batch.id or 2**31),
                or_(ImportBatch.report.is_(None), ~ImportBatch.report.has_key("failed")),
            ).limit(1)
        )
        self._load()

    # ---- indexes over what is already in the database ----

    def _load(self) -> None:
        db = self.db
        self.by_id: dict[int, Company] = {}
        self.by_domain: dict[str, list[Company]] = {}
        self.by_name: dict[str, list[Company]] = {}
        for c in db.scalars(select(Company).order_by(Company.id)):
            self._index(c)
        self.appearances: dict[int, ConventionAppearance] = {
            a.company_id: a
            for a in db.scalars(
                select(ConventionAppearance).where(ConventionAppearance.convention_id == self.convention.id)
            )
        }
        self.contacts_by_email: dict[tuple[int, str], Contact] = {}
        self.contacts_by_name: dict[tuple[int, str], Contact] = {}  # contacts without an email
        for ct in db.scalars(select(Contact).order_by(Contact.id)):
            self._index_contact(ct)
        self.new_appearances: set[int] = set()  # company ids whose appearance this batch created
        self.lead_done: set[int] = set()  # company ids that got a lead in this batch
        self.seen_companies: dict[int, int] = {}  # company id -> first file row
        self.file_names: dict[str, Company] = {}  # normalized name in this file -> company
        self.seen_contacts: set[int] = set()  # id() of contacts this file already touched
        self.via_merge: set[int] = set()  # companies reached through a manual merge

    def _index(self, c: Company) -> None:
        self.by_id[c.id] = c
        if c.domain and c not in self.by_domain.setdefault(c.domain, []):
            self.by_domain[c.domain].append(c)
        if c.name_normalized and c not in self.by_name.setdefault(c.name_normalized, []):
            self.by_name[c.name_normalized].append(c)

    def _index_contact(self, ct: Contact) -> None:
        if ct.email:
            self.contacts_by_email[(ct.company_id, ct.email.strip().lower())] = ct
        elif ct.name:
            self.contacts_by_name[(ct.company_id, ct.name.strip().lower())] = ct

    def _resolve(self, c: Company) -> Company:
        """Follow manual merges to the surviving company."""
        hops = 0
        while c.merged_into_id and c.merged_into_id in self.by_id and hops < 20:
            c = self.by_id[c.merged_into_id]
            hops += 1
        return c

    def find_company(self, domain: str | None, name_norm: str) -> Company | None:
        match = None
        if domain and self.by_domain.get(domain):
            match = self.by_domain[domain][0]
        else:
            for c in self.by_name.get(name_norm, []):
                # Same name but a different known domain is a different legal entity: keep apart
                # (people merge those by hand).
                if c.domain is None or domain is None or c.domain == domain:
                    match = c
                    break
        if match is None:
            return None
        target = self._resolve(match)
        if target is not match:
            self.via_merge.add(target.id)
        return target

    # ---- field merging ----

    def _merge(self, obj, values: dict, edited: set[str], conflict_ctx: dict | None,
               prefix: str = "", only_blank: bool = False) -> bool:
        """Copy file values onto obj following the re-import rules. Returns True when anything changed."""
        changed = False
        for field, new in values.items():
            if _empty(new):
                continue
            old = getattr(obj, field)
            if _same(old, new):
                continue
            if only_blank and not _empty(old):
                continue
            if field in edited:
                if conflict_ctx is not None:
                    self.conflicts.append({**conflict_ctx, "field": prefix + field,
                                           "app_value": old, "file_value": new})
                continue
            setattr(obj, field, new)
            changed = True
        return changed

    # ---- sheets ----

    def run(self, exhibitors: list[dict], contacts: list[dict]) -> dict:
        for row in exhibitors:
            self.exhibitor_row(row)
        for row in contacts:
            self.contact_row(row)
        self.ex["conflicts"] = sum(1 for c in self.conflicts if not c["field"].startswith("contact."))
        self.ct["conflicts"] = len(self.conflicts) - self.ex["conflicts"]
        return {
            "sheets": {"exhibitors": self.ex, "contacts": self.ct},
            "conflicts": self.conflicts,
            "errors": self.errors,
            "leads_created": self.leads_created,
        }

    def exhibitor_row(self, row: dict) -> None:
        self.ex["rows"] += 1
        name = clean(row.get("company"))
        norm = normalize_name(name)
        if not name or not norm:
            self.ex["skipped"] += 1
            self.errors.append({"row": row["_row"], "sheet": "Exhibitors", "message": "no company name"})
            return
        website = clean(row.get("website"))
        email = clean(row.get("primary_email"))
        domain = company_domain(website, email)
        values = {
            "name": name,
            "country": clean(row.get("country")),
            "city": clean(row.get("city")),
            "address": clean(row.get("address")),
            "phone": clean(row.get("phone")),
            "primary_email": email,
            "website": website,
            "categories": split_categories(row.get("categories")),
            "description": clean(row.get("description")),
            "profile_url": clean(row.get("profile_url")),
        }
        company = self.find_company(domain, norm)
        duplicate = company is not None and company.id in self.seen_companies
        changed = False

        if company is None:
            company = Company(**values, name_normalized=norm, domain=domain, source="excel",
                              import_batch_id=self.batch.id, raw=_raw(row))
            self.db.add(company)
            self.db.flush()
            self._index(company)
            self.ex["created"] += 1
            outcome = "created"
        elif duplicate:
            # The same company twice in one file: fill gaps only, keep the first row's raw.
            self._merge(company, values, set(company.edited_fields or []), None, only_blank=True)
            self.ex["duplicates"] += 1
            self.errors.append({"row": row["_row"], "sheet": "Exhibitors",
                                "message": f"duplicate of row {self.seen_companies[company.id]} ({company.name})"})
            outcome = "duplicate"
        elif company.id in self.via_merge:
            # The row is for a company that was merged into this one: it may fill gaps, but the
            # surviving company's own values (name, address, ...) win. raw stays the survivor's.
            self.via_merge.discard(company.id)
            changed = self._merge(company, values, set(company.edited_fields or []), None, only_blank=True)
            outcome = "changed" if changed else "unchanged"
        else:
            edited = set(company.edited_fields or [])
            ctx = {"company_id": company.id, "company": company.name}
            changed = self._merge(company, values, edited, ctx)
            if "name" not in edited and company.name_normalized != normalize_name(company.name):
                company.name_normalized = normalize_name(company.name)
            if domain and domain != company.domain and not edited & {"domain", "website"}:
                company.domain = domain
                changed = True
            company.raw = _raw(row)
            company.import_batch_id = self.batch.id
            self._index(company)
            outcome = "changed" if changed else "unchanged"

        self.seen_companies.setdefault(company.id, row["_row"])
        self.file_names.setdefault(norm, company)
        appearance_changed = self.appearance(company, row, duplicate)

        if outcome in ("changed", "unchanged"):
            if changed or appearance_changed:
                self.ex["updated"] += 1
            else:
                self.ex["unchanged"] += 1

        if self.first_import and company.id in self.new_appearances and company.id not in self.lead_done:
            self.maybe_lead(company, row)

    def appearance(self, company: Company, row: dict, duplicate: bool) -> bool:
        raw_hb = clean(row.get("hall_booth"))
        hall, booth = split_hall_booth(raw_hb)
        a = self.appearances.get(company.id)
        if a is None:
            a = ConventionAppearance(company_id=company.id, convention_id=self.convention.id,
                                     hall=hall, booth=booth, hall_booth_raw=raw_hb,
                                     met_at_booth=truthy(row.get("met_at_booth")))
            self.db.add(a)  # flushed with the next company or lead; its id is not needed before
            self.appearances[company.id] = a
            self.new_appearances.add(company.id)
            self.ex["appearances_created"] += 1
            return True
        changed = False
        edited = set(a.edited_fields or []) | set(company.edited_fields or [])
        if raw_hb and raw_hb != a.hall_booth_raw and not (duplicate and a.hall_booth_raw):
            if edited & LOCATION_EDIT_MARKERS:
                if not duplicate:
                    self.conflicts.append({"company_id": company.id, "company": company.name,
                                           "field": "hall_booth", "app_value": a.hall_booth_raw,
                                           "file_value": raw_hb})
            else:
                a.hall, a.booth, a.hall_booth_raw = hall, booth, raw_hb
                changed = True
        # met_at_booth: the file may switch it on, never off, and never after a person set it.
        if truthy(row.get("met_at_booth")) and not a.met_at_booth and "met_at_booth" not in edited:
            a.met_at_booth = True
            changed = True
        return changed

    def maybe_lead(self, company: Company, row: dict) -> None:
        status_raw = clean(row.get("lead_status"))
        owner = clean(row.get("owner"))
        notes = clean(row.get("notes"))
        follow_raw = row.get("follow_up_date")
        met = truthy(row.get("met_at_booth"))
        if not (met or status_raw or owner or notes or clean(follow_raw)):
            return
        data: dict = {"source": "excel", "batch_id": self.batch.id, "row": row["_row"]}
        status = map_lead_status(status_raw)
        if status_raw and not status:
            data["excel_lead_status"] = status_raw
            notes = f"{notes}\n\nExcel lead status: {status_raw}" if notes else f"Excel lead status: {status_raw}"
        if not status:
            status = "met" if met else "new"
        follow_up_on = None
        try:
            follow_up_on = parse_date(follow_raw)
        except ValueError:
            data["excel_follow_up_date"] = str(follow_raw)
            self.errors.append({"row": row["_row"], "sheet": "Exhibitors",
                                "message": f"Follow-up date not understood: {follow_raw!r}"})
        a = self.appearances[company.id]
        if a.id is None:
            self.db.flush()
        lead = Lead(company_id=company.id, appearance_id=a.id, owner=owner, status=status,
                    notes=notes, follow_up_on=follow_up_on)
        self.db.add(lead)
        self.db.flush()
        self.db.add(LeadActivity(lead_id=lead.id, kind="opened", actor="import", data=data))
        self.lead_done.add(company.id)
        self.leads_created += 1

    def contact_row(self, row: dict) -> None:
        self.ct["rows"] += 1
        company_name = clean(row.get("company"))
        name = clean(row.get("name"))
        email = clean(row.get("email"))
        if not company_name or not (name or email):
            self.ct["skipped"] += 1
            self.errors.append({"row": row["_row"], "sheet": "Contacts",
                                "message": "needs Company and a Name or Email"})
            return
        norm = normalize_name(company_name)
        company = self.file_names.get(norm) or self.find_company(company_domain(None, email), norm)
        if company is None:
            self.ct["skipped"] += 1
            self.errors.append({"row": row["_row"], "sheet": "Contacts",
                                "message": f"company not found: {company_name}"})
            return
        values = {"name": name, "title": clean(row.get("title")), "email": email, "phone": clean(row.get("phone"))}

        contact = None
        if email:
            contact = self.contacts_by_email.get((company.id, email.lower()))
        if contact is None and name:
            # A contact we know only by name gets its email from the file.
            contact = self.contacts_by_name.get((company.id, name.lower()))

        if contact is None:
            contact = Contact(company_id=company.id, source="excel", raw=_raw(row), **values)
            self.db.add(contact)
            self.ct["created"] += 1
        elif id(contact) in self.seen_contacts:
            self._merge(contact, values, set(contact.edited_fields or []), None, only_blank=True)
            self.ct["duplicates"] += 1
        else:
            ctx = {"company_id": company.id, "company": company.name, "contact_id": contact.id}
            if self._merge(contact, values, set(contact.edited_fields or []), ctx, prefix="contact."):
                self.ct["updated"] += 1
            else:
                self.ct["unchanged"] += 1
            contact.raw = _raw(row)
        if contact.email:
            self.contacts_by_name.pop((company.id, (contact.name or "").strip().lower()), None)
        self._index_contact(contact)
        self.seen_contacts.add(id(contact))  # python identity: new contacts have no id until flushed


def run_import(db: Session, batch: ImportBatch, data: bytes) -> ImportBatch:
    """Run the batch's file. The batch row must already be committed: a dry run rolls back
    everything else. Returns the (refreshed) batch with counts and report."""
    batch_id, dry_run = batch.id, batch.dry_run
    convention = db.get(Convention, batch.convention_id)
    exhibitors, contacts = read_import_workbook(data)
    importer = Importer(db, convention, batch)
    report = importer.run(exhibitors, contacts)

    if dry_run:
        db.rollback()
    else:
        db.flush()
        report["suggested"] = suggest.run_suggestions(db, convention.id)
        report["venue"] = venue.rebuild(db, convention.id)

    batch = db.get(ImportBatch, batch_id)
    ex = report["sheets"]["exhibitors"]
    batch.rows = ex["rows"]
    batch.created = ex["created"]
    batch.updated = ex["updated"]
    batch.skipped = ex["skipped"] + ex["duplicates"]
    batch.conflicts = len(report["conflicts"])
    batch.report = {**(batch.report or {}), **report}
    db.commit()
    return batch
