"""
Shared fixtures for the physical-api test suite.

These tests need a reachable Postgres instance. They read connection details
from the same POSTGRES_* environment variables the app itself uses (see
app/core/settings.py); if those aren't already exported (e.g. from
.env.dev / docker-compose), sensible localhost defaults are applied so the
suite can also be pointed at an ad-hoc/throwaway database for local runs.

Tests are skipped automatically if no database is reachable, so `pytest` does
not hard-fail in environments without Postgres available.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("WORKFLOW_DB_SCHEMA", "workflow")
os.environ.setdefault("CASE_DATA_DB_SCHEMA", "case_data")
os.environ.setdefault("MINIO_ROOT_USER", "test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")
os.environ.setdefault("MINIO_SECURE", "false")
os.environ.setdefault("AUTH_URL", "http://localhost")
os.environ.setdefault("AUTH_CLIENT_ID", "test")
os.environ.setdefault("AUTH_CLIENT_SECRET", "test")

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.core.settings import settings  # noqa: E402
from app.models.case_data import Case, Country  # noqa: E402
from app.workflows.activities import SessionLocal, engine  # noqa: E402

REQUIRED_COUNTRIES = [
    ("BE", "Belgium"),
    ("NL", "Netherlands"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("XX", "Multiple Countries"),
]


@pytest.fixture(scope="session", autouse=True)
def _db_schema():
    """
    Ensure the schemas/tables exist and required lookup rows are seeded,
    skipping the whole DB-backed suite if no database is reachable.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.WORKFLOW_DB_SCHEMA}"))
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.CASE_DATA_DB_SCHEMA}"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS support"))  # contact form (app.main imports it)
            Base.metadata.create_all(conn)
    except OperationalError as exc:
        pytest.skip(f"No reachable Postgres database for tests: {exc}")

    with SessionLocal() as session:
        for code, name in REQUIRED_COUNTRIES:
            existing = session.execute(
                select(Country).where(Country.code == code)
            ).scalar_one_or_none()
            if existing is None:
                session.add(Country(code=code, name=name))
        session.commit()

    yield


@pytest.fixture()
def case_id() -> int:
    """
    Create a throwaway Case row for a test and clean it up afterward.
    Deleting the case cascades to its case_locations rows.
    """
    with SessionLocal() as session:
        case = Case(
            case_type="private_lending_v1",
            status="draft",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4(),
        )
        session.add(case)
        session.commit()
        session.refresh(case)
        created_id = case.id

    yield created_id

    with SessionLocal() as session:
        db_case = session.get(Case, created_id)
        if db_case is not None:
            session.delete(db_case)
            session.commit()
