"""Global search: plain ILIKE on companies and contacts, `simple` full text plus ILIKE on meetings."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session

from app.auth import User, current_user
from app.db import get_session
from app.models import Company, Contact, Meeting

router = APIRouter(tags=["search"])


def _escape(q: str) -> str:
    return q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(q: str) -> str:
    return "%" + _escape(q) + "%"


@router.get("/search")
def search(
    q: str = "",
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    q = q.strip()
    if not q:
        return {"companies": [], "contacts": [], "meetings": []}
    pat = _like(q)

    companies = db.execute(
        select(Company.id, Company.name, Company.country)
        .where(
            Company.merged_into_id.is_(None),
            or_(Company.name.ilike(pat), Company.name_normalized.ilike(pat), Company.domain.ilike(pat)),
        )
        .order_by(Company.name.ilike(_escape(q) + "%").desc(), Company.name_normalized, Company.id)
        .limit(limit)
    ).all()

    contacts = db.execute(
        select(Contact.id, Contact.name, Contact.email, Contact.company_id, Company.name.label("company_name"))
        .join(Company, Company.id == Contact.company_id)
        .where(or_(Contact.name.ilike(pat), Contact.email.ilike(pat)))
        .order_by(Contact.name, Contact.id)
        .limit(limit)
    ).all()

    doc = func.coalesce(Meeting.summary_md, literal(""))
    tsq = func.plainto_tsquery("simple", q)
    fts = func.to_tsvector("simple", doc).op("@@")(tsq)  # matches ix_meetings_summary_fts
    snippet = func.ts_headline(
        "simple", doc, tsq, "MaxFragments=1, MaxWords=20, MinWords=6, StartSel=**, StopSel=**"
    )
    meetings = db.execute(
        select(
            Meeting.id,
            Meeting.company_id,
            Company.name.label("company_name"),
            Meeting.met_on,
            snippet.label("snippet"),
        )
        .join(Company, Company.id == Meeting.company_id)
        .where(or_(fts, Meeting.summary_md.ilike(pat), Meeting.place.ilike(pat)))
        .order_by(Meeting.met_on.desc(), Meeting.id.desc())
        .limit(limit)
    ).all()

    return {
        "companies": [{"id": r.id, "name": r.name, "country": r.country} for r in companies],
        "contacts": [
            {"id": r.id, "name": r.name, "email": r.email, "company_id": r.company_id, "company_name": r.company_name}
            for r in contacts
        ],
        "meetings": [
            {"id": r.id, "company_id": r.company_id, "company_name": r.company_name, "met_on": r.met_on, "snippet": r.snippet}
            for r in meetings
        ],
    }
