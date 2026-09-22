"""
Integration tests for case step drafts against a real Postgres database
(see tests/conftest.py for how the target database is selected/skipped).

Covers:
- draft upsert then fetch
- overwriting an existing draft (no duplicate rows)
- fetching a draft that does not exist (returns nulls, not an error)
- a draft being cleared once update_case_step_data() commits real data for
  that (case_id, step_code)
- the edit endpoint's rejection of multipart (file-upload) steps
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.db import SessionLocal as AsyncSessionLocal
from app.models.case_data import Case
from app.models.workflow import CaseStepDraft
from app.services.case_step_draft_service import (
    get_case_step_draft,
    upsert_case_step_draft,
)
from app.services.case_step_edit_service import update_case_step_data
from app.workflows.activities import SessionLocal


@pytest.fixture()
def multipart_case_id() -> int:
    """
    A throwaway case whose workflow (use_case_2_v1) has a step
    ("supporting_document") configured with submit_mode == "multipart",
    used to exercise the edit endpoint's multipart rejection.
    """
    with SessionLocal() as session:
        case = Case(
            case_type="use_case_2_v1",
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


def _draft_rows(case_id: int, step_code: str) -> list[CaseStepDraft]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(CaseStepDraft).where(
                    CaseStepDraft.case_id == case_id,
                    CaseStepDraft.step_code == step_code,
                )
            ).scalars()
        )


@pytest.mark.asyncio(loop_scope="module")
async def test_draft_upsert_then_fetch(case_id):
    async with AsyncSessionLocal() as db:
        result = await upsert_case_step_draft(
            db,
            case_id=case_id,
            step_code="basic_info",
            data={"name": "Draft name"},
        )
        assert result["data"] == {"name": "Draft name"}
        assert result["updated_at"] is not None

    async with AsyncSessionLocal() as db:
        fetched = await get_case_step_draft(
            db, case_id=case_id, step_code="basic_info"
        )
        assert fetched["data"] == {"name": "Draft name"}
        assert fetched["updated_at"] is not None


@pytest.mark.asyncio(loop_scope="module")
async def test_draft_overwrite_replaces_existing_row(case_id):
    async with AsyncSessionLocal() as db:
        await upsert_case_step_draft(
            db, case_id=case_id, step_code="basic_info", data={"name": "First"}
        )

    async with AsyncSessionLocal() as db:
        result = await upsert_case_step_draft(
            db, case_id=case_id, step_code="basic_info", data={"name": "Second"}
        )
        assert result["data"] == {"name": "Second"}

    async with AsyncSessionLocal() as db:
        fetched = await get_case_step_draft(
            db, case_id=case_id, step_code="basic_info"
        )
        assert fetched["data"] == {"name": "Second"}

    # Overwriting must not create a second row for the same (case, step).
    assert len(_draft_rows(case_id, "basic_info")) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_draft_fetch_missing_returns_nulls_not_error(case_id):
    async with AsyncSessionLocal() as db:
        fetched = await get_case_step_draft(
            db, case_id=case_id, step_code="financial"
        )

    assert fetched == {"data": None, "updated_at": None}


@pytest.mark.asyncio(loop_scope="module")
async def test_draft_cleared_after_successful_step_edit(case_id):
    async with AsyncSessionLocal() as db:
        await upsert_case_step_draft(
            db,
            case_id=case_id,
            step_code="basic_info",
            data={"name": "Unsaved in-progress edit"},
        )

    assert len(_draft_rows(case_id, "basic_info")) == 1

    async with AsyncSessionLocal() as db:
        await update_case_step_data(
            db,
            case_id=case_id,
            step_code="basic_info",
            payload={
                "name": "Committed name",
                "high_level_description": "Committed description",
            },
        )

    assert _draft_rows(case_id, "basic_info") == []

    async with AsyncSessionLocal() as db:
        fetched = await get_case_step_draft(
            db, case_id=case_id, step_code="basic_info"
        )
    assert fetched == {"data": None, "updated_at": None}


@pytest.mark.asyncio(loop_scope="module")
async def test_edit_multipart_step_is_rejected(multipart_case_id):
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await update_case_step_data(
                db,
                case_id=multipart_case_id,
                step_code="supporting_document",
                payload={"document_notes": "should not work via PATCH"},
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "unsupported_step_type"
