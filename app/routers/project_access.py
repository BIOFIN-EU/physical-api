"""
A project's members, their access levels and workflow roles (the Access
tab), what the current user may do on it, whose turn it is, and the
administrators' list of every project.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.case_access import is_admin, is_support_access, require_case_permission
from app.dependencies.gateway_identity import RequestIdentity, get_request_identity, get_request_user_id
from app.models.case_data import CaseUserAccess
from app.schemas.project_access import AddMemberRequest, ChangeMemberRequest, TransferOwnershipRequest
from app.services.access_levels import level_of
from app.services.case_state import fetch_all_cases, get_case_workflow_config
from app.services.case_user_access_service import delete_case_user_access, transfer_ownership
from app.services.project_members import access_history, add_member, change_member, project_members
from app.services.workflow_roles import step_capacities, user_roles, waiting_for_user, workflow_roles

router = APIRouter()


async def _workflow_config(db: AsyncSession, case_id: int) -> dict[str, Any]:
    return await get_case_workflow_config(db, case_id) or {}


@router.get("/cases/{case_id}/members")
async def get_members(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """The members (managers see full emails), the project's roles and the access levels."""
    return await project_members(
        db, case_id=case_id, viewer=access, workflow_config=await _workflow_config(db, case_id)
    )


@router.post("/cases/{case_id}/members", status_code=201)
async def post_member(
    case_id: int,
    body: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> dict[str, Any]:
    """Add someone with an account, at an access level and with roles."""
    config = await _workflow_config(db, case_id)
    await add_member(
        db, case_id=case_id, actor=access, email=body.email, level=body.level, roles=body.roles,
        workflow_config=config,
    )
    return await project_members(db, case_id=case_id, viewer=access, workflow_config=config)


@router.patch("/cases/{case_id}/members/{user_id}")
async def patch_member(
    case_id: int,
    user_id: UUID,
    body: ChangeMemberRequest,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> dict[str, Any]:
    config = await _workflow_config(db, case_id)
    await change_member(
        db, case_id=case_id, actor=access, user_id=user_id, level=body.level, roles=body.roles,
        workflow_config=config,
    )
    return await project_members(db, case_id=case_id, viewer=access, workflow_config=config)


@router.delete("/cases/{case_id}/members/{user_id}")
async def delete_member(
    case_id: int,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> dict[str, Any]:
    await delete_case_user_access(db, case_id=case_id, user_id=user_id, actor_user_id=access.user_id)
    return await project_members(
        db, case_id=case_id, viewer=access, workflow_config=await _workflow_config(db, case_id)
    )


@router.post("/cases/{case_id}/transfer-ownership")
async def post_transfer_ownership(
    case_id: int,
    body: TransferOwnershipRequest,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> dict[str, Any]:
    """The owner hands the project over to another member (and stays a manager)."""
    await transfer_ownership(db, case_id=case_id, owner=access, new_owner_id=body.user_id)
    return await project_members(
        db, case_id=case_id, viewer=access, workflow_config=await _workflow_config(db, case_id)
    )


@router.get("/cases/{case_id}/access-history")
async def get_access_history(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> list[dict[str, Any]]:
    """Who changed whose access or roles, and when (newest first)."""
    return await access_history(db, case_id=case_id)


@router.get("/cases/{case_id}/my-access")
async def get_my_access(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """
    The current user's level and roles on the project, and how they may act
    on each step with roles (own role, on a role's behalf, or not).
    """
    held = await user_roles(db, case_id, access.user_id)
    config = await _workflow_config(db, case_id)
    return {
        "level": level_of(access),
        "roles": sorted(held),
        "can_update": access.can_update,
        "can_manage": access.can_assign_users,
        # An administrator reading a project they aren't a member of.
        "support_view": is_support_access(access),
        "steps": step_capacities(held, access, config),
        # Labels of the project's roles: {code: label}.
        "role_labels": {role["code"]: role["label"] for role in workflow_roles(config)},
    }


@router.get("/waiting")
async def get_waiting_for_me(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> list[dict[str, Any]]:
    """Projects whose current step is for one of the user's roles."""
    return await waiting_for_user(db, user_id)


@router.get("/admin/cases")
async def get_all_cases(
    db: AsyncSession = Depends(get_db),
    identity: RequestIdentity = Depends(get_request_identity),
) -> list[dict[str, Any]]:
    """Every project (administrators only), to open one read-only for support."""
    if not is_admin(identity):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators only")
    return await fetch_all_cases(db, identity.user_id)
