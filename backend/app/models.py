"""The `leads` schema in the app's own database (leads-db).

Tables follow LEADS_PLAN.md section 6 and EXHIBITION_MAPPING_PLAN.md section 4.
Rules baked in here:
- No stored company `kind`: it is derived from appearance roles (see app.services.kind).
- No SAP document ids. `companies.sap_card_code` is the only SAP key, a pointer a person confirms.
- No outcome / won / lost columns on leads. Leads are followed, never closed.
- `loop_case_id` is the case's `intake-...` id, as cases-mcp and sap-mcp take it.
Migrations only ever add.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import SCHEMA, Base

ROLES = ("lead", "supplier", "both", "ignore")
PRIORITIES = ("must_visit", "nice_to_visit", "skip")
LEAD_STATUSES = ("new", "met", "follow_up", "talking", "parked")
SUGGESTION_REASONS = ("card_code", "contact_email", "domain")
SUGGESTION_STATUSES = ("pending", "accepted", "dismissed")
LINK_HOW = ("manual", "suggested")
VENUE_KINDS = ("floor", "hall", "room", "booth")


def _in(col: str, values: tuple[str, ...], nullable: bool = False) -> str:
    vals = ", ".join(f"'{v}'" for v in values)
    expr = f"{col} IN ({vals})"
    return f"{col} IS NULL OR {expr}" if nullable else expr


def fk(target: str, ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.{target}", ondelete=ondelete)


TS = DateTime(timezone=True)


class Convention(Base):
    __tablename__ = "conventions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    venue_map_file: Mapped[str | None] = mapped_column(Text)  # path under leads-files
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    convention_id: Mapped[int | None] = mapped_column(fk("conventions.id", "SET NULL"))
    source: Mapped[str] = mapped_column(Text)  # excel | obsidian | jira
    file: Mapped[str | None] = mapped_column(Text)  # stored path under leads-files
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    rows: Mapped[int] = mapped_column(Integer, server_default="0")
    created: Mapped[int] = mapped_column(Integer, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, server_default="0")
    conflicts: Mapped[int] = mapped_column(Integer, server_default="0")
    report: Mapped[dict | None] = mapped_column(JSONB)  # conflict list, per-sheet counts
    actor: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_name_normalized", "name_normalized"),
        Index("ix_companies_domain", "domain"),
        Index("ix_companies_country", "country"),
        Index("ix_companies_sap_card_code", "sap_card_code"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_normalized: Mapped[str] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    primary_email: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    description: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    sap_card_code: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    import_batch_id: Mapped[int | None] = mapped_column(fk("import_batches.id", "SET NULL"))
    raw: Mapped[dict | None] = mapped_column(JSONB)
    edited_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    merged_into_id: Mapped[int | None] = mapped_column(fk("companies.id", "SET NULL"))  # manual merge
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class ConventionAppearance(Base):
    __tablename__ = "convention_appearances"
    __table_args__ = (
        UniqueConstraint("company_id", "convention_id", name="uq_appearance_company_convention"),
        CheckConstraint(_in("role", ROLES, nullable=True), name="ck_appearance_role"),
        CheckConstraint(_in("priority", PRIORITIES, nullable=True), name="ck_appearance_priority"),
        Index("ix_appearances_convention_hall_booth", "convention_id", "hall", "booth"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(fk("companies.id"))
    convention_id: Mapped[int] = mapped_column(fk("conventions.id"))
    hall: Mapped[str | None] = mapped_column(Text)
    booth: Mapped[str | None] = mapped_column(Text)
    hall_booth_raw: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)  # null until a person confirms
    priority: Mapped[str | None] = mapped_column(Text)
    met_at_booth: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    edited_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index(
            "uq_contacts_company_email",
            "company_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(fk("companies.id"))
    name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)  # excel | app | floor
    raw: Mapped[dict | None] = mapped_column(JSONB)
    edited_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(_in("status", LEAD_STATUSES), name="ck_lead_status"),
        Index("ix_leads_company", "company_id"),
        Index("ix_leads_status_follow_up", "status", "follow_up_on"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(fk("companies.id"))
    appearance_id: Mapped[int | None] = mapped_column(fk("convention_appearances.id", "SET NULL"))
    contact_id: Mapped[int | None] = mapped_column(fk("contacts.id", "SET NULL"))
    owner: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="new")
    notes: Mapped[str | None] = mapped_column(Text)
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class LeadCase(Base):
    __tablename__ = "lead_cases"
    __table_args__ = (
        CheckConstraint(_in("how", LINK_HOW), name="ck_lead_case_how"),
        Index("ix_lead_cases_case", "loop_case_id"),
        {"schema": SCHEMA},
    )

    lead_id: Mapped[int] = mapped_column(fk("leads.id"), primary_key=True)
    loop_case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    linked_by: Mapped[str | None] = mapped_column(Text)
    linked_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    how: Mapped[str] = mapped_column(Text, server_default="manual")


class CaseSuggestion(Base):
    __tablename__ = "case_suggestions"
    __table_args__ = (
        UniqueConstraint("lead_id", "loop_case_id", name="uq_suggestion_lead_case"),
        CheckConstraint(_in("reason", SUGGESTION_REASONS), name="ck_suggestion_reason"),
        CheckConstraint(_in("status", SUGGESTION_STATUSES), name="ck_suggestion_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(fk("leads.id"))
    loop_case_id: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_company_met_on", "company_id", "met_on"),
        Index(
            "ix_meetings_summary_fts",
            text("to_tsvector('simple', coalesce(summary_md, ''))"),
            postgresql_using="gin",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(fk("companies.id"))
    lead_id: Mapped[int | None] = mapped_column(fk("leads.id", "SET NULL"))
    appearance_id: Mapped[int | None] = mapped_column(fk("convention_appearances.id", "SET NULL"))
    met_on: Mapped[date] = mapped_column(Date)
    starts_at: Mapped[datetime | None] = mapped_column(TS)
    place: Mapped[str | None] = mapped_column(Text)
    met_by: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    summary_md: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="app")  # app | floor | obsidian
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class MeetingContact(Base):
    __tablename__ = "meeting_contacts"
    __table_args__ = {"schema": SCHEMA}

    meeting_id: Mapped[int] = mapped_column(fk("meetings.id"), primary_key=True)
    contact_id: Mapped[int] = mapped_column(fk("contacts.id"), primary_key=True)


class MeetingAction(Base):
    __tablename__ = "meeting_actions"
    __table_args__ = (Index("ix_meeting_actions_meeting", "meeting_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(fk("meetings.id"))
    text: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    due_on: Mapped[date | None] = mapped_column(Date)
    done_at: Mapped[datetime | None] = mapped_column(TS)


class LeadActivity(Base):
    __tablename__ = "lead_activity"
    __table_args__ = (Index("ix_lead_activity_lead_at", "lead_id", "at"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(fk("leads.id"))
    kind: Mapped[str] = mapped_column(Text)  # opened | edited | linked | unlinked | ...
    at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    actor: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)


# ---- Exhibition mapping (EXHIBITION_MAPPING_PLAN.md section 4) ----


class TagGroup(Base):
    __tablename__ = "tag_groups"
    __table_args__ = (UniqueConstraint("convention_id", "name", name="uq_tag_group_name"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(primary_key=True)
    convention_id: Mapped[int] = mapped_column(fk("conventions.id"))
    name: Mapped[str] = mapped_column(Text)


class HardwareTag(Base):
    __tablename__ = "hardware_tags"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    group_id: Mapped[int | None] = mapped_column(fk("tag_groups.id", "SET NULL"))


class CategoryTagRule(Base):
    """Raw organizer category -> our tag, per show (the Tags screen). Drives mapping suggestions."""

    __tablename__ = "category_tag_rules"
    __table_args__ = (
        UniqueConstraint("convention_id", "category", "tag_id", name="uq_category_tag_rule"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    convention_id: Mapped[int] = mapped_column(fk("conventions.id"))
    category: Mapped[str] = mapped_column(Text)  # raw category string, or a keyword
    tag_id: Mapped[int] = mapped_column(fk("hardware_tags.id"))


class AppearanceMapping(Base):
    __tablename__ = "appearance_mapping"
    __table_args__ = (
        CheckConstraint(_in("suggested_role", ROLES, nullable=True), name="ck_mapping_suggested_role"),
        {"schema": SCHEMA},
    )

    appearance_id: Mapped[int] = mapped_column(fk("convention_appearances.id"), primary_key=True)
    suggested_role: Mapped[str | None] = mapped_column(Text)
    suggested_priority: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(TS)


class AppearanceTag(Base):
    __tablename__ = "appearance_tags"
    __table_args__ = {"schema": SCHEMA}

    appearance_id: Mapped[int] = mapped_column(fk("convention_appearances.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(fk("hardware_tags.id"), primary_key=True)
    suggested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class VenueNode(Base):
    __tablename__ = "venue_nodes"
    __table_args__ = (
        CheckConstraint(_in("kind", VENUE_KINDS), name="ck_venue_kind"),
        Index("ix_venue_nodes_convention", "convention_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    convention_id: Mapped[int] = mapped_column(fk("conventions.id"))
    parent_id: Mapped[int | None] = mapped_column(fk("venue_nodes.id"))
    kind: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    x: Mapped[float | None] = mapped_column(Float)  # saved when people drag
    y: Mapped[float | None] = mapped_column(Float)


class DispatchAssignment(Base):
    __tablename__ = "dispatch_assignments"
    __table_args__ = {"schema": SCHEMA}

    appearance_id: Mapped[int] = mapped_column(fk("convention_appearances.id"), primary_key=True)
    assignee: Mapped[str | None] = mapped_column(Text)
    visited: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    visited_at: Mapped[datetime | None] = mapped_column(TS)
    note: Mapped[str | None] = mapped_column(Text)

