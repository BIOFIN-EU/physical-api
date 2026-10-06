import json
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import BngCaseRole
from app.models.case_data import Case, CaseUserAccess, CaseAccessAuditLog

PERMISSION_FLAGS = ("can_view", "can_update", "can_delete", "can_assign_users")


def access_summary(access: CaseUserAccess) -> dict:
    """A member's access, as recorded in the audit log's details."""
    return {"case_role": access.case_role, **{flag: getattr(access, flag) for flag in PERMISSION_FLAGS}}


async def get_case_user_access(
        db: AsyncSession,
        case_id: int,
        user_id: UUID,
) -> CaseUserAccess | None:
    # Soft-deleted cases grant no access, which hides them from every
    # endpoint guarded by require_case_permission.
    result = await db.execute(
        select(CaseUserAccess)
        .join(Case, Case.id == CaseUserAccess.case_id)
        .where(
            CaseUserAccess.case_id == case_id,
            CaseUserAccess.user_id == user_id,
            Case.deleted_at.is_(None),
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user is already a member of the project.",
        )

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
        details=json.dumps(access_summary(access)),
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

    if access.is_owner:
        # The owner always keeps full access (they can't be locked out).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The project owner's access can't be changed.",
        )

    before = access_summary(access)

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
        details=json.dumps({"before": before, "after": access_summary(access)}),
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
        details=json.dumps(access_summary(access)),
    )

    # Their roles go with them (they would come back if re-added).
    await db.execute(delete(BngCaseRole).where(BngCaseRole.case_id == case_id, BngCaseRole.user_id == user_id))
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