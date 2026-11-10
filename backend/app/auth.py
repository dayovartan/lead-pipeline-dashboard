"""Who is calling. leads-auth (oauth2-proxy) is the only container that can reach this app,
so its forwarded headers are trusted (LEADS_PLAN.md section 12). Entra app roles arrive as
groups (OAUTH2_PROXY_OIDC_GROUPS_CLAIM=roles)."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from .config import Settings, get_settings


@dataclass
class User:
    email: str
    name: str
    roles: set[str]

    @property
    def is_editor(self) -> bool:
        return get_settings().editor_role in self.roles


def current_user(request: Request, settings: Settings = Depends(get_settings)) -> User:
    h = request.headers
    email = h.get("x-forwarded-email") or h.get("x-auth-request-email")
    groups = h.get("x-forwarded-groups") or h.get("x-auth-request-groups") or ""
    name = h.get("x-forwarded-preferred-username") or h.get("x-forwarded-user") or ""
    if not email and settings.dev_user:
        email, groups, name = settings.dev_user, settings.dev_roles, settings.dev_user
    if not email:
        raise HTTPException(401, "not signed in")
    roles = {g.strip() for g in groups.split(",") if g.strip()}
    if not roles & {settings.editor_role, settings.viewer_role}:
        raise HTTPException(403, "no leads role")
    return User(email=email.lower(), name=name or email, roles=roles)


def require_editor(user: User = Depends(current_user)) -> User:
    if not user.is_editor:
        raise HTTPException(403, "editors only")
    return user
