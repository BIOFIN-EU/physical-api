"""
BNG roles (Phase 3): who may submit, approve or reject a BNG step.

A step with "roles" in the workflow config can be submitted by a user who
holds one of those roles on the project (bng_case_roles). A project manager
(can_assign_users) may also submit it on behalf of that role when the step
has "allow_on_behalf", after confirming it (ON_BEHALF_KEY in the payload).
Steps without "roles" (every non-BNG workflow) are not affected.

Every submission of a step with roles is recorded in bng_step_signoffs.
"""
from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import (
    ALLOCATION_DECIDING_ROLES,
    BNG_CREATOR_ROLE,
    BNG_HABITAT_BANK_WORKFLOW,
    MONITORING_BANK_ROLES,
    VERIFIER_ROLES,
    BNG_ROLE_LABELS,
    BNG_ROLES,
    BNG_WORKFLOWS,
    BngCaseRole,
    BngStepSignoff,
)
from app.models.case_data import Case, CaseUserAccess
from app.models.workflow import CaseWorkflowRun
from app.services.case_user_access_service import create_case_access_audit_log, update_case_user_access
from app.services.workflow_config_service import WorkflowConfigService, WorkflowNotFoundError

# Payload keys set by the frontend. Removed before the payload reaches the
# workflow, except APPROVAL_DECISION_KEY on a rejection, which the workflow
# engine reads (ConfigDrivenCaseWorkflow._is_rejection).
ON_BEHALF_KEY = "_bng_on_behalf"
APPROVAL_DECISION_KEY = "_decision"
REJECTION_COMMENT_KEY = "_rejection_comment"
_CLIENT_KEYS = (ON_BEHALF_KEY, APPROVAL_DECISION_KEY, REJECTION_COMMENT_KEY)


def role_names(roles: Iterable[str]) -> str:
    labels = [BNG_ROLE_LABELS.get(role, role) for role in roles]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " or " + labels[-1]


async def user_roles(db: AsyncSession, case_id: int, user_id: UUID) -> set[str]:
    rows = await db.scalars(
        select(BngCaseRole.role).where(BngCaseRole.case_id == case_id, BngCaseRole.user_id == user_id)
    )
    return set(rows)


async def case_roles(db: AsyncSession, case_id: int) -> dict[str, list[str]]:
    """{user_id: [roles]} for a project."""
    result: dict[str, list[str]] = {}
    for row in await db.scalars(
        select(BngCaseRole).where(BngCaseRole.case_id == case_id).order_by(BngCaseRole.id)
    ):
        result.setdefault(str(row.user_id), []).append(row.role)
    return result


async def set_user_roles(
    db: AsyncSession,
    *,
    case_id: int,
    user_id: UUID,
    roles: list[str],
    actor_user_id: UUID,
) -> list[str]:
    """
    Replace a project member's BNG roles. A member given a role also gets
    update access (through the audited access service), since a role means
    submitting that role's steps; removing roles leaves their access as is.
    """
    unknown = [role for role in roles if role not in BNG_ROLES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown BNG role: {', '.join(unknown)}")

    member = await db.scalar(
        select(CaseUserAccess).where(CaseUserAccess.case_id == case_id, CaseUserAccess.user_id == user_id)
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Add this user to the project before giving them BNG roles.")

    wanted = list(dict.fromkeys(roles))
    held = await user_roles(db, case_id, user_id)
    for role in sorted(held - set(wanted)):
        await create_case_access_audit_log(
            db, case_id=case_id, actor_user_id=actor_user_id, target_user_id=user_id,
            action="role_removed", details=role,
        )
    for role in [r for r in wanted if r not in held]:
        await create_case_access_audit_log(
            db, case_id=case_id, actor_user_id=actor_user_id, target_user_id=user_id,
            action="role_assigned", details=role,
        )
    await db.execute(
        delete(BngCaseRole).where(
            BngCaseRole.case_id == case_id,
            BngCaseRole.user_id == user_id,
            BngCaseRole.role.not_in(wanted),
        )
    )
    have = await user_roles(db, case_id, user_id)
    for role in wanted:
        if role not in have:
            db.add(BngCaseRole(
                case_id=case_id, user_id=user_id, role=role,
                created_by=actor_user_id, updated_by=actor_user_id,
            ))
    needs_update_access = bool(wanted) and not member.can_update
    await db.commit()
    if needs_update_access:
        await update_case_user_access(
            db, case_id=case_id, user_id=user_id, actor_user_id=actor_user_id, can_update=True
        )
    return wanted


def add_creator_role(db: AsyncSession, *, case_id: int, workflow_code: str, user_id: UUID) -> None:
    """A new BNG project's creator gets its role (committed by the caller)."""
    role = BNG_CREATOR_ROLE.get(workflow_code)
    if role:
        db.add(BngCaseRole(case_id=case_id, user_id=user_id, role=role, created_by=user_id, updated_by=user_id))


# ---------------------------------------------------------
# Acting in a role
# ---------------------------------------------------------

def capacity_for(
    held: Iterable[str],
    roles: Iterable[str],
    *,
    can_record_on_behalf: bool,
    allow_on_behalf: bool = True,
) -> dict[str, Any]:
    """
    How a user holding `held` may act for something owned by `roles`:
    {"kind": "own" | "on_behalf" | "none", "role": ..., "roles": [...]}.
    "on_behalf" is for a project manager, who must confirm it each time.
    """
    held, roles = set(held), list(roles)
    own = [role for role in roles if role in held]
    if own:
        return {"kind": "own", "role": own[0], "roles": roles}
    first = roles[0] if roles else None
    if allow_on_behalf and can_record_on_behalf:
        return {"kind": "on_behalf", "role": first, "roles": roles}
    return {"kind": "none", "role": first, "roles": roles}


async def my_capacities(db: AsyncSession, case: Case, access: CaseUserAccess) -> dict[str, Any]:
    """
    What the user may do on a BNG project, for the frontend to show the right
    controls (each action is still checked with act_as when it is done):
    each step with roles, deciding on unit allocation requests, and (habitat
    banks only) submitting and verifying monitoring reports.
    """
    # Imported here: case_state imports this module (via bng_payload).
    from app.services.case_state import get_case_workflow_config

    held = await user_roles(db, case.id, access.user_id)
    on_behalf = bool(access.can_assign_users)
    workflow_config = await get_case_workflow_config(db, case.id) or {}
    steps = {
        code: capacity_for(held, step["roles"], can_record_on_behalf=on_behalf,
                           allow_on_behalf=bool(step.get("allow_on_behalf")))
        for code, step in (workflow_config.get("steps") or {}).items()
        if step.get("roles")
    }
    is_bank = case.case_type == BNG_HABITAT_BANK_WORKFLOW
    side = "habitat_bank" if is_bank else "development"
    return {
        "steps": steps,
        "allocations": capacity_for(held, ALLOCATION_DECIDING_ROLES[side], can_record_on_behalf=on_behalf),
        "monitoring_submit": capacity_for(held, MONITORING_BANK_ROLES, can_record_on_behalf=on_behalf) if is_bank else None,
        "monitoring_verify": capacity_for(held, VERIFIER_ROLES, can_record_on_behalf=on_behalf) if is_bank else None,
    }


async def act_as(
    db: AsyncSession,
    *,
    access: CaseUserAccess,
    roles: Iterable[str],
    on_behalf_requested: bool,
    allow_on_behalf: bool = True,
    action: str = "complete this step",
) -> dict[str, Any]:
    """
    The role `access`'s user acts in: {"role": ..., "on_behalf": bool}.
    403 when they hold none of `roles` and can't (or didn't confirm to) act
    on behalf of one.
    """
    roles = list(roles)
    mine = await user_roles(db, access.case_id, access.user_id)
    capacity = capacity_for(mine, roles, can_record_on_behalf=bool(access.can_assign_users),
                            allow_on_behalf=allow_on_behalf)
    if capacity["kind"] == "own":
        return {"role": capacity["role"], "on_behalf": False}

    if capacity["kind"] == "on_behalf":
        if on_behalf_requested:
            return {"role": roles[0], "on_behalf": True}
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "bng_on_behalf_confirmation_required",
                "message": (
                    f"This is for the {role_names(roles)} to {action}. Confirm that you are "
                    "recording it on their behalf."
                ),
                "roles": roles,
            },
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "bng_role_required",
            "message": f"Only the {role_names(roles)} can {action}.",
            "roles": roles,
        },
    )


def is_rejection(step_config: dict[str, Any], payload: dict[str, Any]) -> bool:
    return bool(step_config.get("approval")) and payload.get(APPROVAL_DECISION_KEY) == "rejected"


async def authorize_step(
    db: AsyncSession,
    *,
    access: CaseUserAccess,
    step_config: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Check the user may submit this step, and prepare the payload in place
    (the frontend-only keys are removed). Returns the capacity to record, or
    None for a step without roles (nothing is checked or recorded).
    """
    step_config = step_config or {}
    roles = step_config.get("roles")
    if not roles and not step_config.get("approval"):
        return None  # not a BNG role step: the payload is left untouched

    rejection = is_rejection(step_config, payload)
    on_behalf = payload.get(ON_BEHALF_KEY) is True
    comment = payload.get(REJECTION_COMMENT_KEY)
    for key in _CLIENT_KEYS:
        payload.pop(key, None)

    if not roles:
        return None

    capacity = await act_as(
        db,
        access=access,
        roles=roles,
        on_behalf_requested=on_behalf,
        allow_on_behalf=bool(step_config.get("allow_on_behalf")),
    )

    if rejection:
        if not isinstance(comment, str) or not comment.strip():
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Validation failed",
                    "field_errors": {REJECTION_COMMENT_KEY: "Say why this is being rejected."},
                },
            )
        payload[APPROVAL_DECISION_KEY] = "rejected"
        capacity["decision"] = "rejected"
        capacity["comment"] = comment.strip()[:2000]
    else:
        capacity["decision"] = "approved" if step_config.get("approval") else "submitted"
    return capacity


async def record_signoff(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
    user_id: UUID,
    capacity: dict[str, Any] | None,
    decision: str | None = None,
) -> None:
    if capacity is None:
        return
    db.add(BngStepSignoff(
        case_id=case_id,
        step_code=step_code,
        user_id=user_id,
        role=capacity.get("role"),
        on_behalf=bool(capacity.get("on_behalf")),
        decision=decision or capacity.get("decision") or "submitted",
        comment=capacity.get("comment"),
    ))
    await db.commit()


def serialize_signoff(row: BngStepSignoff) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_code": row.step_code,
        "user_id": str(row.user_id),
        "role": row.role,
        "role_label": BNG_ROLE_LABELS.get(row.role or "", row.role),
        "on_behalf": row.on_behalf,
        "decision": row.decision,
        "comment": row.comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def case_signoffs(db: AsyncSession, case_id: int) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(BngStepSignoff).where(BngStepSignoff.case_id == case_id).order_by(BngStepSignoff.id)
    )
    return [serialize_signoff(row) for row in rows]


# ---------------------------------------------------------
# Whose turn it is
# ---------------------------------------------------------

async def waiting_for_user(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """
    In-progress BNG projects whose current step is for one of the user's
    roles on that project.
    """
    rows = (await db.execute(
        select(Case.id, Case.case_type, CaseWorkflowRun.current_step)
        .join(CaseWorkflowRun, CaseWorkflowRun.case_id == Case.id)
        .join(CaseUserAccess, (CaseUserAccess.case_id == Case.id) & (CaseUserAccess.user_id == user_id))
        .where(
            Case.case_type.in_(BNG_WORKFLOWS),
            Case.deleted_at.is_(None),
            CaseWorkflowRun.status == "in_progress",
            CaseUserAccess.can_update.is_(True),
        )
    )).all()
    if not rows:
        return []

    roles_by_case: dict[int, set[str]] = {}
    for case_id, role in (await db.execute(
        select(BngCaseRole.case_id, BngCaseRole.role).where(
            BngCaseRole.user_id == user_id,
            BngCaseRole.case_id.in_([row.id for row in rows]),
        )
    )).all():
        roles_by_case.setdefault(case_id, set()).add(role)

    service = WorkflowConfigService()
    waiting = []
    for case_id, case_type, current_step in rows:
        try:
            step = service.get_workflow(case_type)["steps"].get(current_step) or {}
        except WorkflowNotFoundError:
            continue
        mine = [role for role in step.get("roles") or [] if role in roles_by_case.get(case_id, set())]
        if mine:
            waiting.append({"case_id": case_id, "step_code": current_step, "step_title": step.get("title"), "roles": mine})
    return waiting
