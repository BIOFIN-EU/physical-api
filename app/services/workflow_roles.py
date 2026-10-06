"""
Workflow roles: who is responsible for which steps of a project.

The roles are defined once in workflows.json ("roles": code -> label and
description); each workflow lists the ones it uses ("roles") and the role
its creator gets ("creator_role"), and each step the roles that may
complete it ("roles"). Members hold roles per project (case_workflow_roles).

A step with roles can be submitted by a member holding one of them. A
project manager (can_assign_users) may also submit it on behalf of that
role when the step has "allow_on_behalf", after confirming it
(ON_BEHALF_KEY in the payload). Steps without roles: any editor.

Every submission of a step with roles is recorded in case_step_signoffs.
"""
from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import (
    ALLOCATION_DECIDING_ROLES,
    BNG_HABITAT_BANK_WORKFLOW,
    MONITORING_BANK_ROLES,
    VERIFIER_ROLES,
)
from app.models.case_data import Case, CaseStepSignoff, CaseUserAccess, CaseWorkflowRole
from app.models.workflow import CaseWorkflowRun
from app.services.case_user_access_service import create_case_access_audit_log
from app.services.workflow_config_service import WorkflowConfigService, WorkflowNotFoundError

# Payload keys set by the frontend. Removed before the payload reaches the
# workflow, except APPROVAL_DECISION_KEY on a rejection, which the workflow
# engine reads (ConfigDrivenCaseWorkflow._is_rejection).
ON_BEHALF_KEY = "_on_behalf"
APPROVAL_DECISION_KEY = "_decision"
REJECTION_COMMENT_KEY = "_rejection_comment"
_CLIENT_KEYS = (ON_BEHALF_KEY, APPROVAL_DECISION_KEY, REJECTION_COMMENT_KEY)


# ---------------------------------------------------------
# The roles in the config
# ---------------------------------------------------------

class RoleConfigError(ValueError):
    pass


def role_catalogue() -> dict[str, dict[str, Any]]:
    """{code: {"label", "description"}} for every role."""
    return WorkflowConfigService().load_all().get("roles") or {}


def role_label(code: str | None) -> str | None:
    if code is None:
        return None
    return (role_catalogue().get(code) or {}).get("label", code)


def workflow_role_codes(workflow_config: dict[str, Any]) -> list[str]:
    return list(workflow_config.get("roles") or [])


def workflow_roles(workflow_config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The workflow's roles for display: code, label, description and the
    steps each may complete.
    """
    catalogue = role_catalogue()
    steps = workflow_config.get("steps") or {}
    return [
        {
            "code": code,
            "label": (catalogue.get(code) or {}).get("label", code),
            "description": (catalogue.get(code) or {}).get("description"),
            "steps": [
                {"code": step_code, "title": step.get("title")}
                for step_code, step in steps.items()
                if code in (step.get("roles") or [])
            ],
        }
        for code in workflow_role_codes(workflow_config)
    ]


def validate_role_config(config: dict[str, Any]) -> None:
    """
    Every workflow's roles are in the catalogue, its creator role is one of
    them, and every step's roles are the workflow's. Raises RoleConfigError
    listing what's wrong (checked on startup).
    """
    catalogue = config.get("roles") or {}
    problems = [f"role '{code}' has no label" for code, role in catalogue.items() if not (role or {}).get("label")]
    for code, workflow in (config.get("workflows") or {}).items():
        roles = workflow.get("roles") or []
        problems += [f"{code}: role '{role}' is not in the role list" for role in roles if role not in catalogue]
        creator = workflow.get("creator_role")
        if creator is not None and creator not in roles:
            problems.append(f"{code}: creator_role '{creator}' is not one of its roles")
        for step_code, step in (workflow.get("steps") or {}).items():
            problems += [
                f"{code}.{step_code}: role '{role}' is not one of the workflow's roles"
                for role in step.get("roles") or []
                if role not in roles
            ]
    if problems:
        raise RoleConfigError("Workflow role config: " + "; ".join(problems))


def role_names(roles: Iterable[str]) -> str:
    labels = [role_label(role) for role in roles]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " or " + labels[-1]


async def user_roles(db: AsyncSession, case_id: int, user_id: UUID) -> set[str]:
    rows = await db.scalars(
        select(CaseWorkflowRole.role).where(CaseWorkflowRole.case_id == case_id, CaseWorkflowRole.user_id == user_id)
    )
    return set(rows)


async def case_roles(db: AsyncSession, case_id: int) -> dict[str, list[str]]:
    """{user_id: [roles]} for a project."""
    result: dict[str, list[str]] = {}
    for row in await db.scalars(
        select(CaseWorkflowRole).where(CaseWorkflowRole.case_id == case_id).order_by(CaseWorkflowRole.id)
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
    workflow_config: dict[str, Any],
) -> list[str]:
    """
    Replace a member's roles on a project (each change audited). Only the
    project's workflow's roles can be given. Not committed; the caller also
    makes sure a member with roles is at least an editor.
    """
    allowed = workflow_role_codes(workflow_config)
    unknown = [role for role in roles if role not in allowed]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Not a role on this project: {', '.join(unknown)}",
        )

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
        db.add(CaseWorkflowRole(
            case_id=case_id, user_id=user_id, role=role,
            created_by=actor_user_id, updated_by=actor_user_id,
        ))
    await db.execute(
        delete(CaseWorkflowRole).where(
            CaseWorkflowRole.case_id == case_id,
            CaseWorkflowRole.user_id == user_id,
            CaseWorkflowRole.role.not_in(wanted),
        )
    )
    return wanted


def add_creator_role(db: AsyncSession, *, case_id: int, workflow_config: dict[str, Any], user_id: UUID) -> None:
    """A new project's creator gets its workflow's creator role (committed by the caller)."""
    role = workflow_config.get("creator_role")
    if role:
        db.add(CaseWorkflowRole(case_id=case_id, user_id=user_id, role=role, created_by=user_id, updated_by=user_id))


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


def step_capacities(held: Iterable[str], access: CaseUserAccess, workflow_config: dict[str, Any]) -> dict[str, Any]:
    """How the user may act on each step with roles (the frontend's step gate)."""
    held = set(held)
    if not access.can_update:
        held = set()  # roles only count for members who can edit
    on_behalf = bool(access.can_assign_users)
    return {
        code: capacity_for(held, step["roles"], can_record_on_behalf=on_behalf,
                           allow_on_behalf=bool(step.get("allow_on_behalf")))
        for code, step in (workflow_config.get("steps") or {}).items()
        if step.get("roles")
    }


async def bng_capacities(db: AsyncSession, case: Case, access: CaseUserAccess) -> dict[str, Any]:
    """
    BNG actions outside the steps, for the frontend to show the right
    controls (each is still checked with act_as when it is done): deciding
    on unit allocation requests and (habitat banks only) submitting and
    verifying monitoring reports.
    """
    held = await user_roles(db, case.id, access.user_id)
    on_behalf = bool(access.can_assign_users)
    is_bank = case.case_type == BNG_HABITAT_BANK_WORKFLOW
    side = "habitat_bank" if is_bank else "development"
    return {
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
                "code": "on_behalf_confirmation_required",
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
            "code": "role_required",
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
        return None  # a step without roles: the payload is left untouched

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
    db.add(CaseStepSignoff(
        case_id=case_id,
        step_code=step_code,
        user_id=user_id,
        role=capacity.get("role"),
        on_behalf=bool(capacity.get("on_behalf")),
        decision=decision or capacity.get("decision") or "submitted",
        comment=capacity.get("comment"),
    ))
    await db.commit()


def serialize_signoff(row: CaseStepSignoff) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_code": row.step_code,
        "user_id": str(row.user_id),
        "role": row.role,
        "role_label": role_label(row.role),
        "on_behalf": row.on_behalf,
        "decision": row.decision,
        "comment": row.comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def case_signoffs(db: AsyncSession, case_id: int) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(CaseStepSignoff).where(CaseStepSignoff.case_id == case_id).order_by(CaseStepSignoff.id)
    )
    return [serialize_signoff(row) for row in rows]


# ---------------------------------------------------------
# Whose turn it is
# ---------------------------------------------------------

async def waiting_for_user(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """
    In-progress projects whose current step is for one of the user's roles
    on that project.
    """
    rows = (await db.execute(
        select(Case.id, Case.case_type, CaseWorkflowRun.current_step)
        .join(CaseWorkflowRun, CaseWorkflowRun.case_id == Case.id)
        .join(CaseUserAccess, (CaseUserAccess.case_id == Case.id) & (CaseUserAccess.user_id == user_id))
        .where(
            Case.deleted_at.is_(None),
            CaseWorkflowRun.status == "in_progress",
            CaseUserAccess.can_update.is_(True),
        )
    )).all()
    if not rows:
        return []

    roles_by_case: dict[int, set[str]] = {}
    for case_id, role in (await db.execute(
        select(CaseWorkflowRole.case_id, CaseWorkflowRole.role).where(
            CaseWorkflowRole.user_id == user_id,
            CaseWorkflowRole.case_id.in_([row.id for row in rows]),
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
            waiting.append({
                "case_id": case_id, "step_code": current_step, "step_title": step.get("title"),
                "roles": mine, "role_names": role_names(mine),
            })
    return waiting
