from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import CaseUserAccess, CaseAccessAuditLog

async def get_case_user_access(
        db: AsyncSession,
        case_id: int,
        user_id: UUID,
) -> CaseUserAccess | None:
    result = await db.execute(
        select(CaseUserAccess).where(
            CaseUserAccess.case_id == case_id,
            CaseUserAccess.user_id == user_id,
        )
    )

    return result.scalar_one_or_none()


async def create_case_user_access(
        db: AsyncSession,
        *,
        case_id: int,
        user_id: UUID,
        actor_user_id: UUID,
        case_role: str,
        can_view: bool,
        can_update: bool,
        can_delete: bool,
        can_assign_users: bool,

) -> CaseUserAccess:
    result = await db.execute(
        select(CaseUserAccess).where(
            CaseUserAccess.case_id == case_id,
            CaseUserAccess.user_id == user_id,
        )
    )

    existing = result.scalar_one_or_none()

    if existing:
        raise ValueError("User already has access to this case")

    access = CaseUserAccess(
        case_id=case_id,
        user_id=user_id,
        case_role=case_role,
        is_owner=False,
        can_view=can_view,
        can_update=can_update,
        can_delete=can_delete,
        can_assign_users=can_assign_users,
    )

    db.add(access)

    await create_case_access_audit_log(
        db=db,
        case_id=case_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        action="user_added",
    )

    await db.commit()
    await db.refresh(access)

    return access


async def update_case_user_access(
        db: AsyncSession,
        *,
        case_id: int,
        user_id: UUID,
        actor_user_id: UUID,
        case_role: str | None = None,
        can_view: bool | None = None,
        can_update: bool | None = None,
        can_delete: bool | None = None,
        can_assign_users: bool | None = None,
) -> CaseUserAccess:
    access = await get_case_user_access(
        db=db,
        case_id=case_id,
        user_id=user_id,
    )

    if access is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have access to this case",
        )

    if case_role is not None:
        access.case_role = case_role

    if can_view is not None:
        access.can_view = can_view

    if can_update is not None:
        access.can_update = can_update

    if can_delete is not None:
        access.can_delete = can_delete

    if can_assign_users is not None:
        access.can_assign_users = can_assign_users

    await create_case_access_audit_log(
        db=db,
        case_id=case_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        action="user_access_updated",
    )

    await db.commit()
    await db.refresh(access)

    return access

async def delete_case_user_access(
    db: AsyncSession,
    *,
    case_id: int,
    user_id: UUID,
    actor_user_id: UUID
) -> None:
    access = await get_case_user_access(
        db=db,
        case_id=case_id,
        user_id=user_id,
    )

    if access is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have access to this case",
        )

    if access.is_owner:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the case owner",
        )

    await create_case_access_audit_log(
        db=db,
        case_id=case_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        action="user_removed",
    )

    await db.delete(access)
    await db.commit()


async def create_case_access_audit_log(
    db: AsyncSession,
    *,
    case_id: int,
    actor_user_id: UUID,
    target_user_id: UUID,
    action: str,
    details: str | None = None,
) -> CaseAccessAuditLog:
    log = CaseAccessAuditLog(
        case_id=case_id,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        details=details,
    )

    db.add(log)
    await db.flush()

    return log