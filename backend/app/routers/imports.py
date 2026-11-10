"""Excel intake: dry run first, then apply (docs/API.md "Imports")."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import User, current_user, require_editor
from ..config import get_settings
from ..db import get_session
from ..models import Convention, ImportBatch
from ..services.importer import run_import
from ..services.xlsx import read_import_workbook, write_import_workbook

router = APIRouter(tags=["imports"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def batch_dict(b: ImportBatch, slug: str | None = None) -> dict:
    return {
        "id": b.id,
        "convention_id": b.convention_id,
        "convention_slug": slug,
        "source": b.source,
        "file": b.file,
        "dry_run": b.dry_run,
        "rows": b.rows,
        "created": b.created,
        "updated": b.updated,
        "skipped": b.skipped,
        "conflicts": b.conflicts,
        "report": b.report or {},
        "actor": b.actor,
        "at": b.at,
    }


def _slug_of(db: Session, convention_id: int | None) -> str | None:
    if convention_id is None:
        return None
    c = db.get(Convention, convention_id)
    return c.slug if c else None


def _store(batch_id: int, filename: str, data: bytes) -> str:
    """Save the upload on leads-files; returns the path relative to files_dir."""
    safe = re.sub(r"[^\w.\-]+", "_", Path(filename or "upload.xlsx").name)[:100] or "upload.xlsx"
    rel = f"imports/{batch_id}-{safe}"
    dest = Path(get_settings().files_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel


def _run(db: Session, batch: ImportBatch, data: bytes) -> dict:
    try:
        batch = run_import(db, batch, data)
    except Exception as e:  # keep the batch row and say what went wrong
        db.rollback()
        b = db.get(ImportBatch, batch.id)
        b.report = {**(b.report or {}), "failed": True, "errors": [{"row": None, "message": str(e)}]}
        db.commit()
        raise HTTPException(422, f"import failed: {e}") from e
    return batch_dict(batch, _slug_of(db, batch.convention_id))


@router.get("/imports/template.xlsx")
def template(user: User = Depends(current_user)) -> Response:
    return Response(write_import_workbook(), media_type=XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="exhibitors-template.xlsx"'})


@router.post("/imports")
async def upload(
    file: UploadFile = File(...),
    convention_slug: str = Form(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_session),
    user: User = Depends(require_editor),
) -> dict:
    convention = db.scalar(select(Convention).where(Convention.slug == convention_slug))
    if convention is None:
        raise HTTPException(404, f"no convention {convention_slug!r}")
    data = await file.read()
    try:
        read_import_workbook(data)  # reject unreadable files before any batch row exists
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    batch = ImportBatch(convention_id=convention.id, source="excel", dry_run=dry_run, actor=user.email,
                        report={"original_name": file.filename})
    db.add(batch)
    db.flush()
    batch.file = _store(batch.id, file.filename or "upload.xlsx", data)
    db.commit()
    return _run(db, batch, data)


@router.post("/imports/{batch_id}/apply")
def apply(batch_id: int, db: Session = Depends(get_session), user: User = Depends(require_editor)) -> dict:
    """Run a dry run's stored file for real. Creates a new batch (dry_run=false); the dry-run
    batch records it under report.applied_batch_id, so a second apply is refused."""
    dry = db.get(ImportBatch, batch_id)
    if dry is None:
        raise HTTPException(404, "no such import")
    if not dry.dry_run:
        raise HTTPException(409, "this import was already a real run")
    if (dry.report or {}).get("applied_batch_id"):
        raise HTTPException(409, f"already applied as import {dry.report['applied_batch_id']}")
    if not dry.file:
        raise HTTPException(409, "the dry run has no stored file")
    path = Path(get_settings().files_dir) / dry.file
    if not path.is_file():
        raise HTTPException(410, "the stored file is gone; upload it again")
    data = path.read_bytes()

    batch = ImportBatch(convention_id=dry.convention_id, source=dry.source, file=dry.file, dry_run=False,
                        actor=user.email, report={"original_name": (dry.report or {}).get("original_name"),
                                                  "from_batch_id": dry.id})
    db.add(batch)
    db.commit()
    result = _run(db, batch, data)
    dry = db.get(ImportBatch, batch_id)
    dry.report = {**(dry.report or {}), "applied_batch_id": result["id"]}
    db.commit()
    return result


@router.get("/imports")
def list_imports(
    convention_slug: str | None = Query(None),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    q = select(ImportBatch, Convention.slug).outerjoin(Convention, Convention.id == ImportBatch.convention_id)
    if convention_slug:
        q = q.where(Convention.slug == convention_slug)
    rows = db.execute(q.order_by(ImportBatch.id.desc())).all()
    out = []
    for b, slug in rows:
        d = batch_dict(b, slug)
        # The list keeps the counts; the conflict and error lists come with GET /imports/{id}.
        d["report"] = {k: v for k, v in d["report"].items() if k not in ("conflicts", "errors")}
        out.append(d)
    return out


@router.get("/imports/{batch_id}")
def get_import(batch_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    b = db.get(ImportBatch, batch_id)
    if b is None:
        raise HTTPException(404, "no such import")
    return batch_dict(b, _slug_of(db, b.convention_id))
