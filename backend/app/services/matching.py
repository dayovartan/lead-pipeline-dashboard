"""Case suggestions for a lead (LEADS_PLAN 8). Pull, not push; nothing links automatically.

Order of lookups, first reason wins for a case:
1. card_code     - customer_timeline(card_code) when the company has a confirmed sap_card_code
2. contact_email - search_mails(sender=<email>) then thread_outline(conversation_id) per thread
3. domain        - list_senders(domain) and, when anyone at the domain wrote, search_mails on
                   "@domain" then thread_outline per thread. Free-mail domains and our own
                   dayo-tech.com are skipped here (an exact contact email still matches in step 2,
                   except our own addresses, which never match).

Cases already linked to the lead are skipped. A dismissed (or accepted) suggestion keeps its row,
and the unique (lead_id, loop_case_id) constraint means it is never suggested again.

The exact MCP answer shapes are parsed in the small `*_from` functions below, defensively: case
ids are any string value starting with "intake-" under a loop_case_id / case_id / id key. Adjust
those functions when checked against the real tools. NOTE: today customer_timeline and
thread_outline return the uuid `case_id` of the cases table and not `loop_case_id`, so against the
current cases-mcp nothing will be suggested until those tools include loop_case_id (a read-only
change in cases-mcp, not in the loop's database).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import CaseSuggestion, Company, Contact, Lead, LeadCase

OWN_DOMAINS = frozenset({"dayo-tech.com"})
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com",
        "msn.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "icloud.com", "me.com", "mac.com",
        "aol.com", "gmx.com", "gmx.de", "gmx.net", "web.de", "t-online.de", "mail.com",
        "protonmail.com", "proton.me", "zoho.com", "yandex.com", "yandex.ru", "mail.ru",
        "qq.com", "163.com", "126.com", "sina.com", "walla.co.il", "walla.com", "bezeqint.net",
        "netvision.net.il", "012.net.il",
    }
)
REASON_ORDER = ("card_code", "contact_email", "domain")
MAX_CONTACTS = 5
MAX_THREADS = 10
CASE_ID_KEYS = ("loop_case_id", "case_id", "id")


# ---- Parsing of MCP answers (adjust against the real tools) ----------------------------


def intake_ids(obj: Any) -> list[str]:
    """Every "intake-..." id under a case id key, anywhere in the structure, in order."""
    found: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k in CASE_ID_KEYS:
                v = o.get(k)
                if isinstance(v, str) and v.startswith("intake-") and v not in found:
                    found.append(v)
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found


def case_ids_from_timeline(data: Any) -> list[str]:
    if isinstance(data, dict) and "cases" in data:
        return intake_ids(data["cases"])
    return intake_ids(data)


def case_ids_from_outline(data: Any) -> list[str]:
    if isinstance(data, dict) and "cases" in data:
        return intake_ids(data["cases"])
    return intake_ids(data)


def _mails(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("mails") or data.get("hits") or data.get("results") or []
    return [m for m in data if isinstance(m, dict)] if isinstance(data, list) else []


def _sender(mail: dict) -> str:
    return str(mail.get("from_addr") or mail.get("sender") or mail.get("from") or "").strip().lower()


def conversations_from_mails(data: Any, sender_ok) -> list[str]:
    """Conversation ids of the mails whose sender passes `sender_ok`, in answer order."""
    out: list[str] = []
    for m in _mails(data):
        conv = m.get("conversation_id") or m.get("conversationId")
        if conv and sender_ok(_sender(m)) and conv not in out:
            out.append(str(conv))
    return out


def senders_from(data: Any) -> list[str]:
    rows = data.get("senders") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [str(s.get("from_addr") or s.get("address") or "").lower() for s in rows if isinstance(s, dict)]


# ---- Lookup ----------------------------------------------------------------------------


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


def company_domain(company: Company) -> str | None:
    d = (company.domain or "").strip().lower().removeprefix("www.")
    return d or email_domain(company.primary_email)


def domain_matchable(domain: str | None) -> bool:
    return bool(domain) and domain not in FREE_MAIL_DOMAINS and domain not in OWN_DOMAINS


@dataclass
class MatchResult:
    found: list[tuple[str, str]] = field(default_factory=list)  # (loop_case_id, reason)
    calls: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.failures or self.calls > len(self.failures)

    @property
    def reason(self) -> str | None:
        return self.failures[0] if self.failures else None

    def add(self, ids: list[str], reason: str) -> None:
        seen = {cid for cid, _ in self.found}
        for cid in ids:
            if cid not in seen:
                self.found.append((cid, reason))
                seen.add(cid)


def find_cases(mcp, company: Company, emails: list[str]) -> MatchResult:
    res = MatchResult()
    outlines: dict[str, list[str]] = {}

    def call(server: str, tool: str, args: dict):
        res.calls += 1
        r = mcp.call(server, tool, args)
        if not r.get("available"):
            res.failures.append(r.get("reason") or "not available")
            return None
        return r.get("data")

    def cases_of_threads(conversations: list[str]) -> list[str]:
        ids: list[str] = []
        for conv in conversations[:MAX_THREADS]:
            if conv not in outlines:
                outlines[conv] = case_ids_from_outline(call("cases", "thread_outline", {"conversation_id": conv}))
            ids += [c for c in outlines[conv] if c not in ids]
        return ids

    # 1. CardCode
    if company.sap_card_code:
        data = call("cases", "customer_timeline", {"card_code": company.sap_card_code})
        res.add(case_ids_from_timeline(data), "card_code")

    # 2. Contact emails (exact address, free-mail allowed, never our own)
    for email in emails[:MAX_CONTACTS]:
        data = call("cases", "search_mails", {"query": "", "sender": email, "limit": 20})
        convs = conversations_from_mails(data, lambda s, e=email: s == e)
        res.add(cases_of_threads(convs), "contact_email")

    # 3. Domain
    domain = company_domain(company)
    if domain_matchable(domain):
        senders = senders_from(call("cases", "list_senders", {"domain": domain, "limit": 50}))
        if senders:
            data = call("cases", "search_mails", {"query": "", "sender": f"@{domain}", "limit": 20})
            convs = conversations_from_mails(data, lambda s: s.endswith(f"@{domain}"))
            res.add(cases_of_threads(convs), "domain")
    return res


def lead_emails(db: Session, lead: Lead) -> list[str]:
    """The lead's contact first, then the company's other contacts; lowercased, deduped, no own."""
    contacts = db.scalars(select(Contact).where(Contact.company_id == lead.company_id).order_by(Contact.id)).all()
    contacts = sorted(contacts, key=lambda c: c.id != lead.contact_id)
    out: list[str] = []
    for c in contacts:
        e = (c.email or "").strip().lower()
        if e and "@" in e and email_domain(e) not in OWN_DOMAINS and e not in out:
            out.append(e)
    return out


def refresh_suggestions(db: Session, mcp, lead: Lead) -> MatchResult:
    """Run the lookup and add new pending suggestions. Commits."""
    company = db.get(Company, lead.company_id)
    res = find_cases(mcp, company, lead_emails(db, lead))
    linked = set(db.scalars(select(LeadCase.loop_case_id).where(LeadCase.lead_id == lead.id)))
    for cid, reason in res.found:
        if cid in linked:
            continue
        db.execute(
            insert(CaseSuggestion)
            .values(lead_id=lead.id, loop_case_id=cid, reason=reason, status="pending")
            .on_conflict_do_nothing(constraint="uq_suggestion_lead_case")
        )
    db.commit()
    return res


def pending_suggestions(db: Session, lead_id: int) -> list[CaseSuggestion]:
    linked = select(LeadCase.loop_case_id).where(LeadCase.lead_id == lead_id)
    rows = db.scalars(
        select(CaseSuggestion)
        .where(
            CaseSuggestion.lead_id == lead_id,
            CaseSuggestion.status == "pending",
            CaseSuggestion.loop_case_id.not_in(linked),
        )
        .order_by(CaseSuggestion.id)
    ).all()
    return sorted(rows, key=lambda s: REASON_ORDER.index(s.reason))
