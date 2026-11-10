"""Obsidian markdown export of a meeting and of a company (LEADS_PLAN 14 frontmatter).

The app is the store; this is an export only. Works on the plain dicts the routers serialize, so
it has no database access of its own.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return json.dumps(str(v), ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, (list, tuple)):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                lines += [f"  - {_scalar(x)}" for x in v]
        else:
            lines.append(f"{k}: {_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", name or "").strip()
    return re.sub(r"\s+", " ", cleaned)[:120] or "export"


def _action_line(a: dict) -> str:
    box = "x" if a.get("done_at") else " "
    extra = []
    if a.get("owner"):
        extra.append(f"@{a['owner']}")
    if a.get("due_on"):
        extra.append(f"due {_d(a['due_on'])}")
    tail = f" ({', '.join(extra)})" if extra else ""
    return f"- [{box}] {a.get('text', '')}{tail}"


def _d(v: Any) -> str:
    return v.isoformat() if isinstance(v, (date, datetime)) else str(v)


def _next_step(actions: list[dict]) -> tuple[str | None, Any]:
    open_ = [a for a in actions if not a.get("done_at")]
    dated = sorted((a for a in open_ if a.get("due_on")), key=lambda a: _d(a["due_on"]))
    first = dated[0] if dated else (open_[0] if open_ else None)
    return (first["text"], first.get("due_on")) if first else (None, None)


def _stand(appearance: dict | None) -> str | None:
    if not appearance:
        return None
    hb = " ".join(x for x in (appearance.get("hall"), appearance.get("booth")) if x)
    return hb or appearance.get("hall_booth_raw")


def meeting_body(meeting: dict, heading: str = "##") -> str:
    parts = []
    summary = (meeting.get("summary_md") or "").strip()
    parts.append(f"{heading} Summary\n\n{summary or '_No summary._'}")
    actions = meeting.get("actions") or []
    if actions:
        parts.append(f"{heading} Action items\n\n" + "\n".join(_action_line(a) for a in actions))
    return "\n\n".join(parts)


def render_meeting(meeting: dict, company: dict, appearance: dict | None = None, contacts: list[dict] | None = None) -> str:
    """One meeting as Conventions/<event>/<Company>.md style note."""
    contacts = contacts if contacts is not None else meeting.get("contacts") or []
    step, due = _next_step(meeting.get("actions") or [])
    fm = frontmatter(
        {
            "company": company.get("name"),
            "contacts": [c.get("name") or c.get("email") or "" for c in contacts],
            "roles": [c.get("title") for c in contacts if c.get("title")],
            "convention": (appearance or {}).get("convention_slug"),
            "stand": _stand(appearance),
            "date": meeting.get("met_on"),
            "met_by": meeting.get("met_by") or [],
            "place": meeting.get("place"),
            "next_step": step,
            "next_step_due": due,
            "source": meeting.get("source"),
            "leads_meeting_id": meeting.get("id"),
            "leads_company_id": company.get("id"),
        }
    )
    title = f"# {company.get('name')} — {_d(meeting.get('met_on'))}"
    return f"{fm}\n\n{title}\n\n{meeting_body(meeting)}\n"


def render_company(company: dict, meetings: list[dict]) -> str:
    """The company, its contacts, appearances, leads and every meeting (newest first)."""
    appearances = company.get("appearances") or []
    leads = company.get("leads") or []
    contacts = company.get("contacts") or []
    fm = frontmatter(
        {
            "company": company.get("name"),
            "kind": company.get("kind"),
            "country": company.get("country"),
            "city": company.get("city"),
            "website": company.get("website"),
            "domain": company.get("domain"),
            "sap_card_code": company.get("sap_card_code"),
            "categories": company.get("categories") or [],
            "conventions": [a.get("convention_slug") for a in appearances],
            "stands": [s for s in (_stand(a) for a in appearances) if s],
            "contacts": [c.get("name") or c.get("email") or "" for c in contacts],
            "lead_status": leads[0].get("status") if leads else None,
            "owner": leads[0].get("owner") if leads else None,
            "follow_up_on": leads[0].get("follow_up_on") if leads else None,
            "leads_company_id": company.get("id"),
        }
    )
    out = [fm, "", f"# {company.get('name')}", ""]

    details = [
        ("Country", company.get("country")),
        ("City", company.get("city")),
        ("Address", company.get("address")),
        ("Phone", company.get("phone")),
        ("Email", company.get("primary_email")),
        ("Website", company.get("website")),
        ("SAP CardCode", company.get("sap_card_code")),
        ("Categories", ", ".join(company.get("categories") or [])),
    ]
    out.append("## Details\n")
    out += [f"- **{k}:** {v}" for k, v in details if v]
    if company.get("description"):
        out += ["", company["description"].strip()]

    if contacts:
        out.append("\n## Contacts\n")
        for c in contacts:
            bits = [c.get("title"), c.get("email"), c.get("phone")]
            out.append(f"- {c.get('name') or '(no name)'}" + "".join(f" · {b}" for b in bits if b))

    if appearances:
        out.append("\n## Shows\n")
        for a in appearances:
            bits = [_stand(a), a.get("role"), a.get("priority"), "met at booth" if a.get("met_at_booth") else None]
            out.append(f"- {a.get('convention_slug')}" + "".join(f" · {b}" for b in bits if b))

    if leads:
        out.append("\n## Leads\n")
        for lead in leads:
            bits = [lead.get("owner"), f"follow up {_d(lead['follow_up_on'])}" if lead.get("follow_up_on") else None]
            out.append(f"- {lead.get('status')}" + "".join(f" · {b}" for b in bits if b))
            if lead.get("notes"):
                out.append(f"  - {lead['notes'].strip()}")

    if meetings:
        out.append("\n## Meetings\n")
        for m in meetings:
            who = ", ".join(m.get("met_by") or [])
            names = ", ".join(c.get("name") or "" for c in m.get("contacts") or [])
            head = f"### {_d(m.get('met_on'))}" + (f" · {m['place']}" if m.get("place") else "")
            out.append(head)
            meta = [f"met by {who}" if who else None, f"with {names}" if names else None]
            meta = [x for x in meta if x]
            if meta:
                out.append(f"_{'; '.join(meta)}_")
            out.append("")
            out.append(meeting_body(m, heading="####"))
            out.append("")
    return "\n".join(out).rstrip() + "\n"
