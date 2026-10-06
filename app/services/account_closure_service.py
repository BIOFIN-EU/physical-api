"""
A user closing their account (asked by the gateway before auth-api closes
it): their projects mustn't be left without anyone who can manage them.

- A project they own passes to another member: the longest-standing manager,
  else the longest-standing member, who gets full access.
- A project they own alone is deleted (soft: its data stays), since no one
  could open it any more.
- Their access and roles on every project are removed.

Everything is recorded in each project's access audit log.
"""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import Case, CaseUserAccess, CaseWorkflowRole
from app.services.access_levels import apply_level
from app.services.case_delete_service import soft_delete_case
from app.services.case_user_access_service import access_summary, create_case_access_audit_log

REASON = "account closed"


async def release_closed_account(db: AsyncSession, *, user_id: UUID) -> dict:
    """
    Returns {"transferred": {case_id: new owner id}, "deleted": [case ids],
    "removed_from": [case ids], "workflows_to_stop": {case_id: workflow id}}.
    """
    memberships = (
        await db.execute(
            select(CaseUserAccess, Case.deleted_at)
            .join(Case, Case.id == CaseUserAccess.case_id)
            .where(CaseUserAccess.user_id == user_id)
        )
    ).all()

    transferred: dict[int, str] = {}
    sole_owned: list[int] = []
    for access, deleted_at in memberships:
        if not access.is_owner or deleted_at is not None:
            continue
        successor = await db.scalar(
            select(CaseUserAccess)
            .where(CaseUserAccess.case_id == access.case_id, CaseUserAccess.user_id != user_id)
            .order_by(CaseUserAccess.can_assign_users.desc(), CaseUserAccess.created_at, CaseUserAccess.id)
            .limit(1)
        )
        if successor is None:
            sole_owned.append(access.case_id)
            continue
        before = access_summary(successor)
        successor.is_owner = True
        apply_level(successor, "manager")
        await create_case_access_audit_log(
            db, case_id=access.case_id, actor_user_id=user_id, target_user_id=successor.user_id,
            action="ownership_transferred",
            details=json.dumps({"reason": REASON, "before": before, "after": access_summary(successor)}),
        )
        transferred[access.case_id] = str(successor.user_id)

    for access, _ in memberships:
        await create_case_access_audit_log(
            db, case_id=access.case_id, actor_user_id=user_id, target_user_id=user_id,
            action="user_removed", details=json.dumps({"reason": REASON, **access_summary(access)}),
        )
    await db.commit()

    # Deleting needs the owner's access, so before it is removed (each
    # delete commits).
    workflows_to_stop: dict[int, str] = {}
    for case_id in sole_owned:
        workflow_id = await soft_delete_case(db, case_id=case_id, user_id=user_id)
        if workflow_id:
            workflows_to_stop[case_id] = workflow_id

    case_ids = [access.case_id for access, _ in memberships]
    await db.execute(delete(CaseWorkflowRole).where(CaseWorkflowRole.user_id == user_id))
    await db.execute(delete(CaseUserAccess).where(CaseUserAccess.user_id == user_id))
    await db.commit()

    return {
        "transferred": transferred,
        "deleted": sole_owned,
        "removed_from": case_ids,
        "workflows_to_stop": workflows_to_stop,
    }
