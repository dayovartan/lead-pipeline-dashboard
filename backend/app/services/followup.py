"""A lead's follow_up_on follows its earliest open meeting action unless a person set it.

"Set by hand" is read from lead_activity, no extra column:
- Every change of follow_up_on writes an `edited` activity with
  data = {"changes": {"follow_up_on": [old, new]}, "auto": true|false}.
- The date is auto-managed when follow_up_on is empty, or when the newest activity that changed
  follow_up_on was an automatic one and still matches the stored date.
- Anything else (a PATCH by a person, a date seeded by the Excel import or Jira with no auto
  activity behind it) counts as set by hand and is left alone. Clearing the date by hand
  (PATCH follow_up_on=null) hands it back to the actions.

A lead's actions are those on meetings with that lead_id, plus meetings of the same company that
are not attached to any lead.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models import Lead, LeadActivity, Meeting, MeetingAction


def earliest_open_due(db: Session, lead: Lead) -> date | None:
    return db.scalar(
        select(MeetingAction.due_on)
        .join(Meeting, Meeting.id == MeetingAction.meeting_id)
        .where(
            MeetingAction.done_at.is_(None),
            MeetingAction.due_on.is_not(None),
            or_(
                Meeting.lead_id == lead.id,
                (Meeting.lead_id.is_(None)) & (Meeting.company_id == lead.company_id),
            ),
        )
        .order_by(MeetingAction.due_on)
        .limit(1)
    )


def is_auto_managed(db: Session, lead: Lead) -> bool:
    if lead.follow_up_on is None:
        return True
    last = db.scalar(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead.id, text("lead_activity.data -> 'changes' ? 'follow_up_on'"))
        .order_by(LeadActivity.at.desc(), LeadActivity.id.desc())
        .limit(1)
    )
    if last is None or not (last.data or {}).get("auto"):
        return False
    return last.data["changes"]["follow_up_on"][1] == lead.follow_up_on.isoformat()


def refresh_follow_up(db: Session, lead: Lead, actor: str | None) -> bool:
    """Set follow_up_on from the actions when it is auto-managed. Does not commit."""
    if not is_auto_managed(db, lead):
        return False
    due = earliest_open_due(db, lead)
    if due == lead.follow_up_on:
        return False
    old = lead.follow_up_on
    lead.follow_up_on = due
    db.add(
        LeadActivity(
            lead_id=lead.id,
            kind="edited",
            actor=actor,
            data={"changes": {"follow_up_on": [_iso(old), _iso(due)]}, "auto": True},
        )
    )
    db.flush()
    return True


def refresh_company_leads(db: Session, company_id: int, actor: str | None) -> None:
    for lead in db.scalars(select(Lead).where(Lead.company_id == company_id)).all():
        refresh_follow_up(db, lead, actor)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
