"""Excel in and out (openpyxl). Excel is import and export only, never the store."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

# Expected workbook (docs/API.md, LEADS_PLAN 14). key -> header as written in the template.
EXHIBITOR_COLUMNS = {
    "company": "Company",
    "country": "Country",
    "city": "City",
    "address": "Address",
    "phone": "Phone",
    "primary_email": "Primary email",
    "website": "Website",
    "hall_booth": "Hall/Booth",
    "categories": "Categories",
    "description": "Description",
    "profile_url": "Profile URL",
    "met_at_booth": "Met at booth",
    "lead_status": "Lead status",
    "owner": "Owner",
    "notes": "Notes",
    "follow_up_date": "Follow-up date",
    "meeting_note": "Meeting note",
}
CONTACT_COLUMNS = {
    "company": "Company",
    "name": "Name",
    "title": "Title",
    "email": "Email",
    "phone": "Phone",
}

# A few header spellings people actually type. Headers are matched case-insensitively.
HEADER_ALIASES = {
    "hall / booth": "hall_booth",
    "hall-booth": "hall_booth",
    "hall booth": "hall_booth",
    "booth": "hall_booth",
    "email": "primary_email",
    "e-mail": "primary_email",
    "follow up date": "follow_up_date",
    "followup date": "follow_up_date",
    "follow-up": "follow_up_date",
    "company name": "company",
}


def _header_key(header, columns: dict[str, str], aliases: dict[str, str]) -> str | None:
    if header is None:
        return None
    h = " ".join(str(header).split()).lower()
    for key, label in columns.items():
        if h == label.lower():
            return key
    key = aliases.get(h)
    return key if key in columns else None


def read_sheet(ws, columns: dict[str, str], aliases: dict[str, str] | None = None) -> list[dict]:
    """Rows of a sheet as dicts: {"_row": excel row number, "_raw": {header: value}, key: value}.
    The first non-empty row is the header row. Fully empty rows are dropped."""
    aliases = aliases or {}
    rows = ws.iter_rows(values_only=True)
    headers: list | None = None
    header_row = 0
    for i, values in enumerate(rows, start=1):
        if any(v not in (None, "") for v in values):
            headers, header_row = list(values), i
            break
    if headers is None:
        return []
    keys = [_header_key(h, columns, aliases) for h in headers]
    out = []
    for i, values in enumerate(rows, start=header_row + 1):
        if not any(v not in (None, "") for v in values):
            continue
        row: dict = {"_row": i, "_raw": {}}
        for h, k, v in zip(headers, keys, values):
            if h is not None and str(h).strip():
                row["_raw"][str(h).strip()] = v
            if k and k not in row:
                row[k] = v
        out.append(row)
    return out


def read_import_workbook(data: bytes) -> tuple[list[dict], list[dict]]:
    """(exhibitor rows, contact rows). Sheets are found by name (case-insensitive); when there is
    no "Exhibitors" sheet the first sheet is used. Raises ValueError for a file openpyxl can't read."""
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # zipfile.BadZipFile, KeyError, InvalidFileException ...
        raise ValueError(f"not a readable .xlsx file: {e}") from e
    by_name = {ws.title.strip().lower(): ws for ws in wb.worksheets}
    ex_ws = by_name.get("exhibitors") or wb.worksheets[0]
    exhibitors = read_sheet(ex_ws, EXHIBITOR_COLUMNS, HEADER_ALIASES)
    ct_ws = by_name.get("contacts")
    contacts = read_sheet(ct_ws, CONTACT_COLUMNS) if ct_ws is not None and ct_ws is not ex_ws else []
    wb.close()
    return exhibitors, contacts


def _write_sheet(ws, headers: list[str], rows: list[list], widths: dict[int, int] | None = None) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for r in rows:
        ws.append(r)
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, max(12, len(h) + 4))


def _to_bytes(wb: Workbook) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_import_workbook(exhibitors: list[dict] | None = None, contacts: list[dict] | None = None) -> bytes:
    """A workbook in the import format. Rows are dicts keyed by the column keys above (or by the
    header labels). With no rows this is the empty template."""

    def as_row(d: dict, columns: dict[str, str]) -> list:
        return [d.get(k, d.get(label)) for k, label in columns.items()]

    wb = Workbook()
    ws = wb.active
    ws.title = "Exhibitors"
    _write_sheet(ws, list(EXHIBITOR_COLUMNS.values()), [as_row(r, EXHIBITOR_COLUMNS) for r in exhibitors or []])
    ws2 = wb.create_sheet("Contacts")
    _write_sheet(ws2, list(CONTACT_COLUMNS.values()), [as_row(r, CONTACT_COLUMNS) for r in contacts or []])
    return _to_bytes(wb)


FLOOR_HEADERS = ["Hall", "Booth", "Company", "Country", "Role", "Priority", "Tags", "Assignee",
                 "Visited", "Note", "Website"]


def write_floor_list(title: str, items: list[dict]) -> bytes:
    """The dispatch floor list. `items` are appearance items as the API returns them, already sorted."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Floor list"
    rows = []
    for a in items:
        d = a.get("dispatch") or {}
        rows.append([
            a.get("hall"),
            a.get("booth"),
            a["company"]["name"],
            a["company"].get("country"),
            a.get("role"),
            (a.get("priority") or "").replace("_", " ") or None,
            ", ".join(t["name"] for t in a.get("tags", []) if t.get("confirmed") or not t.get("suggested")),
            d.get("assignee"),
            "yes" if d.get("visited") else "",
            d.get("note"),
            a["company"].get("website"),
        ])
    _write_sheet(ws, FLOOR_HEADERS, rows, widths={3: 40, 7: 30, 10: 40, 11: 30})
    ws.oddHeader.center.text = title
    ws.print_title_rows = "1:1"
    return _to_bytes(wb)
