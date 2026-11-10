"""Small, pure helpers for cleaning Excel values: company names, domains, hall/booth, dates.

Nothing here touches the database, so it is easy to test on its own.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlsplit

# Legal-form words stripped from the end of a company name (after dots and quotes are removed).
LEGAL_SUFFIXES = {
    "gmbh", "mbh", "ag", "kg", "kgaa", "ohg", "ug", "se", "ev",
    "co", "company", "corp", "corporation", "inc", "incorporated", "llc", "llp", "lp",
    "ltd", "limited", "plc", "pty", "pte", "pvt", "private",
    "sa", "sas", "sarl", "srl", "spa", "sl", "slu", "sro", "as", "asa", "ab", "oy", "oyj",
    "bv", "nv", "aps", "kk", "zoo", "sp", "jsc", "ooo", "doo", "kft", "zrt", "bhd", "sdn",
    "בעמ",
}

# Free-mail domains never count as a company's domain (LEADS_PLAN 18 "Matching").
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.de", "yahoo.co.uk", "ymail.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "gmx.de", "gmx.net", "gmx.com", "web.de", "t-online.de", "freenet.de",
    "mail.com", "mail.ru", "yandex.ru", "yandex.com", "protonmail.com", "proton.me",
    "163.com", "126.com", "qq.com", "foxmail.com", "sina.com", "sohu.com", "aliyun.com",
    "naver.com", "hanmail.net", "walla.co.il", "zoho.com",
}


def clean(value) -> str | None:
    """A cell as a trimmed string, or None when empty."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # phone numbers typed as numbers
    s = str(value).strip()
    return s or None


def normalize_name(name: str | None) -> str:
    """Lowercase, accents folded, punctuation and trailing legal suffixes removed.

    "ACME Electronics GmbH & Co. KG" -> "acme electronics"
    "Shenzhen Foo Co., Ltd."          -> "shenzhen foo"
    'אלביט מערכות בע"מ'               -> "אלביט מערכות"
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[.'\"׳״`’]", "", s)  # dots and quotes: "s.a." -> "sa", בע"מ -> בעמ
    s = re.sub(r"[^\w]+", " ", s)  # everything else that is not a letter/digit becomes a space
    tokens = s.split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def domain_from_website(website: str | None) -> str | None:
    s = clean(website)
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    try:
        host = urlsplit(s).hostname or ""
    except ValueError:
        return None
    host = host.lower().strip(".")
    host = re.sub(r"^www\d*\.", "", host)
    return host if "." in host else None


def domain_from_email(email: str | None) -> str | None:
    s = clean(email)
    if not s or "@" not in s:
        return None
    host = s.rsplit("@", 1)[1].strip().lower().strip(".>")
    return host if "." in host else None


def company_domain(website: str | None, email: str | None) -> str | None:
    """The dedupe domain: from the website, else from the email. Free-mail never counts."""
    for d in (domain_from_website(website), domain_from_email(email)):
        if d and d not in FREE_MAIL_DOMAINS:
            return d
    return None


# Hall/booth, e.g. "A3.123", "Hall B4 / 411", "C5-210", "Halle A3, Stand 123", "B4.411, B4.412".
_HALL_BOOTH = re.compile(r"^([A-Z]{1,2}\d{0,2}|\d{1,2})\s*[./\-,:\s]\s*([A-Z]?\d+[A-Z]?(?:[./]\d+)?)\b")
_HALL_ONLY = re.compile(r"^([A-Z]{1,2}\d{0,2}|\d{1,2})$")


def split_hall_booth(raw: str | None) -> tuple[str | None, str | None]:
    """Returns (hall, booth). Unparseable values give (None, None); the raw text is kept elsewhere.
    When a company has several booths, the first one is used."""
    s = clean(raw)
    if not s:
        return None, None
    s = s.upper()
    s = re.sub(r"\b(HALL|HALLE|BOOTH|STAND|STANDS|BOOTHS)\b\.?", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;/-")
    if m := _HALL_BOOTH.match(s):
        return m.group(1), m.group(2)
    if m := _HALL_ONLY.match(s):
        return m.group(1), None
    return None, None


def split_categories(value) -> list[str]:
    """Categories split on ';', ',' or newline, trimmed, duplicates dropped, order kept."""
    s = clean(value)
    if not s:
        return []
    out: list[str] = []
    for part in re.split(r"[;,\n\r]+", s):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def parse_date(value) -> date | None:
    """Excel date cell, or a string like 2026-11-20, 20.11.2026 or 20/11/2026. Raises ValueError."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"not a date: {s!r}")


_TRUE = {"yes", "y", "true", "x", "1", "ja", "j", "met", "✓", "✔", "v", "done"}


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    s = clean(value)
    return bool(s) and s.lower() in _TRUE


LEAD_STATUS_ALIASES = {
    "new": "new",
    "met": "met",
    "follow_up": "follow_up",
    "follow up": "follow_up",
    "follow-up": "follow_up",
    "followup": "follow_up",
    "talking": "talking",
    "parked": "parked",
}


def map_lead_status(value) -> str | None:
    """A Lead status cell mapped to one of the app statuses, or None when it does not map cleanly."""
    s = clean(value)
    if not s:
        return None
    return LEAD_STATUS_ALIASES.get(re.sub(r"\s+", " ", s.lower()))


def booth_sort_key(hall: str | None, booth: str | None) -> tuple:
    """Natural order: hall A1 < A2 < A10, booth 9 < 101 < 101A. Missing hall/booth sort last."""

    def natural(s: str | None) -> tuple:
        if not s:
            return (1, ())
        parts = re.split(r"(\d+)", s)
        return (0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p))

    return (natural(hall), natural(booth))


def json_safe(value):
    """Cell value for the raw jsonb column."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
