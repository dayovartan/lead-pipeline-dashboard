"""Companies directory, detail window, edits, merge, contacts, SAP link and Obsidian export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import any_, func, literal, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import User, current_user, require_editor
from app.db import get_session
from app.models import (
    AppearanceMapping,
    AppearanceTag,
    Company,
    Contact,
    Convention,
    ConventionAppearance,
    DispatchAssignment,
    HardwareTag,
    Lead,
    LeadActivity,
    Meeting,
    MeetingContact,
    TagGroup,
)
from app.routers.leads import lead_items
from app.routers.meetings import markdown_response, newest_first, serialize_meetings
from app.services import export_md
from app.services.kind import KINDS, derive_kind, kind_by_company_subquery

router = APIRouter(tags=["companies"])

CATALOGUE_FIELDS = (
    "name",
    "domain",
    "country",
    "city",
    "address",
    "phone",
    "primary_email",
    "website",
    "categories",
    "description",
    "profile_url",
)
CONTACT_FIELDS = ("name", "title", "email", "phone")
SORTS = {
    "name": (Company.name_normalized, Company.id),
    "country": (Company.country.asc().nulls_last(), Company.name_normalized, Company.id),
    "updated": (Company.updated_at.desc(), Company.id),
}


class CompanyPatch(BaseModel):
    name: str | None = Field(None, min_length=1)
    domain: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    primary_email: str | None = None
    website: str | None = None
    categories: list[str] | None = None
    description: str | None = None
    profile_url: str | None = None


class ContactIn(BaseModel):
    name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None


class MergeIn(BaseModel):
    into_id: int


class SapLinkIn(BaseModel):
    card_code: str = Field(min_length=1, max_length=50)


def _like(q: str) -> str:
    return "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def normalize_name(name: str) -> str:
    try:  # owned by the import agent; fall back to a plain lowercase if it is not there
        from app.services.normalize import normalize_name as nn

        return nn(name)
    except ImportError:
        return " ".join("".join(ch if ch.isalnum() else " " for ch in name.lower()).split())


def _get_company(db: Session, company_id: int) -> Company:
    c = db.get(Company, company_id)
    if c is None:
        raise HTTPException(404, "company not found")
    return c


def _truthy(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    return v.lower() in ("1", "true", "yes", "y")


# ---- List and facets ---------------------------------------------------------------------


def _appearances_by_company(db: Session, company_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {i: [] for i in company_ids}
    if not company_ids:
        return out
    rows = db.execute(
        select(ConventionAppearance, Convention.slug, Convention.name, Convention.starts_on)
        .join(Convention, Convention.id == ConventionAppearance.convention_id)
        .where(ConventionAppearance.company_id.in_(company_ids))
        .order_by(Convention.starts_on.desc().nulls_last(), Convention.id.desc())
    ).all()
    for ap, slug, cname, starts_on in rows:
        out[ap.company_id].append(
            {
                "id": ap.id,
                "convention_id": ap.convention_id,
                "convention_slug": slug,
                "convention_name": cname,
                "convention_starts_on": starts_on,
                "hall": ap.hall,
                "booth": ap.booth,
                "hall_booth_raw": ap.hall_booth_raw,
                "role": ap.role,
                "priority": ap.priority,
                "met_at_booth": ap.met_at_booth,
            }
        )
    return out


def _latest_leads(db: Session, company_ids) -> dict[int, Lead]:
    out: dict[int, Lead] = {}
    if not company_ids:
        return out
    for lead in db.scalars(
        select(Lead).where(Lead.company_id.in_(company_ids)).order_by(Lead.updated_at.desc(), Lead.id.desc())
    ):
        out.setdefault(lead.company_id, lead)
    return out


def _company_filters(
    stmt,
    *,
    q=None,
    convention=None,
    role=None,
    kind=None,
    country=None,
    category=None,
    tag=None,
    has_lead=None,
    sap_linked=None,
    met=None,
):
    stmt = stmt.where(Company.merged_into_id.is_(None))
    conv_id = None
    if convention:
        conv_id = select(Convention.id).where(Convention.slug == convention).scalar_subquery()
        stmt = stmt.where(
            Company.id.in_(select(ConventionAppearance.company_id).where(ConventionAppearance.convention_id == conv_id))
        )
    if q and q.strip():
        pat = _like(q)
        contact_hit = select(Contact.company_id).where(or_(Contact.name.ilike(pat), Contact.email.ilike(pat)))
        conds = [
            Company.name.ilike(pat),
            Company.name_normalized.ilike(pat),
            Company.domain.ilike(pat),
            Company.id.in_(contact_hit),
        ]
        normalized = normalize_name(q)
        if normalized:  # "Acme GmbH" also finds "ACME" (legal suffix and punctuation stripped)
            conds.append(Company.name_normalized.ilike(_like(normalized)))
        stmt = stmt.where(or_(*conds))
    if role:
        roles = [r.strip() for r in role.split(",") if r.strip()]
        conds = []
        named = [r for r in roles if r != "unmapped"]
        if named:
            conds.append(ConventionAppearance.role.in_(named))
        if "unmapped" in roles:
            conds.append(ConventionAppearance.role.is_(None))
        sub = select(ConventionAppearance.company_id).where(or_(*conds))
        if conv_id is not None:
            sub = sub.where(ConventionAppearance.convention_id == conv_id)
        stmt = stmt.where(Company.id.in_(sub))
    if kind:
        kinds = [k.strip() for k in kind.split(",") if k.strip()]
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            raise HTTPException(422, f"unknown kind {bad[0]!r}")
        ks = kind_by_company_subquery()
        cond = Company.id.in_(select(ks.c.company_id).where(ks.c.kind.in_(kinds)))
        if "unmapped" in kinds:  # a company with no appearance at all is unmapped too
            cond = or_(cond, ~Company.id.in_(select(ks.c.company_id)))
        stmt = stmt.where(cond)
    if country:
        stmt = stmt.where(func.lower(Company.country) == country.strip().lower())
    if category:
        stmt = stmt.where(literal(category.strip()) == any_(Company.categories))
    if tag:
        tag_cond = HardwareTag.id == int(tag) if tag.isdigit() else func.lower(HardwareTag.name) == tag.strip().lower()
        sub = (
            select(ConventionAppearance.company_id)
            .join(AppearanceTag, AppearanceTag.appearance_id == ConventionAppearance.id)
            .join(HardwareTag, HardwareTag.id == AppearanceTag.tag_id)
            .where(tag_cond)
        )
        if conv_id is not None:
            sub = sub.where(ConventionAppearance.convention_id == conv_id)
        stmt = stmt.where(Company.id.in_(sub))
    if has_lead is not None:
        sub = Company.id.in_(select(Lead.company_id))
        stmt = stmt.where(sub if has_lead else ~sub)
    if sap_linked is not None:
        stmt = stmt.where(Company.sap_card_code.is_not(None) if sap_linked else Company.sap_card_code.is_(None))
    if met is not None:
        met_ap = select(ConventionAppearance.company_id).where(ConventionAppearance.met_at_booth.is_(True))
        if conv_id is not None:
            met_ap = met_ap.where(ConventionAppearance.convention_id == conv_id)
        cond = or_(Company.id.in_(met_ap), Company.id.in_(select(Meeting.company_id)))
        stmt = stmt.where(cond if met else ~cond)
    return stmt


@router.get("/companies")
def list_companies(
    q: str | None = None,
    convention: str | None = None,
    role: str | None = None,
    kind: str | None = None,
    country: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    has_lead: str | None = None,
    sap_linked: str | None = None,
    met: str | None = None,
    sort: str = "name",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {', '.join(SORTS)}")
    stmt = _company_filters(
        select(Company),
        q=q,
        convention=convention,
        role=role,
        kind=kind,
        country=country,
        category=category,
        tag=tag,
        has_lead=_truthy(has_lead),
        sap_linked=_truthy(sap_linked),
        met=_truthy(met),
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(*SORTS[sort]).offset((page - 1) * page_size).limit(page_size)).all()
    ids = [c.id for c in rows]
    apps = _appearances_by_company(db, ids)
    leads = _latest_leads(db, ids)
    items = []
    for c in rows:
        lead = leads.get(c.id)
        items.append(
            {
                "id": c.id,
                "name": c.name,
                "domain": c.domain,
                "country": c.country,
                "city": c.city,
                "website": c.website,
                "categories": c.categories or [],
                "kind": derive_kind(a["role"] for a in apps[c.id]),
                "sap_card_code": c.sap_card_code,
                "lead_id": lead.id if lead else None,
                "lead_status": lead.status if lead else None,
                "appearances": [
                    {k: a[k] for k in ("convention_slug", "hall", "booth", "role", "priority")} for a in apps[c.id]
                ],
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/companies/facets")
def facets(convention: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    base = _company_filters(select(Company.id), convention=convention).subquery()
    countries = db.execute(
        select(Company.country, func.count())
        .where(Company.id.in_(select(base.c.id)), Company.country.is_not(None))
        .group_by(Company.country)
        .order_by(func.count().desc(), Company.country)
    ).all()
    cat = func.unnest(Company.categories).label("category")
    cat_rows = select(cat).where(Company.id.in_(select(base.c.id))).subquery()
    categories = db.execute(
        select(cat_rows.c.category, func.count()).group_by(cat_rows.c.category).order_by(func.count().desc(), cat_rows.c.category)
    ).all()
    role_q = select(func.coalesce(ConventionAppearance.role, literal("unmapped")).label("role"), func.count()).where(
        ConventionAppearance.company_id.in_(select(base.c.id))
    )
    if convention:
        role_q = role_q.join(Convention, Convention.id == ConventionAppearance.convention_id).where(
            Convention.slug == convention
        )
    roles = db.execute(role_q.group_by("role").order_by(func.count().desc())).all()
    as_list = lambda rows: [{"value": v, "count": n} for v, n in rows]  # noqa: E731
    return {"countries": as_list(countries), "categories": as_list(categories), "roles": as_list(roles)}


# ---- Detail ------------------------------------------------------------------------------


def _contact_dict(c: Contact) -> dict:
    return {
        "id": c.id,
        "company_id": c.company_id,
        "name": c.name,
        "title": c.title,
        "email": c.email,
        "phone": c.phone,
        "source": c.source,
        "edited_fields": c.edited_fields or [],
        "created_at": c.created_at,
    }


def company_detail(db: Session, c: Company) -> dict:
    apps = _appearances_by_company(db, [c.id])[c.id]
    ap_ids = [a["id"] for a in apps]
    tags: dict[int, list[dict]] = {i: [] for i in ap_ids}
    mappings: dict[int, dict] = {}
    dispatch: dict[int, dict] = {}
    if ap_ids:
        for at, t, gname in db.execute(
            select(AppearanceTag, HardwareTag, TagGroup.name)
            .join(HardwareTag, HardwareTag.id == AppearanceTag.tag_id)
            .outerjoin(TagGroup, TagGroup.id == HardwareTag.group_id)
            .where(AppearanceTag.appearance_id.in_(ap_ids))
            .order_by(HardwareTag.name)
        ).all():
            tags[at.appearance_id].append(
                {"id": t.id, "name": t.name, "group": gname, "suggested": at.suggested, "confirmed": at.confirmed}
            )
        for m in db.scalars(select(AppearanceMapping).where(AppearanceMapping.appearance_id.in_(ap_ids))):
            mappings[m.appearance_id] = {
                "suggested_role": m.suggested_role,
                "suggested_priority": m.suggested_priority,
                "confirmed_by": m.confirmed_by,
                "confirmed_at": m.confirmed_at,
            }
        for d in db.scalars(select(DispatchAssignment).where(DispatchAssignment.appearance_id.in_(ap_ids))):
            dispatch[d.appearance_id] = {
                "assignee": d.assignee,
                "visited": d.visited,
                "visited_at": d.visited_at,
                "note": d.note,
            }
    for a in apps:
        a["tags"] = tags.get(a["id"], [])
        a["mapping"] = mappings.get(a["id"])
        a["dispatch"] = dispatch.get(a["id"])
    contacts = db.scalars(select(Contact).where(Contact.company_id == c.id).order_by(Contact.name, Contact.id)).all()
    leads = db.scalars(select(Lead).where(Lead.company_id == c.id).order_by(Lead.updated_at.desc(), Lead.id.desc())).all()
    out = {col.name: getattr(c, col.key) for col in Company.__table__.columns if col.name != "raw"}
    out["categories"] = c.categories or []
    out["edited_fields"] = c.edited_fields or []
    out["kind"] = derive_kind(a["role"] for a in apps)
    out["contacts"] = [_contact_dict(x) for x in contacts]
    out["appearances"] = apps
    out["leads"] = lead_items(db, list(leads))
    return out


@router.get("/companies/{company_id}")
def get_company(company_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return company_detail(db, _get_company(db, company_id))


def _apply_edits(obj, incoming: dict, fields: tuple[str, ...]) -> list[str]:
    """Set changed fields and add them to edited_fields. Returns the changed field names."""
    changed = []
    for k, v in incoming.items():
        if k not in fields:
            continue
        if isinstance(v, str):
            v = v.strip() or None
        if getattr(obj, k) != v:
            setattr(obj, k, v)
            changed.append(k)
    if changed:
        obj.edited_fields = sorted(set(obj.edited_fields or []) | set(changed))
    return changed


@router.patch("/companies/{company_id}")
def patch_company(
    company_id: int, body: CompanyPatch, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    c = _get_company(db, company_id)
    incoming = body.model_dump(exclude_unset=True)
    if "name" in incoming and not (incoming["name"] or "").strip():
        raise HTTPException(422, "name cannot be empty")
    if "categories" in incoming:
        incoming["categories"] = [x.strip() for x in incoming["categories"] or [] if x and x.strip()]
    if "domain" in incoming and incoming["domain"]:
        incoming["domain"] = incoming["domain"].strip().lower().removeprefix("www.")
    changed = _apply_edits(c, incoming, CATALOGUE_FIELDS)
    if "name" in changed:
        c.name_normalized = normalize_name(c.name)
    db.commit()
    return company_detail(db, c)


# ---- Merge -------------------------------------------------------------------------------


@router.post("/companies/{company_id}/merge")
def merge_company(
    company_id: int, body: MergeIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    """Manual merge of `company_id` into `into_id`. The source row stays, pointing at the target.

    Moved to the target: contacts (a contact whose email the target already has is folded into
    the target's contact), appearances (except at a show where the target already has one; leads
    and meetings pointing at such an appearance are repointed to the target's), leads, meetings.
    Empty catalogue fields and the SAP CardCode of the target are filled from the source.
    """
    src = _get_company(db, company_id)
    dst = _get_company(db, body.into_id)
    if src.id == dst.id:
        raise HTTPException(422, "cannot merge a company into itself")
    if src.merged_into_id:
        raise HTTPException(409, "company was already merged")
    if dst.merged_into_id:
        raise HTTPException(409, "target company was merged into another company")

    # Contacts
    dst_by_email = {
        (x.email or "").lower(): x for x in db.scalars(select(Contact).where(Contact.company_id == dst.id)) if x.email
    }
    for ct in db.scalars(select(Contact).where(Contact.company_id == src.id)).all():
        twin = dst_by_email.get((ct.email or "").lower()) if ct.email else None
        if twin is None:
            ct.company_id = dst.id
            continue
        db.execute(update(Lead).where(Lead.contact_id == ct.id).values(contact_id=twin.id))
        already = set(db.scalars(select(MeetingContact.meeting_id).where(MeetingContact.contact_id == twin.id)))
        for mc in db.scalars(select(MeetingContact).where(MeetingContact.contact_id == ct.id)).all():
            if mc.meeting_id in already:
                db.delete(mc)
            else:
                mc.contact_id = twin.id
        db.flush()
        db.delete(ct)

    # Appearances
    dst_by_conv = {a.convention_id: a for a in db.scalars(select(ConventionAppearance).where(ConventionAppearance.company_id == dst.id))}
    for ap in db.scalars(select(ConventionAppearance).where(ConventionAppearance.company_id == src.id)).all():
        twin = dst_by_conv.get(ap.convention_id)
        if twin is None:
            ap.company_id = dst.id
        else:
            db.execute(update(Lead).where(Lead.appearance_id == ap.id).values(appearance_id=twin.id))
            db.execute(update(Meeting).where(Meeting.appearance_id == ap.id).values(appearance_id=twin.id))

    # Leads and meetings
    for lead in db.scalars(select(Lead).where(Lead.company_id == src.id)).all():
        lead.company_id = dst.id
        db.add(
            LeadActivity(
                lead_id=lead.id, kind="edited", actor=user.email, data={"merged_from_company_id": src.id, "into": dst.id}
            )
        )
    db.execute(update(Meeting).where(Meeting.company_id == src.id).values(company_id=dst.id))

    for f in CATALOGUE_FIELDS:
        if f != "name" and not getattr(dst, f) and getattr(src, f):
            setattr(dst, f, getattr(src, f))
    if not dst.sap_card_code and src.sap_card_code:
        dst.sap_card_code = src.sap_card_code
    src.merged_into_id = dst.id
    db.commit()
    return company_detail(db, dst)


# ---- Contacts ----------------------------------------------------------------------------


@router.post("/companies/{company_id}/contacts", status_code=201)
def add_contact(
    company_id: int, body: ContactIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    _get_company(db, company_id)
    data = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in body.model_dump().items()}
    if not data.get("name") and not data.get("email"):
        raise HTTPException(422, "a contact needs a name or an email")
    ct = Contact(company_id=company_id, source="app", **data)
    db.add(ct)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "this company already has a contact with that email")
    return _contact_dict(ct)


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    ct = db.get(Contact, contact_id)
    if ct is None:
        raise HTTPException(404, "contact not found")
    company = db.get(Company, ct.company_id)
    out = _contact_dict(ct)
    out["company"] = {"id": company.id, "name": company.name}
    leads = db.scalars(select(Lead).where(Lead.contact_id == ct.id).order_by(Lead.updated_at.desc())).all()
    out["leads"] = lead_items(db, list(leads))
    return out


@router.patch("/contacts/{contact_id}")
def patch_contact(
    contact_id: int, body: ContactIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    ct = db.get(Contact, contact_id)
    if ct is None:
        raise HTTPException(404, "contact not found")
    _apply_edits(ct, body.model_dump(exclude_unset=True), CONTACT_FIELDS)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "this company already has a contact with that email")
    return _contact_dict(ct)


# ---- SAP link ----------------------------------------------------------------------------


@router.post("/companies/{company_id}/sap-link")
def sap_link(
    company_id: int, body: SapLinkIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    """Store the CardCode a person picked from resolve_customer. Nothing else from SAP is kept."""
    c = _get_company(db, company_id)
    c.sap_card_code = body.card_code.strip()
    db.commit()
    return {"id": c.id, "sap_card_code": c.sap_card_code}


@router.delete("/companies/{company_id}/sap-link")
def sap_unlink(company_id: int, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    c = _get_company(db, company_id)
    c.sap_card_code = None
    db.commit()
    return {"id": c.id, "sap_card_code": None}


# ---- Export ------------------------------------------------------------------------------


@router.get("/companies/{company_id}/export.md")
def export_company(company_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    c = _get_company(db, company_id)
    detail = company_detail(db, c)
    meetings = serialize_meetings(db, db.scalars(newest_first(select(Meeting).where(Meeting.company_id == c.id))).all())
    return markdown_response(export_md.render_company(detail, meetings), f"{export_md.safe_filename(c.name)}.md")

