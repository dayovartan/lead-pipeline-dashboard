from alembic import context
from sqlalchemy import create_engine, text

from app import models  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import SCHEMA, Base

target_metadata = Base.metadata


def run() -> None:
    eng = create_engine(get_settings().database_url)
    with eng.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=SCHEMA,
            include_name=lambda name, type_, parent: type_ != "schema" or name == SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


run()
