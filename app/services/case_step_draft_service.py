from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import Case
from app.models.workflow import CaseStepDraft


async def _get_case_or_404(db: AsyncSession, case_id: int) -> Case:
    case = await db.get(Case, case_id)

    if case is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "case_not_found",
                "message": f"Case {case_id} not found.",
            },
        )

    return case


async def _get_draft_row(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
) -> CaseStepDraft | None:
    result = await db.execute(
        select(CaseStepDraft).where(
            CaseStepDraft.case_id == case_id,
            CaseStepDraft.step_code == step_code,
        )
    )
    return result.scalar_one_or_none()


async def upsert_case_step_draft(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
    data: dict[str, Any],
    actor_user_id: UUID | None = None,
) -> dict[str, Any]:
    """
    Create or overwrite the single draft row for this (case_id, step_code).

    No validation is applied to `data` against the step's real Pydantic
    schema - drafts are allowed to be incomplete.
    """
    await _get_case_or_404(db, case_id)

    draft = await _get_draft_row(db, case_id=case_id, step_code=step_code)

    if draft is None:
        draft = CaseStepDraft(
            case_id=case_id,
            step_code=step_code,
            data=data,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        db.add(draft)
    else:
        draft.data = data
        draft.updated_by = actor_user_id

    await db.commit()
    await db.refresh(draft)

    return {"data": draft.data, "updated_at": draft.updated_at}


async def get_case_step_draft(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
) -> dict[str, Any]:
    await _get_case_or_404(db, case_id)

    draft = await _get_draft_row(db, case_id=case_id, step_code=step_code)

    if draft is None:
        return {"data": None, "updated_at": None}

    return {"data": draft.data, "updated_at": draft.updated_at}


async def delete_case_step_draft(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
) -> None:
    """
    Delete any existing draft for this (case_id, step_code), if present.

    Called after committed data has been saved for a step (via the
    edit/PATCH endpoint), since committed data supersedes an in-progress
    draft. A no-op if no draft exists.

    This is the async counterpart of the `clear_step_draft` Temporal
    activity in app.workflows.activities, which does the same thing for
    normal (non-edit) step submissions that go through the workflow engine.
    """
    await db.execute(
        delete(CaseStepDraft).where(
            CaseStepDraft.case_id == case_id,
            CaseStepDraft.step_code == step_code,
        )
    )
    await db.commit()
