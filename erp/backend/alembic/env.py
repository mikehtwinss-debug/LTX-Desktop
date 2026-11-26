"""Alembic environment: complete application metadata, database URL from ERP_DATABASE_URL.

Autogenerate does not see the immutability triggers; a migration installs them with
`op.execute(statement)` for each statement of `app.core.triggers.trigger_statements()`.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (imports every model module)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    # Keep existing loggers alive: migrations may also be run from inside a running process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
