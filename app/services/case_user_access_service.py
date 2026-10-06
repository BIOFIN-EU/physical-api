import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import Case, CaseAccessAuditLog, CaseUserAccess, CaseWorkflowRole
from app.services.access_levels import Level, apply_level, level_of


def access_summary(access: CaseUserAccess) -> dict:
    """A member's access, as recorded in the audit log's details."""
    return {"level": level_of(access)}


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


async def _member_or_404(db: AsyncSession, case_id: int, user_id: UUID) -> CaseUserAccess:
    access = await get_case_user_access(db=db, case_id=case_id, user_id=user_id)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This user isn't a member of the project.")
    return access


async def create_case_user_access(
        db: AsyncSession,
        *,
        case_id: int,
        user_id: UUID,
        actor_user_id: UUID,
        level: Level,
) -> CaseUserAccess:
    """Add a member at this level (audited; not committed)."""
    existing = await db.scalar(
        select(CaseUserAccess).where(CaseUserAccess.case_id == case_id, CaseUserAccess.user_id == user_id)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user is already a member of the project.",
        )

    access = CaseUserAccess(case_id=case_id, user_id=user_id, is_owner=False)
    apply_level(access, level)
    db.add(access)

    await create_case_access_audit_log(
        db=db,
        case_id=case_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        action="user_added",
        details=json.dumps(access_summary(access)),
    )
    return access


async def update_case_user_access(
        db: AsyncSession,
        *,
        case_id: int,
        user_id: UUID,
        actor_user_id: UUID,
        level: Level,
) -> CaseUserAccess:
    """Change a member's level (audited when it changes; not committed)."""
    access = await _member_or_404(db, case_id, user_id)

    if access.is_owner:
        # The owner always keeps full access (they can't be locked out).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The project owner's access can't be changed.",
        )

    before = access_summary(access)
    apply_level(access, level)
    after = access_summary(access)
    if before != after:
        await create_case_access_audit_log(
            db=db,
            case_id=case_id,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action="user_access_updated",
            details=json.dumps({"before": before, "after": after}),
        )
    return access


async def delete_case_user_access(
    db: AsyncSession,
    *,
    case_id: int,
    user_id: UUID,
    actor_user_id: UUID
) -> None:
    """Remove a member and their roles (audited; committed)."""
    access = await _member_or_404(db, case_id, user_id)

    if access.is_owner:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The project owner can't be removed.",
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
    await db.execute(
        delete(CaseWorkflowRole).where(CaseWorkflowRole.case_id == case_id, CaseWorkflowRole.user_id == user_id)
    )
    await db.delete(access)
    await db.commit()


async def transfer_ownership(
    db: AsyncSession,
    *,
    case_id: int,
    owner: CaseUserAccess,
    new_owner_id: UUID,
) -> CaseUserAccess:
    """
    Hand the project over to another member, who becomes its owner (with
    full access); the previous owner stays on as a manager. Committed.
    """
    # This session's copy of the owner's row (the one passed in may be from elsewhere).
    owner = await get_case_user_access(db, case_id, owner.user_id) or owner
    if not owner.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the project owner can hand it over.")
    if new_owner_id == owner.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You already own this project.")

    new_owner = await _member_or_404(db, case_id, new_owner_id)
    before = access_summary(new_owner)
    owner.is_owner = False
    apply_level(owner, "manager")
    new_owner.is_owner = True
    apply_level(new_owner, "manager")
    await create_case_access_audit_log(
        db, case_id=case_id, actor_user_id=owner.user_id, target_user_id=new_owner_id,
        action="ownership_transferred",
        details=json.dumps({"before": before, "after": access_summary(new_owner)}),
    )
    await db.commit()
    return new_owner


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
