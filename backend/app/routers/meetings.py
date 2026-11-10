"""Meetings: dated entries with a markdown summary, contacts and follow-up actions (LEADS_PLAN 6)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import User, current_user, require_editor
from app.db import get_session
from app.models import Company, Contact, Convention, ConventionAppearance, Lead, Meeting, MeetingAction, MeetingContact
from app.services import export_md
from app.services.followup import refresh_company_leads

router = APIRouter(tags=["meetings"])


class ActionIn(BaseModel):
    text: str
    owner: str | None = None
    due_on: date | None = None


class ActionPatch(BaseModel):
    text: str | None = None
    owner: str | None = None
    due_on: date | None = None
    done: bool | None = None


class MeetingIn(BaseModel):
    company_id: int
    met_on: date
    lead_id: int | None = None
    appearance_id: int | None = None
    starts_at: datetime | None = None
    place: str | None = None
    met_by: list[str] = []
    summary_md: str | None = None
    contact_ids: list[int] = []
    actions: list[ActionIn] = []
    source: str | None = None


class MeetingPatch(BaseModel):
    met_on: date | None = None
    lead_id: int | None = None
    appearance_id: int | None = None
    starts_at: datetime | None = None
    place: str | None = None
    met_by: list[str] | None = None
    summary_md: str | None = None
    contact_ids: list[int] | None = None
    source: str | None = None


# ---- Serialization (also used by the companies router and the export) -----------------


def action_dict(a: MeetingAction) -> dict:
    return {"id": a.id, "text": a.text, "owner": a.owner, "due_on": a.due_on, "done_at": a.done_at}


def serialize_meetings(db: Session, meetings: list[Meeting]) -> list[dict]:
    if not meetings:
        return []
    ids = [m.id for m in meetings]
    names = dict(db.execute(select(Company.id, Company.name).where(Company.id.in_({m.company_id for m in meetings}))).all())
    contacts: dict[int, list[dict]] = {i: [] for i in ids}
    for mid, c in db.execute(
        select(MeetingContact.meeting_id, Contact)
        .join(Contact, Contact.id == MeetingContact.contact_id)
        .where(MeetingContact.meeting_id.in_(ids))
        .order_by(Contact.name, Contact.id)
    ).all():
        contacts[mid].append({"id": c.id, "name": c.name, "email": c.email, "title": c.title})
    actions: dict[int, list[dict]] = {i: [] for i in ids}
    for a in db.scalars(
        select(MeetingAction).where(MeetingAction.meeting_id.in_(ids)).order_by(MeetingAction.id)
    ).all():
        actions[a.meeting_id].append(action_dict(a))
    return [
        {
            "id": m.id,
            "company_id": m.company_id,
            "company_name": names.get(m.company_id),
            "lead_id": m.lead_id,
            "appearance_id": m.appearance_id,
            "met_on": m.met_on,
            "starts_at": m.starts_at,
            "place": m.place,
            "met_by": m.met_by or [],
            "summary_md": m.summary_md,
            "source": m.source,
            "contacts": contacts[m.id],
            "actions": actions[m.id],
            "created_by": m.created_by,
            "created_at": m.created_at,
            "updated_at": m.updated_at,
        }
        for m in meetings
    ]


def newest_first(stmt):
    return stmt.order_by(Meeting.met_on.desc(), Meeting.starts_at.desc().nulls_last(), Meeting.id.desc())


def _one(db: Session, meeting_id: int) -> dict:
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(404, "meeting not found")
    return serialize_meetings(db, [m])[0]


def _check_refs(db: Session, company_id: int, lead_id, appearance_id, contact_ids) -> None:
    if lead_id is not None:
        lead = db.get(Lead, lead_id)
        if lead is None or lead.company_id != company_id:
            raise HTTPException(422, "lead does not belong to this company")
    if appearance_id is not None:
        ap = db.get(ConventionAppearance, appearance_id)
        if ap is None or ap.company_id != company_id:
            raise HTTPException(422, "appearance does not belong to this company")
    if contact_ids:
        found = set(db.scalars(select(Contact.id).where(Contact.id.in_(contact_ids), Contact.company_id == company_id)))
        if found != set(contact_ids):
            raise HTTPException(422, "contact does not belong to this company")


def _set_contacts(db: Session, meeting_id: int, contact_ids: list[int]) -> None:
    db.execute(delete(MeetingContact).where(MeetingContact.meeting_id == meeting_id))
    for cid in dict.fromkeys(contact_ids):
        db.add(MeetingContact(meeting_id=meeting_id, contact_id=cid))


# ---- Endpoints ---------------------------------------------------------------------------


@router.get("/meetings")
def list_meetings(
    company_id: int | None = None,
    contact_id: int | None = None,
    lead_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    stmt = select(Meeting)
    if company_id is not None:
        stmt = stmt.where(Meeting.company_id == company_id)
    if lead_id is not None:
        stmt = stmt.where(Meeting.lead_id == lead_id)
    if contact_id is not None:
        stmt = stmt.where(
            Meeting.id.in_(select(MeetingContact.meeting_id).where(MeetingContact.contact_id == contact_id))
        )
    return serialize_meetings(db, db.scalars(newest_first(stmt)).all())


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return _one(db, meeting_id)


@router.post("/meetings", status_code=201)
def create_meeting(body: MeetingIn, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    if db.get(Company, body.company_id) is None:
        raise HTTPException(404, "company not found")
    _check_refs(db, body.company_id, body.lead_id, body.appearance_id, body.contact_ids)
    m = Meeting(
        company_id=body.company_id,
        lead_id=body.lead_id,
        appearance_id=body.appearance_id,
        met_on=body.met_on,
        starts_at=body.starts_at,
        place=body.place,
        met_by=body.met_by,
        summary_md=body.summary_md,
        source=body.source or "app",
        created_by=user.email,
    )
    db.add(m)
    db.flush()
    _set_contacts(db, m.id, body.contact_ids)
    for a in body.actions:
        db.add(MeetingAction(meeting_id=m.id, text=a.text, owner=a.owner, due_on=a.due_on))
    db.flush()
    refresh_company_leads(db, m.company_id, user.email)
    db.commit()
    return _one(db, m.id)


@router.patch("/meetings/{meeting_id}")
def patch_meeting(
    meeting_id: int, body: MeetingPatch, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(404, "meeting not found")
    changes = body.model_dump(exclude_unset=True)
    if "met_on" in changes and changes["met_on"] is None:
        raise HTTPException(422, "met_on cannot be empty")
    _check_refs(
        db,
        m.company_id,
        changes.get("lead_id"),
        changes.get("appearance_id"),
        changes.get("contact_ids") or [],
    )
    contact_ids = changes.pop("contact_ids", None)
    for k, v in changes.items():
        if k == "met_by":
            v = v or []
        if k == "source":
            v = v or "app"
        setattr(m, k, v)
    if contact_ids is not None:
        _set_contacts(db, m.id, contact_ids)
    db.flush()
    refresh_company_leads(db, m.company_id, user.email)
    db.commit()
    return _one(db, m.id)


@router.post("/meetings/{meeting_id}/actions", status_code=201)
def add_action(
    meeting_id: int, body: ActionIn, db: Session = Depends(get_session), user: User = Depends(require_editor)
) -> dict:
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(404, "meeting not found")
    db.add(MeetingAction(meeting_id=m.id, text=body.text, owner=body.owner, due_on=body.due_on))
    db.flush()
    refresh_company_leads(db, m.company_id, user.email)
    db.commit()
    return _one(db, m.id)


@router.patch("/meetings/{meeting_id}/actions/{action_id}")
def patch_action(
    meeting_id: int,
    action_id: int,
    body: ActionPatch,
    db: Session = Depends(get_session),
    user: User = Depends(require_editor),
) -> dict:
    a = db.get(MeetingAction, action_id)
    if a is None or a.meeting_id != meeting_id:
        raise HTTPException(404, "action not found")
    changes = body.model_dump(exclude_unset=True)
    done = changes.pop("done", None)
    if "text" in changes and not changes["text"]:
        raise HTTPException(422, "text cannot be empty")
    for k, v in changes.items():
        setattr(a, k, v)
    if done is True and a.done_at is None:
        a.done_at = datetime.now(timezone.utc)
    elif done is False:
        a.done_at = None
    db.flush()
    m = db.get(Meeting, meeting_id)
    refresh_company_leads(db, m.company_id, user.email)
    db.commit()
    return _one(db, meeting_id)


@router.get("/meetings/{meeting_id}/export.md")
def export_meeting(meeting_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(404, "meeting not found")
    meeting = serialize_meetings(db, [m])[0]
    company = db.get(Company, m.company_id)
    appearance = None
    if m.appearance_id:
        ap = db.get(ConventionAppearance, m.appearance_id)
        conv = db.get(Convention, ap.convention_id) if ap else None
        if ap:
            appearance = {
                "hall": ap.hall,
                "booth": ap.booth,
                "hall_booth_raw": ap.hall_booth_raw,
                "convention_slug": conv.slug if conv else None,
            }
    md = export_md.render_meeting(meeting, {"id": company.id, "name": company.name}, appearance)
    filename = f"{export_md.safe_filename(company.name)} {m.met_on.isoformat()}.md"
    return markdown_response(md, filename)


def markdown_response(md: str, filename: str) -> Response:
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
