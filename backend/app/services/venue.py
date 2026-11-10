"""The coverage hierarchy (EXHIBITION_MAPPING_PLAN 3.4, UI_PLAN): floor -> hall -> booth,
built from the hall/booth on the show's appearances. Positions (x, y) people saved by dragging
are kept across rebuilds because nodes are matched by their path of labels.

electronica-style halls ("A3", "B4", "C5") are grouped under a floor node named after the
letter ("A"); halls without a letter prefix go under "Venue".
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppearanceMapping, AppearanceTag, Company, ConventionAppearance, DispatchAssignment, VenueNode
from .normalize import booth_sort_key

KIND_BY_DEPTH = {1: "floor", 2: "hall", 3: "booth"}


def floor_label(hall: str) -> str:
    m = re.match(r"[A-Za-z]+", hall)
    return m.group(0).upper() if m else "Venue"


def appearance_path(hall: str | None, booth: str | None) -> tuple[str, ...] | None:
    """Label path of the deepest node an appearance sits on, or None when it has no hall."""
    if not hall:
        return None
    return (floor_label(hall), hall, booth) if booth else (floor_label(hall), hall)


def _paths_of(nodes: list[VenueNode]) -> dict[tuple[str, ...], VenueNode]:
    by_id = {n.id: n for n in nodes}
    out = {}
    for n in nodes:
        labels, cur, hops = [], n, 0
        while cur is not None and hops < 10:
            labels.append(cur.label)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
            hops += 1
        out[tuple(reversed(labels))] = n
    return out


def node_paths(db: Session, convention_id: int) -> dict[tuple[str, ...], VenueNode]:
    nodes = list(db.scalars(select(VenueNode).where(VenueNode.convention_id == convention_id)))
    return _paths_of(nodes)


def rebuild(db: Session, convention_id: int) -> dict:
    """Make venue_nodes match the hall/booth values. Adds what is missing, removes what no
    appearance uses any more, keeps everything else (and its x, y)."""
    needed: set[tuple[str, ...]] = set()
    for hall, booth in db.execute(
        select(ConventionAppearance.hall, ConventionAppearance.booth).where(
            ConventionAppearance.convention_id == convention_id
        )
    ):
        path = appearance_path(hall, booth)
        if path:
            for depth in range(1, len(path) + 1):
                needed.add(path[:depth])

    existing = node_paths(db, convention_id)
    removed = 0
    # Deepest first, so children go before their parents.
    for path in sorted(existing, key=len, reverse=True):
        if path not in needed:
            db.delete(existing.pop(path))
            removed += 1
    db.flush()

    created = 0
    for path in sorted(needed, key=lambda p: (len(p), booth_sort_key(p[-2] if len(p) > 1 else p[0], p[-1]))):
        if path in existing:
            continue
        parent = existing.get(path[:-1]) if len(path) > 1 else None
        node = VenueNode(convention_id=convention_id, parent_id=parent.id if parent else None,
                         kind=KIND_BY_DEPTH[len(path)], label=path[-1])
        db.add(node)
        db.flush()
        existing[path] = node
        created += 1

    kinds = [len(p) for p in needed]
    return {"floors": kinds.count(1), "halls": kinds.count(2), "booths": kinds.count(3),
            "created": created, "removed": removed}


def coverage(db: Session, convention_id: int) -> dict:
    """Nodes with visit stats, and every appearance placed on its booth (or hall) node."""
    paths = node_paths(db, convention_id)
    stats = {n.id: {"total": 0, "visited": 0, "must_visit_uncovered": 0, "skipped": 0} for n in paths.values()}
    rows = db.execute(
        select(ConventionAppearance, Company.name, DispatchAssignment.visited)
        .join(Company, Company.id == ConventionAppearance.company_id)
        .outerjoin(DispatchAssignment, DispatchAssignment.appearance_id == ConventionAppearance.id)
        .where(ConventionAppearance.convention_id == convention_id)
    ).all()
    # tags and suggested role per appearance, so the coverage legend can filter and highlight
    tags_by_app: dict[int, list[dict]] = {}
    for at in db.scalars(
        select(AppearanceTag)
        .join(ConventionAppearance, ConventionAppearance.id == AppearanceTag.appearance_id)
        .where(ConventionAppearance.convention_id == convention_id)
    ):
        tags_by_app.setdefault(at.appearance_id, []).append({"tag_id": at.tag_id, "confirmed": bool(at.confirmed)})
    suggested_role = dict(db.execute(
        select(AppearanceMapping.appearance_id, AppearanceMapping.suggested_role)
        .join(ConventionAppearance, ConventionAppearance.id == AppearanceMapping.appearance_id)
        .where(ConventionAppearance.convention_id == convention_id)
    ).all())
    booths = []
    unplaced = {"total": 0, "visited": 0, "must_visit_uncovered": 0, "skipped": 0}
    for a, company_name, visited in sorted(rows, key=lambda r: booth_sort_key(r[0].hall, r[0].booth)):
        visited = bool(visited)
        path = appearance_path(a.hall, a.booth)
        node = paths.get(path) if path else None
        targets = [stats[paths[path[:d]].id] for d in range(1, len(path) + 1) if path[:d] in paths] if node else [unplaced]
        for s in targets:
            s["total"] += 1
            s["visited"] += visited
            s["must_visit_uncovered"] += a.priority == "must_visit" and not visited
            s["skipped"] += a.priority == "skip"
        if node:
            booths.append({"node_id": node.id, "appearance_id": a.id, "company_id": a.company_id, "company_name": company_name,
                           "priority": a.priority, "visited": visited, "role": a.role,
                           "suggested_role": suggested_role.get(a.id), "tags": tags_by_app.get(a.id, [])})
    nodes = sorted(paths.items(), key=lambda kv: (len(kv[0]), booth_sort_key(kv[0][-2] if len(kv[0]) > 1 else kv[0][0], kv[0][-1])))
    return {
        "nodes": [{"id": n.id, "parent_id": n.parent_id, "kind": n.kind, "label": n.label,
                   "x": n.x, "y": n.y, "stats": stats[n.id]} for _, n in nodes],
        "booths": booths,
        "unplaced": unplaced,
    }
