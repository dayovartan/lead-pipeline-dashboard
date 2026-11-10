"""Settings. Everything comes from env vars or Docker secret files; nothing secret in git."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return p.read_text().strip() if p.exists() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEADS_", extra="ignore")

    # Database: the app's own leads-db. There is deliberately no setting for dbot-db.
    db_host: str = "leads-db"
    db_port: int = 5432
    db_name: str = "leads"
    db_user: str = "dbot_leads"
    db_password: str | None = None
    db_password_file: str | None = "/run/secrets/leads_db_password"
    db_url: str | None = None  # full override, used by tests

    # Uploaded files (Excel, venue maps) live on the leads-files volume.
    files_dir: str = "/data/files"

    # Built SPA, served as static files.
    static_dir: str = "/app/static"

    # Auth. In production oauth2-proxy (leads-auth) sets X-Forwarded-Email / -Groups.
    # dev_user lets a local run work without leads-auth; never set it in production.
    dev_user: str | None = None
    dev_roles: str = "leads_editor"
    editor_role: str = "leads_editor"
    viewer_role: str = "leads_viewer"

    # MCPs (read tools only). Empty token = MCP panels show "not available".
    cases_mcp_url: str = "https://mcp-dev.dayo-tech.com:7806/mcp"
    sap_mcp_url: str = "https://mcp-dev.dayo-tech.com:7801/mcp"
    mcp_token: str | None = None
    mcp_token_file: str | None = "/run/secrets/mcp_token"
    mcp_ca_file: str | None = None  # Caddy root CA
    mcp_timeout_s: float = 8.0
    mcp_cache_ttl_s: int = 300

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        pw = self.db_password or _read_secret(self.db_password_file) or ""
        return f"postgresql+psycopg://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def mcp_bearer(self) -> str | None:
        return self.mcp_token or _read_secret(self.mcp_token_file)


@lru_cache
def get_settings() -> Settings:
    return Settings()
