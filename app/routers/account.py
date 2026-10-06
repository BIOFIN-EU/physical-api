"""The signed-in user's account, as far as this API is concerned."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.gateway_identity import get_request_user_id
from app.services.account_closure_service import release_closed_account
from app.services.case_delete_service import stop_deleted_case_workflow

router = APIRouter()


@router.post("/close")
async def close_account(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict:
    """
    Hand over or delete the user's projects and remove their access, before
    their account is closed. Called by the gateway as part of closing the
    account; safe to repeat.
    """
    result = await release_closed_account(db, user_id=user_id)
    for case_id, workflow_id in result.pop("workflows_to_stop").items():
        await stop_deleted_case_workflow(workflow_id, case_id=case_id)
    return result
