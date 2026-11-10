"""Leads: followed companies (LEADS_PLAN 8, 9). Follow, never close.

Every change writes lead_activity with actor = the user's email:
opened, edited, linked, unlinked, suggestion_accepted, suggestion_dismissed.
Also the live MCP reads of the company window (SAP card, Find in SAP, supplier prices).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import User, current_user, require_editor
from app.db import get_session
from app.models import (
    LEAD_STATUSES,
    CaseSuggestion,
    Company,
    Contact,
    Convention,
    ConventionAppearance,
    Lead,
    LeadActivity,
    LeadCase,
    Meeting,
)
from app.services import matching
from app.services.followup import refresh_follow_up
from app.services.mcp import McpClient, get_mcp, unavailable

router = APIRouter(tags=["leads"])

MAX_PAGE_SIZE = 500  # the board loads one big page


class FollowIn(BaseModel):
    owner: str | None = None
    contact_id: int | None = None
    appearance_id: int | None = None
    notes: str | None = None


class LeadPatch(BaseModel):
    status: str | None = None
    owner: str | None = None
    follow_up_on: date | None = None
    notes: str | None = None
    contact_id: int | None = None
    appearance_id: int | None = None


class LinkIn(BaseModel):
    loop_case_id: str = Field(min_length=1, max_length=200)


def _like(q: str) -> str:
    return "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def activity(db: Session, lead_id: int, kind: str, actor: str | None, data: dict | None = None) -> None:
    db.add(LeadActivity(lead_id=lead_id, kind=kind, actor=actor, data=data))


def _first_line(md: str | None, limit: int = 160) -> str | None:
    for line in (md or "").splitlines():
        line = line.strip().lstrip("#-*> ").strip()
        if line:
            return line[:limit]
    return None


def lead_items(db: Session, leads: list[Lead]) -> list[dict]:
    """The list/board shape of docs/API.md, plus a few ids the windows need."""
    if not leads:
        return []
    lead_ids = [lead.id for lead in leads]
    company_ids = {lead.company_id for lead in leads}
    companies = dict(db.execute(select(Company.id, Company.name).where(Company.id.in_(company_ids))).all())
    contact_ids = {lead.contact_id for lead in leads if lead.contact_id}
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_(contact_ids)))} if contact_ids else {}
    ap_ids = {lead.appearance_id for lead in leads if lead.appearance_id}
    slugs = (
        dict(
            db.execute(
                select(ConventionAppearance.id, Convention.slug)
                .join(Convention, Convention.id == ConventionAppearance.convention_id)
                .where(ConventionAppearance.id.in_(ap_ids))
            ).all()
        )
        if ap_ids
        else {}
    )
    case_counts = dict(
        db.execute(
            select(LeadCase.lead_id, func.count()).where(LeadCase.lead_id.in_(lead_ids)).group_by(LeadCase.lead_id)
        ).all()
    )
    pending = dict(
        db.execute(
            select(CaseSuggestion.lead_id, func.count())
            .where(
                CaseSuggestion.lead_id.in_(lead_ids),
                CaseSuggestion.status == "pending",
                CaseSuggestion.loop_case_id.not_in(select(LeadCase.loop_case_id).where(LeadCase.lead_id == CaseSuggestion.lead_id)),
            )
            .group_by(CaseSuggestion.lead_id)
        ).all()
    )
    meetings = db.execute(
        select(Meeting.company_id, Meeting.lead_id, Meeting.summary_md)
        .where(Meeting.company_id.in_(company_ids))
        .order_by(Meeting.met_on.desc(), Meeting.starts_at.desc().nulls_last(), Meeting.id.desc())
    ).all()

    def last_note(lead: Lead) -> str | None:
        for m in meetings:  # newest first; the lead's own meetings, then unattached company ones
            if m.lead_id == lead.id and _first_line(m.summary_md):
                return _first_line(m.summary_md)
        for m in meetings:
            if m.company_id == lead.company_id and m.lead_id is None and _first_line(m.summary_md):
                return _first_line(m.summary_md)
        return None

    today = date.today()
    out = []
    for lead in leads:
        c = contacts.get(lead.contact_id)
        out.append(
            {
                "id": lead.id,
                "company": {"id": lead.company_id, "name": companies.get(lead.company_id)},
                "contact": {"id": c.id, "name": c.name, "email": c.email} if c else None,
                "owner": lead.owner,
                "status": lead.status,
                "notes": lead.notes,
                "follow_up_on": lead.follow_up_on,
                "overdue": bool(lead.follow_up_on and lead.follow_up_on < today),
                "last_note": last_note(lead),
                "linked_case_count": case_counts.get(lead.id, 0),
                "pending_suggestion_count": pending.get(lead.id, 0),
                "convention_slug": slugs.get(lead.appearance_id),
                "company_id": lead.company_id,
                "contact_id": lead.contact_id,
                "appearance_id": lead.appearance_id,
                "created_at": lead.created_at,
                "updated_at": lead.updated_at,
            }
        )
    return out


def _get_lead(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return lead


def _get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "company not found")
    return company


def _check_lead_refs(db: Session, company_id: int, contact_id: int | None, appearance_id: int | None) -> None:
    if contact_id is not None:
        c = db.get(Contact, contact_id)
        if c is None or c.company_id != company_id:
            raise HTTPException(422, "contact does not belong to this company")
    if appearance_id is not None:
        ap = db.get(ConventionAppearance, appearance_id)
        if ap is None or ap.company_id != company_id:
            raise HTTPException(422, "appearance does not belong to this company")


# ---- Follow, list, edit ------------------------------------------------------------------


@router.post("/companies/{company_id}/leads", status_code=201)
def follow(company_id: int, body: FollowIn, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    """The "Follow" button. No uniqueness rule: a company can be followed more than once."""
    company = _get_company(db, company_id)
    if company.merged_into_id:
        raise HTTPException(409, "company was merged; follow the company it was merged into")
    _check_lead_refs(db, company_id, body.contact_id, body.appearance_id)
    lead = Lead(
        company_id=company_id,
        owner=body.owner,
        contact_id=body.contact_id,
        appearance_id=body.appearance_id,
        notes=body.notes,
        status="new",
    )
    db.add(lead)
    db.flush()
    activity(db, lead.id, "opened", user.email, body.model_dump(exclude_none=True))
    refresh_follow_up(db, lead, user.email)  # meetings already logged for the company
    db.commit()
    return lead_items(db, [lead])[0]


@router.get("/leads")
def list_leads(
    status: str | None = None,
    owner: str | None = None,
    convention: str | None = None,
    company_id: int | None = None,
    q: str | None = None,
    include_parked: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    stmt = select(Lead).join(Company, Company.id == Lead.company_id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in statuses if s not in LEAD_STATUSES]
        if bad:
            raise HTTPException(422, f"unknown status {bad[0]!r}")
        stmt = stmt.where(Lead.status.in_(statuses))
    elif not include_parked:
        stmt = stmt.where(Lead.status != "parked")
    if owner:
        stmt = stmt.where(func.lower(Lead.owner) == owner.strip().lower())
    if company_id is not None:
        stmt = stmt.where(Lead.company_id == company_id)
    if convention:
        at_show = (
            select(ConventionAppearance.company_id)
            .join(Convention, Convention.id == ConventionAppearance.convention_id)
            .where(Convention.slug == convention)
        )
        stmt = stmt.where(Lead.company_id.in_(at_show))
    if q and q.strip():
        pat = _like(q)
        contact_hit = select(Contact.company_id).where(or_(Contact.name.ilike(pat), Contact.email.ilike(pat)))
        stmt = stmt.where(
            or_(
                Company.name.ilike(pat),
                Company.name_normalized.ilike(pat),
                Company.domain.ilike(pat),
                Lead.notes.ilike(pat),
                Lead.owner.ilike(pat),
                Lead.company_id.in_(contact_hit),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Lead.follow_up_on.asc().nulls_last(), Lead.updated_at.desc(), Lead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": lead_items(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return lead_items(db, [_get_lead(db, lead_id)])[0]


@router.patch("/leads/{lead_id}")
def patch_lead(
    lead_id: int, body: LeadPatch, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    lead = _get_lead(db, lead_id)
    incoming = body.model_dump(exclude_unset=True)
    if "status" in incoming and incoming["status"] not in LEAD_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(LEAD_STATUSES)}")
    _check_lead_refs(db, lead.company_id, incoming.get("contact_id"), incoming.get("appearance_id"))
    changes = {}
    for k, v in incoming.items():
        old = getattr(lead, k)
        if old != v:
            changes[k] = [_json(old), _json(v)]
            setattr(lead, k, v)
    if changes:
        activity(db, lead.id, "edited", user.email, {"changes": changes, "auto": False})
        db.flush()
        if "follow_up_on" in changes and lead.follow_up_on is None:
            refresh_follow_up(db, lead, user.email)  # cleared by hand: the actions take over
        db.commit()
    return lead_items(db, [lead])[0]


def _json(v):
    return v.isoformat() if isinstance(v, date) else v


@router.get("/leads/{lead_id}/activity")
def lead_activity(lead_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    _get_lead(db, lead_id)
    rows = db.scalars(
        select(LeadActivity).where(LeadActivity.lead_id == lead_id).order_by(LeadActivity.at.desc(), LeadActivity.id.desc())
    ).all()
    return [{"id": a.id, "kind": a.kind, "at": a.at, "actor": a.actor, "data": a.data} for a in rows]


# ---- Linked cases ------------------------------------------------------------------------


def _story_summary(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    keys = ("loop_case_id", "where", "briefing", "standing", "customer", "card_code", "kind")
    out = {k: data.get(k) for k in keys if k in data}
    events = data.get("events")
    if isinstance(events, list) and events:
        last = events[-1] if isinstance(events[-1], dict) else {}
        out["last_activity_at"] = last.get("at")
        out["last_activity"] = last.get("sentence")
    return out or data


def _doc(data) -> dict | None:
    """find_quotation / find_order answer: {"found": bool, "doc": {...}}."""
    if isinstance(data, dict) and data.get("found") and isinstance(data.get("doc"), dict):
        return data["doc"]
    return None


@router.get("/leads/{lead_id}/cases")
def lead_cases(
    lead_id: int, db: Session = Depends(get_session), user: User = Depends(current_user), mcp: McpClient = Depends(get_mcp)
) -> list[dict]:
    lead = _get_lead(db, lead_id)
    links = db.scalars(select(LeadCase).where(LeadCase.lead_id == lead_id).order_by(LeadCase.linked_at.desc())).all()
    since = ((lead.created_at.date() if lead.created_at else date.today()) - timedelta(days=365)).isoformat()
    out = []
    for link in links:
        story = mcp.call("cases", "case_story", {"loop_case_id": link.loop_case_id})
        quote = mcp.call("sap", "find_quotation", {"since": since, "case_id": link.loop_case_id})
        order = mcp.call("sap", "find_order", {"since": since, "case_id": link.loop_case_id})
        reasons = [r["reason"] for r in (story, quote, order) if not r["available"]]
        out.append(
            {
                "loop_case_id": link.loop_case_id,
                "how": link.how,
                "linked_at": link.linked_at,
                "linked_by": link.linked_by,
                "story": _story_summary(story.get("data")) if story["available"] else None,
                "quotation": _doc(quote.get("data")) if quote["available"] else None,
                "order": _doc(order.get("data")) if order["available"] else None,
                "available": not reasons,
                "reason": reasons[0] if reasons else None,
            }
        )
    return out


def _link(db: Session, lead_id: int, loop_case_id: str, how: str, actor: str) -> bool:
    res = db.execute(
        insert(LeadCase)
        .values(lead_id=lead_id, loop_case_id=loop_case_id, how=how, linked_by=actor)
        .on_conflict_do_nothing(index_elements=["lead_id", "loop_case_id"])
        .returning(LeadCase.loop_case_id)
    )
    return res.scalar() is not None  # rowcount is not reliable here


@router.post("/leads/{lead_id}/cases", status_code=201)
def link_case(
    lead_id: int, body: LinkIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    """Link an existing loop case (intake-...). There is no create-case path."""
    _get_lead(db, lead_id)
    cid = body.loop_case_id.strip()
    if not cid or any(ch.isspace() for ch in cid):
        raise HTTPException(422, "loop_case_id must be a case id such as intake-...")
    created = _link(db, lead_id, cid, "manual", user.email)
    if created:
        activity(db, lead_id, "linked", user.email, {"loop_case_id": cid, "how": "manual"})
        # A pending suggestion for the same case is settled by the manual link.
        for s in db.scalars(
            select(CaseSuggestion).where(
                CaseSuggestion.lead_id == lead_id, CaseSuggestion.loop_case_id == cid, CaseSuggestion.status == "pending"
            )
        ):
            s.status = "accepted"
    db.commit()
    link = db.get(LeadCase, (lead_id, cid))
    return {"loop_case_id": link.loop_case_id, "how": link.how, "linked_at": link.linked_at, "linked_by": link.linked_by}


@router.delete("/leads/{lead_id}/cases/{loop_case_id}", status_code=204)
def unlink_case(
    lead_id: int, loop_case_id: str, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> None:
    link = db.get(LeadCase, (lead_id, loop_case_id))
    if link is None:
        raise HTTPException(404, "case not linked to this lead")
    db.delete(link)
    activity(db, lead_id, "unlinked", user.email, {"loop_case_id": loop_case_id, "how": link.how})
    db.commit()


# ---- Suggestions -------------------------------------------------------------------------


def _suggestion(s: CaseSuggestion) -> dict:
    return {
        "id": s.id,
        "lead_id": s.lead_id,
        "loop_case_id": s.loop_case_id,
        "reason": s.reason,
        "status": s.status,
        "created_at": s.created_at,
    }


@router.get("/leads/{lead_id}/suggestions")
def suggestions(
    lead_id: int, db: Session = Depends(get_session), user: User = Depends(current_user), mcp: McpClient = Depends(get_mcp)
) -> dict:
    """Runs the lookup (CardCode, contact email, domain) and returns the pending suggestions.

    The lookup stores new pending rows even for a viewer: it is a cache of what the MCPs said,
    not a change to the lead. Nothing is linked here.
    """
    lead = _get_lead(db, lead_id)
    res = matching.refresh_suggestions(db, mcp, lead)
    return {
        "available": res.available,
        "reason": res.reason,
        "items": [_suggestion(s) for s in matching.pending_suggestions(db, lead_id)],
    }


def _pending_suggestion(db: Session, lead_id: int, sid: int) -> CaseSuggestion:
    s = db.get(CaseSuggestion, sid)
    if s is None or s.lead_id != lead_id:
        raise HTTPException(404, "suggestion not found")
    if s.status != "pending":
        raise HTTPException(409, f"suggestion is already {s.status}")
    return s


@router.post("/leads/{lead_id}/suggestions/{sid}/accept")
def accept_suggestion(
    lead_id: int, sid: int, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    s = _pending_suggestion(db, lead_id, sid)
    s.status = "accepted"
    _link(db, lead_id, s.loop_case_id, "suggested", user.email)
    activity(db, lead_id, "suggestion_accepted", user.email, {"loop_case_id": s.loop_case_id, "reason": s.reason})
    db.commit()
    return _suggestion(s)


@router.post("/leads/{lead_id}/suggestions/{sid}/dismiss")
def dismiss_suggestion(
    lead_id: int, sid: int, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    s = _pending_suggestion(db, lead_id, sid)
    s.status = "dismissed"
    activity(db, lead_id, "suggestion_dismissed", user.email, {"loop_case_id": s.loop_case_id, "reason": s.reason})
    db.commit()
    return _suggestion(s)


# ---- Live MCP reads for the company window -----------------------------------------------


@router.get("/companies/{company_id}/sap-card")
def sap_card(
    company_id: int, db: Session = Depends(get_session), user: User = Depends(current_user), mcp: McpClient = Depends(get_mcp)
) -> dict:
    company = _get_company(db, company_id)
    if not company.sap_card_code:
        return unavailable("company has no confirmed SAP CardCode")
    r = mcp.call("sap", "get_customer_card", {"card_code": company.sap_card_code})
    if not r["available"]:
        return r
    return {"available": True, "card_code": company.sap_card_code, "card": r["data"], "text": r["text"]}


@router.get("/companies/{company_id}/sap-search")
def sap_search(
    company_id: int,
    q: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
    mcp: McpClient = Depends(get_mcp),
) -> dict:
    """"Find in SAP": resolve_customer on q, or the company's domain, or its name."""
    company = _get_company(db, company_id)
    query = (q or "").strip() or company.domain or company.name
    r = mcp.call("sap", "resolve_customer", {"query": query, "include_suppliers": True, "limit": 10})
    if not r["available"]:
        return r
    data = r["data"] if isinstance(r["data"], dict) else {}
    return {"available": True, "query": query, "matches": data.get("matches") or [], "more": data.get("more", 0)}


@router.get("/companies/{company_id}/supplier-prices")
def supplier_prices(
    company_id: int,
    q: str | None = None,
    item_code: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
    mcp: McpClient = Depends(get_mcp),
) -> dict:
    """latest_supplier_prices matches item description / supplier SKU / ItemCode, not the supplier
    name, so the window should pass q or item_code; the company name is only the default."""
    company = _get_company(db, company_id)
    query = (q or "").strip() or None
    if not item_code and not query:
        query = company.name
    r = mcp.call("cases", "latest_supplier_prices", {"item_code": item_code, "query": query, "limit": 20})
    if not r["available"]:
        return r
    data = r["data"] if isinstance(r["data"], dict) else {}
    return {"available": True, "query": query, "item_code": item_code, "prices": data.get("prices") or []}
