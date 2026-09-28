from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import Case, CaseUserAccess
from app.models.workflow import CaseWorkflowRun


async def soft_delete_case(
        db: AsyncSession,
        *,
        case_id: int,
        user_id: UUID,
) -> str | None:
    """
    Mark a case deleted (deleted_at / deleted_by); no rows are removed.

    Requires the user's can_delete on the case. Deleting an already-deleted
    case is a no-op, so it checks access itself rather than through
    require_case_permission, which treats deleted cases as not found.

    Returns the Temporal workflow id when the case's workflow was still
    running, so the caller can stop it; otherwise None.
    """
    row = (
        await db.execute(
            select(Case, CaseUserAccess.can_delete)
            .outerjoin(
                CaseUserAccess,
                (CaseUserAccess.case_id == Case.id) & (CaseUserAccess.user_id == user_id),
            )
            .where(Case.id == case_id)
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    case, can_delete = row

    if can_delete is None:
        # No access row: don't reveal whether the case exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: can_delete",
        )

    if case.deleted_at is not None:
        return None

    case.deleted_at = datetime.now(timezone.utc)
    case.deleted_by = user_id

    run = await db.scalar(select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id))

    await db.commit()

    if run is not None and run.status not in {"completed", "failed"}:
        return run.temporal_workflow_id

    return None
