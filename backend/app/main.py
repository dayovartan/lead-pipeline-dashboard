from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import User, current_user
from .config import get_settings
from .routers import companies, exhibitions, imports, leads, meetings, search

app = FastAPI(title="Leads", version="0.1.0")

for r in (companies.router, leads.router, meetings.router, imports.router, exhibitions.router, search.router):
    app.include_router(r, prefix="/api")


@app.get("/api/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"email": user.email, "name": user.name, "roles": sorted(user.roles), "is_editor": user.is_editor}


# The built SPA. Any non-API path falls back to index.html (client-side routes).
_static = Path(get_settings().static_dir)
if (_static / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    f = _static / path
    if path and f.is_file() and _static in f.resolve().parents:
        return FileResponse(f)
    index = _static / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"detail": "frontend not built"}
