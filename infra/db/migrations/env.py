"""Alembic environment. The database URL comes from application Settings (never alembic.ini).

Set ``OPSPILOT_MIGRATE_DATABASE`` to migrate a different database (used for the test DB).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from opspilot_shared.config import get_settings
from opspilot_shared.db import models  # noqa: F401  (registers tables)
from opspilot_shared.db.base import SCHEMAS, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
settings = get_settings()
DATABASE = os.environ.get("OPSPILOT_MIGRATE_DATABASE") or settings.db_name


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url(database=DATABASE),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(settings.database_url(database=DATABASE), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
