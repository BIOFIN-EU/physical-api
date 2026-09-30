"""
Marketplace actions on a unit allocation (diagram steps 11 and 13):
the habitat bank accepts or declines a request, the development releases
units it no longer needs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import ALLOCATION_DECIDING_ROLES, BngUnitAllocation
from app.models.case_data import Case
from app.services.bng_roles import act_as
from app.services.case_user_access_service import get_case_user_access

# action -> (whose project decides, statuses it applies to, new status)
ACTIONS = {
    "accept": ("habitat_bank", ("requested",), "reserved"),
    "decline": ("habitat_bank", ("requested",), "declined"),
    "release": ("development", ("requested", "reserved"), "released"),
}


async def apply_allocation_action(
    db: AsyncSession,
    *,
    allocation_id: int,
    action: str,
    user_id: UUID,
    on_behalf: bool = False,
) -> BngUnitAllocation:
    side, from_statuses, to_status = ACTIONS[action]

    allocation = await db.get(BngUnitAllocation, allocation_id)
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found")

    case_id = allocation.habitat_bank_case_id if side == "habitat_bank" else allocation.development_case_id
    access = await get_case_user_access(db, case_id=case_id, user_id=user_id)
    if access is None or not access.can_update:
        # Don't reveal allocations of projects the user can't manage.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found")

    await act_as(
        db,
        access=access,
        roles=ALLOCATION_DECIDING_ROLES[side],
        on_behalf_requested=on_behalf,
        action=f"{action} this request",
    )

    # Same lock as the capacity trigger, then re-read the row under it.
    await db.execute(select(Case.id).where(Case.id == allocation.habitat_bank_case_id).with_for_update())
    await db.refresh(allocation)

    if allocation.status not in from_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This allocation is {allocation.status} and can't be {action}ed.",
        )

    now = datetime.now(timezone.utc)
    allocation.status = to_status
    allocation.updated_by = user_id
    if action == "release":
        allocation.released_at = now
    else:
        allocation.decided_at = now

    await db.commit()
    await db.refresh(allocation)
    return allocation
