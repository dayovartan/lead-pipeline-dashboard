"""Conventions and exhibition mapping (docs/API.md "Conventions" and "Exhibitions").

Self-contained: no MCPs, no cases, no external systems. The only hand-offs to the leads side
are the floor note (a meeting, source='floor') and Follow (a lead).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import User, current_user, require_editor
from ..config import get_settings
from ..db import get_session
from ..models import (
    AppearanceMapping,
    AppearanceTag,
    CategoryTagRule,
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
    VenueNode,
)
from ..services import suggest, venue
from ..services.normalize import booth_sort_key
from ..services.xlsx import write_floor_list

router = APIRouter(tags=["exhibitions"])

Role = Literal["lead", "supplier", "both", "ignore"]
Priority = Literal["must_visit", "nice_to_visit", "skip"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- conventions


class ConventionIn(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    city: str | None = None
    country: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


def _convention(db: Session, slug: str) -> Convention:
    c = db.scalar(select(Convention).where(Convention.slug == slug))
    if c is None:
        raise HTTPException(404, f"no convention {slug!r}")
    return c


def _counts(db: Session, convention_ids: list[int]) -> dict[int, dict]:
    out = {cid: {"appearances": 0, "mapped": 0, "visited": 0, "leads": 0} for cid in convention_ids}
    if not convention_ids:
        return out
    A = ConventionAppearance
    in_ids = A.convention_id.in_(convention_ids)
    for cid, n in db.execute(select(A.convention_id, func.count()).where(in_ids).group_by(A.convention_id)):
        out[cid]["appearances"] = n
    for cid, n in db.execute(
        select(A.convention_id, func.count()).join(AppearanceMapping, AppearanceMapping.appearance_id == A.id)
        .where(in_ids, AppearanceMapping.confirmed_at.is_not(None)).group_by(A.convention_id)
    ):
        out[cid]["mapped"] = n
    for cid, n in db.execute(
        select(A.convention_id, func.count()).join(DispatchAssignment, DispatchAssignment.appearance_id == A.id)
        .where(in_ids, DispatchAssignment.visited.is_(True)).group_by(A.convention_id)
    ):
        out[cid]["visited"] = n
    for cid, n in db.execute(
        select(A.convention_id, func.count()).join(Lead, Lead.appearance_id == A.id)
        .where(in_ids).group_by(A.convention_id)
    ):
        out[cid]["leads"] = n
    return out


def convention_dict(c: Convention, counts: dict) -> dict:
    return {
        "id": c.id, "name": c.name, "slug": c.slug, "city": c.city, "country": c.country,
        "starts_on": c.starts_on, "ends_on": c.ends_on, "counts": counts,
        "venue_map_url": f"/api/conventions/{c.slug}/venue-map" if c.venue_map_file else None,
    }


@router.get("/conventions")
def list_conventions(db: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    convs = list(db.scalars(select(Convention).order_by(Convention.starts_on.desc().nulls_last(), Convention.name)))
    counts = _counts(db, [c.id for c in convs])
    return [convention_dict(c, counts[c.id]) for c in convs]


@router.post("/conventions", status_code=201)
def create_convention(body: ConventionIn, db: Session = Depends(get_session),
                      user: User = Depends(require_editor)) -> dict:
    if db.scalar(select(Convention.id).where(Convention.slug == body.slug)):
        raise HTTPException(409, f"slug {body.slug!r} is taken")
    c = Convention(**body.model_dump())
    db.add(c)
    db.commit()
    return convention_dict(c, _counts(db, [c.id])[c.id])


@router.get("/conventions/{slug}")
def get_convention(slug: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    c = _convention(db, slug)
    return convention_dict(c, _counts(db, [c.id])[c.id])


@router.post("/conventions/{slug}/venue-map")
async def upload_venue_map(slug: str, file: UploadFile = File(...), db: Session = Depends(get_session),
                           user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    name = re.sub(r"[^\w.\-]+", "_", Path(file.filename or "venue-map").name)[:100]
    rel = f"venue-maps/{c.slug}-{name}"
    dest = Path(get_settings().files_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    c.venue_map_file = rel
    db.commit()
    return convention_dict(c, _counts(db, [c.id])[c.id])


@router.get("/conventions/{slug}/venue-map")
def get_venue_map(slug: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    c = _convention(db, slug)
    path = Path(get_settings().files_dir) / (c.venue_map_file or "")
    if not c.venue_map_file or not path.is_file():
        raise HTTPException(404, "no venue map")
    return FileResponse(path)


# ---------------------------------------------------------------- appearance items

P = "/conventions/{slug}"


def appearance_items(db: Session, apps: list[ConventionAppearance]) -> list[dict]:
    """The appearance item shape shared by the map, dispatch and floor lists."""
    if not apps:
        return []
    ids = [a.id for a in apps]
    company_ids = list({a.company_id for a in apps})
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))}
    mappings = {m.appearance_id: m for m in db.scalars(select(AppearanceMapping).where(AppearanceMapping.appearance_id.in_(ids)))}
    dispatch = {d.appearance_id: d for d in db.scalars(select(DispatchAssignment).where(DispatchAssignment.appearance_id.in_(ids)))}
    tags: dict[int, list[dict]] = {}
    for at, tag, group in db.execute(
        select(AppearanceTag, HardwareTag, TagGroup)
        .join(HardwareTag, HardwareTag.id == AppearanceTag.tag_id)
        .outerjoin(TagGroup, TagGroup.id == HardwareTag.group_id)
        .where(AppearanceTag.appearance_id.in_(ids))
        .order_by(HardwareTag.name)
    ):
        tags.setdefault(at.appearance_id, []).append({
            "id": tag.id, "name": tag.name, "group": group.name if group else None,
            "group_id": tag.group_id, "suggested": at.suggested, "confirmed": at.confirmed,
        })
    lead_by_app: dict[int, int] = {}
    lead_by_company: dict[int, int] = {}
    for lead_id, company_id, appearance_id in db.execute(
        select(Lead.id, Lead.company_id, Lead.appearance_id).where(Lead.company_id.in_(company_ids)).order_by(Lead.id)
    ):
        lead_by_company[company_id] = lead_id
        if appearance_id:
            lead_by_app[appearance_id] = lead_id

    out = []
    for a in apps:
        c = companies[a.company_id]
        m = mappings.get(a.id)
        d = dispatch.get(a.id)
        out.append({
            "id": a.id,
            "company": {"id": c.id, "name": c.name, "country": c.country, "website": c.website,
                        "categories": c.categories or []},
            "hall": a.hall,
            "booth": a.booth,
            "hall_booth_raw": a.hall_booth_raw,
            "role": a.role,
            "priority": a.priority,
            "met_at_booth": a.met_at_booth,
            "mapping": None if m is None else {
                "suggested_role": m.suggested_role, "suggested_priority": m.suggested_priority,
                "confirmed_by": m.confirmed_by, "confirmed_at": m.confirmed_at,
            },
            "tags": tags.get(a.id, []),
            "dispatch": None if d is None else {
                "assignee": d.assignee, "visited": d.visited, "visited_at": d.visited_at, "note": d.note,
            },
            "lead_id": lead_by_app.get(a.id) or lead_by_company.get(a.company_id),
        })
    return out


def _filtered(convention_id: int, q=None, role=None, priority=None, tag=None, group=None, hall=None,
              assignee=None, visited=None, mapped=None, category=None):
    """select(ConventionAppearance) joined to Company with the list filters applied."""
    A = ConventionAppearance
    s = select(A).join(Company, Company.id == A.company_id).where(A.convention_id == convention_id)
    if q:
        like = f"%{q.strip()}%"
        s = s.where(or_(Company.name.ilike(like), Company.name_normalized.ilike(like),
                        Company.domain.ilike(like), A.hall_booth_raw.ilike(like)))
    if role:
        s = s.where(A.role.is_(None) if role in ("none", "unmapped") else A.role == role)
    if priority:
        s = s.where(A.priority.is_(None) if priority == "none" else A.priority == priority)
    if tag is not None:
        s = s.where(exists().where(AppearanceTag.appearance_id == A.id, AppearanceTag.tag_id == tag))
    if group is not None:
        s = s.where(exists().where(AppearanceTag.appearance_id == A.id, AppearanceTag.tag_id == HardwareTag.id,
                                   HardwareTag.group_id == group))
    if hall:
        s = s.where(func.lower(A.hall) == hall.lower())
    if assignee:
        if assignee == "none":
            s = s.where(~exists().where(DispatchAssignment.appearance_id == A.id,
                                        DispatchAssignment.assignee.is_not(None)))
        else:
            s = s.where(exists().where(DispatchAssignment.appearance_id == A.id,
                                       func.lower(DispatchAssignment.assignee) == assignee.lower()))
    if visited is not None:
        is_visited = exists().where(DispatchAssignment.appearance_id == A.id, DispatchAssignment.visited.is_(True))
        s = s.where(is_visited if visited else ~is_visited)
    if mapped is not None:
        is_mapped = exists().where(AppearanceMapping.appearance_id == A.id, AppearanceMapping.confirmed_at.is_not(None))
        s = s.where(is_mapped if mapped else ~is_mapped)
    if category:
        s = s.where(Company.categories.any(category))
    return s


def _booth_order():
    A = ConventionAppearance
    return (A.hall.asc().nulls_last(), func.length(A.booth).asc().nulls_last(), A.booth.asc(), A.id)


@router.get(P + "/appearances")
def list_appearances(
    slug: str,
    q: str | None = None,
    role: str | None = None,
    priority: str | None = None,
    tag: int | None = None,
    group: int | None = None,
    hall: str | None = None,
    assignee: str | None = None,
    visited: bool | None = None,
    mapped: bool | None = None,
    category: str | None = None,
    sort: Literal["booth", "name"] = "booth",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    c = _convention(db, slug)
    s = _filtered(c.id, q, role, priority, tag, group, hall, assignee, visited, mapped, category)
    total = db.scalar(select(func.count()).select_from(s.subquery()))
    order = (func.lower(Company.name), ConventionAppearance.id) if sort == "name" else _booth_order()
    apps = list(db.scalars(s.order_by(*order).offset((page - 1) * page_size).limit(page_size)))
    return {"items": appearance_items(db, apps), "total": total, "page": page, "page_size": page_size}


def _appearance(db: Session, convention: Convention, appearance_id: int) -> ConventionAppearance:
    a = db.get(ConventionAppearance, appearance_id)
    if a is None or a.convention_id != convention.id:
        raise HTTPException(404, "no such appearance at this convention")
    return a


def _mapping(db: Session, appearance_id: int) -> AppearanceMapping:
    m = db.get(AppearanceMapping, appearance_id)
    if m is None:
        m = AppearanceMapping(appearance_id=appearance_id)
        db.add(m)
        db.flush()
    return m


def _confirm(db: Session, a: ConventionAppearance, user: User) -> None:
    m = _mapping(db, a.id)
    m.confirmed_by = user.email
    m.confirmed_at = _now()


def _dispatch(db: Session, appearance_id: int) -> DispatchAssignment:
    d = db.get(DispatchAssignment, appearance_id)
    if d is None:
        d = DispatchAssignment(appearance_id=appearance_id, visited=False)
        db.add(d)
        db.flush()
    return d


def _set_tag(db: Session, appearance_id: int, tag_id: int) -> AppearanceTag:
    """A person adds a tag: confirmed. An existing suggestion becomes confirmed."""
    at = db.get(AppearanceTag, (appearance_id, tag_id))
    if at is None:
        at = AppearanceTag(appearance_id=appearance_id, tag_id=tag_id, suggested=False, confirmed=True)
        db.add(at)
        db.flush()
    else:
        at.confirmed = True
    return at


def _tag(db: Session, tag_id: int) -> HardwareTag:
    t = db.get(HardwareTag, tag_id)
    if t is None:
        raise HTTPException(404, f"no tag {tag_id}")
    return t


class AppearancePatch(BaseModel):
    role: Role | None = None
    priority: Priority | None = None
    met_at_booth: bool | None = None


@router.patch(P + "/appearances/{appearance_id}")
def patch_appearance(slug: str, appearance_id: int, body: AppearancePatch, db: Session = Depends(get_session),
                     user: User = Depends(require_editor)) -> dict:
    """Setting role or priority is a person's decision, so it confirms the mapping."""
    a = _appearance(db, _convention(db, slug), appearance_id)
    fields = body.model_fields_set
    if "role" in fields:
        a.role = body.role
    if "priority" in fields:
        a.priority = body.priority
    if "met_at_booth" in fields and body.met_at_booth is not None:
        a.met_at_booth = body.met_at_booth
        a.edited_fields = sorted(set(a.edited_fields or []) | {"met_at_booth"})
    if fields & {"role", "priority"}:
        _confirm(db, a, user)
    db.commit()
    return appearance_items(db, [a])[0]


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    role: Role | None = None
    priority: Priority | None = None
    add_tag_ids: list[int] = []
    remove_tag_ids: list[int] = []
    assignee: str | None = None
    confirm: bool = False


@router.post(P + "/appearances/bulk")
def bulk(slug: str, body: BulkIn, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    """Bulk set. confirm=true accepts the suggestions: suggested role/priority fill an empty
    role/priority, suggested tags become confirmed, and the mapping is confirmed.
    `assignee` given (even null) sets or clears the assignee."""
    c = _convention(db, slug)
    apps = list(db.scalars(select(ConventionAppearance).where(
        ConventionAppearance.id.in_(body.ids), ConventionAppearance.convention_id == c.id)))
    if len(apps) != len(set(body.ids)):
        raise HTTPException(404, "some ids are not appearances of this convention")
    for tag_id in body.add_tag_ids + body.remove_tag_ids:
        _tag(db, tag_id)
    fields = body.model_fields_set
    for a in apps:
        if body.role is not None:
            a.role = body.role
        if body.priority is not None:
            a.priority = body.priority
        for tag_id in body.add_tag_ids:
            _set_tag(db, a.id, tag_id)
        for tag_id in body.remove_tag_ids:
            at = db.get(AppearanceTag, (a.id, tag_id))
            if at is not None:
                db.delete(at)
        if "assignee" in fields:
            _dispatch(db, a.id).assignee = (body.assignee or "").strip() or None
        if body.confirm:
            m = _mapping(db, a.id)
            if a.role is None and m.suggested_role:
                a.role = m.suggested_role
            if a.priority is None and m.suggested_priority:
                a.priority = m.suggested_priority
            for at in db.scalars(select(AppearanceTag).where(AppearanceTag.appearance_id == a.id)):
                at.confirmed = True
        if body.confirm or body.role is not None or body.priority is not None:
            _confirm(db, a, user)
    db.commit()
    return {"updated": len(apps)}


class TagIn(BaseModel):
    tag_id: int


@router.post(P + "/appearances/{appearance_id}/tags")
def add_tag(slug: str, appearance_id: int, body: TagIn, db: Session = Depends(get_session),
            user: User = Depends(require_editor)) -> dict:
    a = _appearance(db, _convention(db, slug), appearance_id)
    _tag(db, body.tag_id)
    _set_tag(db, a.id, body.tag_id)
    db.commit()
    return appearance_items(db, [a])[0]


@router.delete(P + "/appearances/{appearance_id}/tags/{tag_id}")
def remove_tag(slug: str, appearance_id: int, tag_id: int, db: Session = Depends(get_session),
               user: User = Depends(require_editor)) -> dict:
    a = _appearance(db, _convention(db, slug), appearance_id)
    at = db.get(AppearanceTag, (a.id, tag_id))
    if at is not None:
        db.delete(at)
        db.commit()
    return appearance_items(db, [a])[0]


@router.post(P + "/appearances/{appearance_id}/tags/{tag_id}/confirm")
def confirm_tag(slug: str, appearance_id: int, tag_id: int, db: Session = Depends(get_session),
                user: User = Depends(require_editor)) -> dict:
    a = _appearance(db, _convention(db, slug), appearance_id)
    at = db.get(AppearanceTag, (a.id, tag_id))
    if at is None:
        raise HTTPException(404, "tag not on this appearance")
    at.confirmed = True
    db.commit()
    return appearance_items(db, [a])[0]


@router.post(P + "/suggest")
def run_suggest(slug: str, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    counts = suggest.run_suggestions(db, c.id)
    db.commit()
    return counts


# ---------------------------------------------------------------- categories and tags


@router.get(P + "/categories")
def categories(slug: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    """Raw organizer categories of this show's exhibitors, with counts and the tags they map to."""
    c = _convention(db, slug)
    rows = db.execute(text("""
        SELECT cat, count(*) AS n
        FROM leads.convention_appearances a
        JOIN leads.companies co ON co.id = a.company_id
        CROSS JOIN LATERAL unnest(co.categories) AS cat
        WHERE a.convention_id = :cid
        GROUP BY cat
        ORDER BY n DESC, cat
    """), {"cid": c.id}).all()
    rules: dict[str, list[CategoryTagRule]] = {}
    for r in db.scalars(select(CategoryTagRule).where(CategoryTagRule.convention_id == c.id).order_by(CategoryTagRule.id)):
        rules.setdefault(r.category.lower(), []).append(r)
    out = [{"category": cat, "count": n,
            "tag_ids": [r.tag_id for r in rules.get(cat.lower(), [])],
            "rules": [{"id": r.id, "tag_id": r.tag_id} for r in rules.get(cat.lower(), [])]}
           for cat, n in rows]
    # Keyword rules that are not a raw category still show up, with count 0.
    known = {o["category"].lower() for o in out}
    for key, rs in rules.items():
        if key not in known:
            out.append({"category": rs[0].category, "count": 0, "tag_ids": [r.tag_id for r in rs],
                        "rules": [{"id": r.id, "tag_id": r.tag_id} for r in rs], "keyword": True})
    return out


def _tag_dict(t: HardwareTag, counts: dict[int, tuple[int, int]]) -> dict:
    n, confirmed = counts.get(t.id, (0, 0))
    return {"id": t.id, "name": t.name, "group_id": t.group_id, "count": n, "confirmed_count": confirmed}


@router.get(P + "/tags")
def list_tags(slug: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    """This show's tag groups with their tags. `ungrouped` holds every tag that is not in one of
    this show's groups (tags are shared across shows; groups are per show)."""
    c = _convention(db, slug)
    counts = {
        tag_id: (n, confirmed)
        for tag_id, n, confirmed in db.execute(
            select(AppearanceTag.tag_id, func.count(), func.count().filter(AppearanceTag.confirmed.is_(True)))
            .join(ConventionAppearance, ConventionAppearance.id == AppearanceTag.appearance_id)
            .where(ConventionAppearance.convention_id == c.id)
            .group_by(AppearanceTag.tag_id)
        )
    }
    groups = list(db.scalars(select(TagGroup).where(TagGroup.convention_id == c.id).order_by(TagGroup.name)))
    group_ids = {g.id for g in groups}
    by_group: dict[int, list[dict]] = {g.id: [] for g in groups}
    ungrouped = []
    for t in db.scalars(select(HardwareTag).order_by(func.lower(HardwareTag.name))):
        if t.group_id in group_ids:
            by_group[t.group_id].append(_tag_dict(t, counts))
        else:
            ungrouped.append(_tag_dict(t, counts))
    return {"groups": [{"id": g.id, "name": g.name, "tags": by_group[g.id]} for g in groups], "ungrouped": ungrouped}


class NameIn(BaseModel):
    name: str = Field(min_length=1)


@router.post(P + "/tag-groups", status_code=201)
def create_tag_group(slug: str, body: NameIn, db: Session = Depends(get_session),
                     user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    g = TagGroup(convention_id=c.id, name=body.name.strip())
    db.add(g)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"group {body.name!r} exists") from None
    return {"id": g.id, "name": g.name, "tags": []}


class TagCreate(BaseModel):
    name: str = Field(min_length=1)
    group_id: int | None = None


class TagPatch(BaseModel):
    name: str | None = Field(None, min_length=1)
    group_id: int | None = None


def _check_group(db: Session, c: Convention, group_id: int | None) -> None:
    if group_id is not None:
        g = db.get(TagGroup, group_id)
        if g is None or g.convention_id != c.id:
            raise HTTPException(404, "no such tag group at this convention")


@router.post(P + "/tags", status_code=201)
def create_tag(slug: str, body: TagCreate, db: Session = Depends(get_session),
               user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    _check_group(db, c, body.group_id)
    t = HardwareTag(name=body.name.strip(), group_id=body.group_id)
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"tag {body.name!r} exists") from None
    return _tag_dict(t, {})


@router.patch(P + "/tags/{tag_id}")
def patch_tag(slug: str, tag_id: int, body: TagPatch, db: Session = Depends(get_session),
              user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    t = _tag(db, tag_id)
    if body.name is not None:
        t.name = body.name.strip()
    if "group_id" in body.model_fields_set:
        _check_group(db, c, body.group_id)
        t.group_id = body.group_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"tag {body.name!r} exists") from None
    return _tag_dict(t, {})


class RuleIn(BaseModel):
    category: str = Field(min_length=1)
    tag_id: int


@router.post(P + "/category-rules", status_code=201)
def create_rule(slug: str, body: RuleIn, db: Session = Depends(get_session),
                user: User = Depends(require_editor)) -> dict:
    """Map a raw category (or a keyword) to a tag for this show. Run /suggest to apply it."""
    c = _convention(db, slug)
    _tag(db, body.tag_id)
    category = body.category.strip()
    r = db.scalar(select(CategoryTagRule).where(CategoryTagRule.convention_id == c.id,
                                                CategoryTagRule.category == category,
                                                CategoryTagRule.tag_id == body.tag_id))
    if r is None:
        r = CategoryTagRule(convention_id=c.id, category=category, tag_id=body.tag_id)
        db.add(r)
        db.commit()
    return {"id": r.id, "category": r.category, "tag_id": r.tag_id}


@router.delete(P + "/category-rules/{rule_id}")
def delete_rule(slug: str, rule_id: int, db: Session = Depends(get_session),
                user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    r = db.get(CategoryTagRule, rule_id)
    if r is None or r.convention_id != c.id:
        raise HTTPException(404, "no such rule")
    db.delete(r)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- coverage


@router.get(P + "/coverage")
def get_coverage(slug: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return venue.coverage(db, _convention(db, slug).id)


@router.post(P + "/venue/rebuild")
def rebuild_venue(slug: str, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    counts = venue.rebuild(db, _convention(db, slug).id)
    db.commit()
    return counts


class XY(BaseModel):
    x: float
    y: float


@router.patch(P + "/venue/nodes/{node_id}")
def move_node(slug: str, node_id: int, body: XY, db: Session = Depends(get_session),
              user: User = Depends(require_editor)) -> dict:
    c = _convention(db, slug)
    n = db.get(VenueNode, node_id)
    if n is None or n.convention_id != c.id:
        raise HTTPException(404, "no such node")
    n.x, n.y = body.x, body.y
    db.commit()
    return {"id": n.id, "parent_id": n.parent_id, "kind": n.kind, "label": n.label, "x": n.x, "y": n.y}


# ---------------------------------------------------------------- dispatch and floor


def _sorted_items(db: Session, apps: list[ConventionAppearance]) -> list[dict]:
    apps = sorted(apps, key=lambda a: booth_sort_key(a.hall, a.booth))
    return appearance_items(db, apps)


def _by_hall(items: list[dict]) -> list[dict]:
    halls: dict[str | None, list[dict]] = {}
    for it in items:
        halls.setdefault(it["hall"], []).append(it)
    return [{"hall": h, "appearances": a} for h, a in halls.items()]


@router.get(P + "/dispatch")
def dispatch(slug: str, tag: int | None = None, role: str | None = None, priority: str | None = None,
             assignee: str | None = None, db: Session = Depends(get_session),
             user: User = Depends(current_user)) -> dict:
    """Hall-by-hall, booth order. Hall null comes last as {"hall": null}."""
    c = _convention(db, slug)
    apps = list(db.scalars(_filtered(c.id, role=role, priority=priority, tag=tag, assignee=assignee)))
    return {"halls": _by_hall(_sorted_items(db, apps))}


@router.get(P + "/dispatch/export.xlsx")
def dispatch_export(slug: str, assignee: str | None = None, tag: int | None = None, role: str | None = None,
                    priority: str | None = None, db: Session = Depends(get_session),
                    user: User = Depends(current_user)) -> Response:
    c = _convention(db, slug)
    apps = list(db.scalars(_filtered(c.id, role=role, priority=priority, tag=tag, assignee=assignee)))
    title = f"{c.name} floor list" + (f" - {assignee}" if assignee else "")
    data = write_floor_list(title, _sorted_items(db, apps))
    fname = f"{c.slug}-floor-list{'-' + re.sub(r'[^\w-]+', '_', assignee) if assignee else ''}.xlsx"
    return Response(data, media_type=XLSX_MIME, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class DispatchIn(BaseModel):
    assignee: str | None = None
    visited: bool | None = None
    note: str | None = None


def dispatch_dict(d: DispatchAssignment) -> dict:
    return {"assignee": d.assignee, "visited": d.visited, "visited_at": d.visited_at, "note": d.note}


def _mark_visited(d: DispatchAssignment, visited: bool) -> None:
    if visited and not d.visited:
        d.visited_at = _now()
    if not visited:
        d.visited_at = None
    d.visited = visited


@router.put(P + "/appearances/{appearance_id}/dispatch")
def put_dispatch(slug: str, appearance_id: int, body: DispatchIn, db: Session = Depends(get_session),
                 user: User = Depends(require_editor)) -> dict:
    """Fields left out stay as they are; a field sent as null clears it."""
    a = _appearance(db, _convention(db, slug), appearance_id)
    d = _dispatch(db, a.id)
    fields = body.model_fields_set
    if "assignee" in fields:
        d.assignee = (body.assignee or "").strip() or None
    if "visited" in fields:
        _mark_visited(d, bool(body.visited))
    if "note" in fields:
        d.note = body.note
    db.commit()
    return dispatch_dict(d)


@router.get(P + "/floor/{person}")
def floor_list(slug: str, person: str, hall: str | None = None, db: Session = Depends(get_session),
               user: User = Depends(current_user)) -> dict:
    """One person's phone list in booth order. person="all" lists every appearance that is not
    ignored or skipped. `halls` lists the halls on the list, for the hall picker."""
    c = _convention(db, slug)
    if person.lower() == "all":
        s = _filtered(c.id).where(
            or_(ConventionAppearance.role.is_(None), ConventionAppearance.role != "ignore"),
            or_(ConventionAppearance.priority.is_(None), ConventionAppearance.priority != "skip"),
        )
    else:
        s = _filtered(c.id, assignee=person)
    apps = list(db.scalars(s))
    halls = sorted({a.hall for a in apps if a.hall}, key=lambda h: booth_sort_key(h, None))
    if hall:
        apps = [a for a in apps if (a.hall or "").lower() == hall.lower()]
    return {"person": person, "hall": hall, "halls": halls, "items": _sorted_items(db, apps)}


class FloorContact(BaseModel):
    name: str | None = None
    email: str | None = None
    title: str | None = None
    phone: str | None = None


class FloorNoteIn(BaseModel):
    text: str = Field(min_length=1)
    contact: FloorContact | None = None


def _floor_contact(db: Session, company_id: int, body: FloorContact) -> Contact | None:
    """Upsert on company + lower(email) (or name when there is no email). What a person typed
    counts as an app edit, so a later Excel import won't overwrite it."""
    values = {k: (v or "").strip() or None for k, v in body.model_dump().items()}
    if not values["name"] and not values["email"]:
        return None
    contact = None
    if values["email"]:
        contact = db.scalar(select(Contact).where(Contact.company_id == company_id,
                                                  func.lower(Contact.email) == values["email"].lower()))
    if contact is None and values["name"]:
        contact = db.scalar(select(Contact).where(Contact.company_id == company_id, Contact.email.is_(None),
                                                  func.lower(Contact.name) == values["name"].lower()))
    if contact is None:
        contact = Contact(company_id=company_id, source="floor", **values)
        db.add(contact)
    else:
        given = {k: v for k, v in values.items() if v}
        for k, v in given.items():
            setattr(contact, k, v)
        contact.edited_fields = sorted(set(contact.edited_fields or []) | set(given))
    db.flush()
    return contact


@router.post(P + "/floor/{appearance_id}/note", status_code=201)
def floor_note(slug: str, appearance_id: int, body: FloorNoteIn, db: Session = Depends(get_session),
               user: User = Depends(require_editor)) -> dict:
    """A short meeting (source='floor', met today), an optional contact, and the booth marked visited."""
    c = _convention(db, slug)
    a = _appearance(db, c, appearance_id)
    contact = _floor_contact(db, a.company_id, body.contact) if body.contact else None
    lead_id = db.scalar(select(Lead.id).where(Lead.appearance_id == a.id).order_by(Lead.id.desc()).limit(1))
    place = c.name + (f", {a.hall}.{a.booth}" if a.hall and a.booth else f", {a.hall}" if a.hall else "")
    m = Meeting(company_id=a.company_id, appearance_id=a.id, lead_id=lead_id, met_on=date.today(),
                place=place, met_by=[user.name], summary_md=body.text.strip(), source="floor",
                created_by=user.email)
    db.add(m)
    db.flush()
    if contact:
        db.add(MeetingContact(meeting_id=m.id, contact_id=contact.id))
    d = _dispatch(db, a.id)
    _mark_visited(d, True)
    d.note = body.text.strip()
    db.commit()
    return {
        "meeting": {"id": m.id, "company_id": m.company_id, "lead_id": m.lead_id, "appearance_id": m.appearance_id,
                    "met_on": m.met_on, "place": m.place, "met_by": m.met_by, "summary_md": m.summary_md,
                    "source": m.source, "created_by": m.created_by,
                    "contacts": [{"id": contact.id, "name": contact.name}] if contact else []},
        "contact_id": contact.id if contact else None,
        "dispatch": dispatch_dict(d),
    }


class FollowIn(BaseModel):
    owner: str | None = None
    contact_id: int | None = None
    notes: str | None = None


@router.post(P + "/floor/{appearance_id}/follow")
def floor_follow(slug: str, appearance_id: int, body: FollowIn | None = None, db: Session = Depends(get_session),
                 user: User = Depends(require_editor)) -> dict:
    """Creates a lead for this appearance (status 'met' when the booth was visited, else 'new').
    A second tap returns the lead that already exists for this appearance (created=false)."""
    body = body or FollowIn()
    c = _convention(db, slug)
    a = _appearance(db, c, appearance_id)
    lead = db.scalar(select(Lead).where(Lead.appearance_id == a.id).order_by(Lead.id.desc()).limit(1))
    created = lead is None
    if created:
        if body.contact_id is not None:
            ct = db.get(Contact, body.contact_id)
            if ct is None or ct.company_id != a.company_id:
                raise HTTPException(404, "no such contact at this company")
        d = db.get(DispatchAssignment, a.id)
        lead = Lead(company_id=a.company_id, appearance_id=a.id, contact_id=body.contact_id,
                    owner=(body.owner or "").strip() or user.name, notes=body.notes,
                    status="met" if d is not None and d.visited else "new")
        db.add(lead)
        db.flush()
        db.add(LeadActivity(lead_id=lead.id, kind="opened", actor=user.email,
                            data={"source": "floor", "convention": c.slug, "appearance_id": a.id}))
        db.commit()
    return {"id": lead.id, "company_id": lead.company_id, "appearance_id": lead.appearance_id,
            "contact_id": lead.contact_id, "owner": lead.owner, "status": lead.status, "notes": lead.notes,
            "follow_up_on": lead.follow_up_on, "created": created}
