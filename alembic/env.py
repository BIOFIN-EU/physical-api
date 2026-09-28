from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# Import the project's declarative Base and every module that defines models
# on it, so `Base.metadata` is fully populated for autogenerate support.
from app.core.db import Base  # noqa: E402
from app.core.settings import settings  # noqa: E402
import app.models.case_data  # noqa: E402,F401
import app.models.workflow  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Source the DB URL from the project's own settings rather than hardcoding it
# in alembic.ini. Alembic's own connection always uses the sync psycopg
# driver, independent of the app runtime's asyncpg engine.
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=settings.CASE_DATA_DB_SCHEMA,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    A plain sync engine (psycopg) is used here for Alembic's own connection.
    The app's own runtime keeps using the async asyncpg engine regardless.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Alembic's version table lives in the case_data schema and is created
        # before any migration runs, so on an empty database the schema must
        # exist first (the baseline migration's CREATE SCHEMA runs too late).
        connection.execute(
            text(f'CREATE SCHEMA IF NOT EXISTS "{settings.CASE_DATA_DB_SCHEMA}"')
        )
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=settings.CASE_DATA_DB_SCHEMA,
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
