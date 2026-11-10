"""Mapping suggestions (EXHIBITION_MAPPING_PLAN 3.3).

Simple keyword rules over the organizer categories and description we copied from the show's
website, plus the show's category_tag_rules (Tags screen). Results go into
appearance_mapping.suggested_role and appearance_tags (suggested=true, confirmed=false).
Nothing here ever confirms: a person does that, and confirmed appearances are left alone.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AppearanceMapping,
    AppearanceTag,
    CategoryTagRule,
    Company,
    ConventionAppearance,
    HardwareTag,
)

# Built-in keyword -> tag name rules. Used only for tags that already exist on the Tags screen,
# so running suggestions never invents tags. A starting point; the show's own category rules
# (category_tag_rules) are the main source.
TAG_KEYWORDS: dict[str, list[str]] = {
    "RAM": ["dram", "sdram", "ddr3", "ddr4", "ddr5", "lpddr", "memory module", "memory modules", "ram"],
    "GPU": ["gpu", "gpus", "graphics card", "graphics cards", "graphics processor"],
    "Disks": ["ssd", "ssds", "hdd", "hard disk", "hard drive", "solid state", "nvme", "disk", "disks"],
    "Flash": ["nand", "flash memory", "emmc", "nor flash"],
    "CPU": ["cpu", "cpus", "processor", "processors", "microprocessor"],
    "Internal parts": ["connector", "connectors", "cable assemblies", "fan", "fans", "heatsink",
                       "power supply", "power supplies", "psu", "motherboard", "mainboard"],
    "Displays": ["display", "displays", "lcd", "tft", "oled"],
}

# Role keywords. Any suggested hardware tag also counts as a supplier signal.
ROLE_KEYWORDS: dict[str, list[str]] = {
    "supplier": ["manufacturer", "manufacturing", "distributor", "distribution", "supplier",
                 "semiconductor", "semiconductors", "components", "oem", "odm", "factory"],
    "lead": ["system integrator", "systems integrator", "integrator", "reseller", "solution provider",
             "end user", "data center", "datacenter", "research institute", "university"],
}


def _contains(text: str, keyword: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", text) is not None


def suggest_for(company: Company, rules: list[CategoryTagRule], tag_ids_by_name: dict[str, int]) -> tuple[str | None, set[int]]:
    """(suggested role, suggested tag ids) for one company. Pure, so it is easy to test."""
    categories = [c.lower().strip() for c in company.categories or []]
    text = " \n ".join(categories + [(company.description or "").lower()])
    tags: set[int] = set()
    for r in rules:
        cat = r.category.lower().strip()
        if cat in categories or _contains(text, cat):
            tags.add(r.tag_id)
    for tag_name, keywords in TAG_KEYWORDS.items():
        tag_id = tag_ids_by_name.get(tag_name.lower())
        if tag_id and any(_contains(text, k) for k in keywords):
            tags.add(tag_id)
    supplier = bool(tags) or any(_contains(text, k) for k in ROLE_KEYWORDS["supplier"])
    lead = any(_contains(text, k) for k in ROLE_KEYWORDS["lead"])
    role = "both" if supplier and lead else "supplier" if supplier else "lead" if lead else None
    return role, tags


def run_suggestions(db: Session, convention_id: int) -> dict:
    """Recompute suggestions for every unconfirmed appearance of the show. Stale suggested
    (unconfirmed) tags are removed; tags a person added or confirmed are never touched."""
    rules = list(db.scalars(select(CategoryTagRule).where(CategoryTagRule.convention_id == convention_id)))
    tag_ids_by_name = {t.name.lower(): t.id for t in db.scalars(select(HardwareTag))}
    rows = db.execute(
        select(ConventionAppearance, Company, AppearanceMapping)
        .join(Company, Company.id == ConventionAppearance.company_id)
        .outerjoin(AppearanceMapping, AppearanceMapping.appearance_id == ConventionAppearance.id)
        .where(ConventionAppearance.convention_id == convention_id)
    ).all()
    unconfirmed = [(a, c, m) for a, c, m in rows if m is None or m.confirmed_at is None]
    ids = [a.id for a, _, _ in unconfirmed]
    existing: dict[int, dict[int, AppearanceTag]] = {}
    if ids:
        for at in db.scalars(select(AppearanceTag).where(AppearanceTag.appearance_id.in_(ids))):
            existing.setdefault(at.appearance_id, {})[at.tag_id] = at

    counts = {"appearances": len(unconfirmed), "roles_suggested": 0, "tags_suggested": 0, "tags_removed": 0}
    for a, company, mapping in unconfirmed:
        role, tags = suggest_for(company, rules, tag_ids_by_name)
        if mapping is None:
            mapping = AppearanceMapping(appearance_id=a.id)
            db.add(mapping)
        mapping.suggested_role = role
        if role:
            counts["roles_suggested"] += 1
        have = existing.get(a.id, {})
        for tag_id in tags - have.keys():
            db.add(AppearanceTag(appearance_id=a.id, tag_id=tag_id, suggested=True, confirmed=False))
            counts["tags_suggested"] += 1
        stale = [t for t_id, t in have.items() if t_id not in tags and t.suggested and not t.confirmed]
        for t in stale:
            db.delete(t)
            counts["tags_removed"] += 1
    db.flush()
    return counts
