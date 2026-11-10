"""Tests run against a real Postgres (the schema uses arrays, jsonb, partial indexes).

Set LEADS_TEST_ADMIN_URL to a Postgres server you can create databases on, e.g.
    postgresql+psycopg://dbot_leads:tmp@127.0.0.1:5434/leads
Each test session creates its own database (LEADS_TEST_DB, default leads_test) and
runs the Alembic migrations into it, so parallel runs with different names don't clash.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get("LEADS_TEST_ADMIN_URL", "postgresql+psycopg://dbot_leads:tmp@127.0.0.1:5434/leads")
TEST_DB = os.environ.get("LEADS_TEST_DB", "leads_test")


def _test_url() -> str:
    return make_url(ADMIN_URL).set(database=TEST_DB).render_as_string(hide_password=False)


os.environ["LEADS_DB_URL"] = _test_url()
os.environ.setdefault("LEADS_DEV_USER", "tester@dayo-tech.com")
os.environ.setdefault("LEADS_FILES_DIR", "/tmp/leads-test-files")


@pytest.fixture(scope="session", autouse=True)
def _database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    command.upgrade(cfg, "head")
    yield
    admin.dispose()


@pytest.fixture
def db():
    from app.db import engine, get_session

    engine()
    gen = get_session()
    s = next(gen)
    yield s
    s.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture
def clean(db):
    """Empty every table in the leads schema."""
    from app.db import Base

    names = ", ".join(f"leads.{t.name}" for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    db.commit()
    yield
