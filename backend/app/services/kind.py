"""Derived company kind. Never stored: computed from the roles on the company's appearances.

Rules (docs/API.md):
- no confirmed role (all null)              -> "unmapped"
- every confirmed role is ignore            -> "ignore"
- supplier side and lead side both present  -> "both"
- only supplier side                        -> "supplier"
- only lead side                            -> "lead"

A role of "both" counts on both sides, so a single "both" appearance gives kind "both".
Ignore roles are skipped when the company has any other confirmed role.
`kind_sql` is the same rule as a SQL expression, for filtering lists by kind.
"""

from collections.abc import Iterable

from sqlalchemy import case, func, select

from app.models import ConventionAppearance

KINDS = ("lead", "supplier", "both", "unmapped", "ignore")


def derive_kind(roles: Iterable[str | None]) -> str:
    confirmed = [r for r in roles if r]
    if not confirmed:
        return "unmapped"
    supplier_side = any(r in ("supplier", "both") for r in confirmed)
    lead_side = any(r in ("lead", "both") for r in confirmed)
    if supplier_side and lead_side:
        return "both"
    if supplier_side:
        return "supplier"
    if lead_side:
        return "lead"
    return "ignore"


def kind_by_company_subquery():
    """(company_id, kind) for every company that has at least one appearance."""
    a = ConventionAppearance
    supplier_side = func.bool_or(a.role.in_(("supplier", "both")))
    lead_side = func.bool_or(a.role.in_(("lead", "both")))
    kind = case(
        (supplier_side & lead_side, "both"),
        (supplier_side, "supplier"),
        (lead_side, "lead"),
        (func.count(a.role) > 0, "ignore"),
        else_="unmapped",
    )
    return select(a.company_id.label("company_id"), kind.label("kind")).group_by(a.company_id).subquery()
