"""
A project's members as the Access tab shows and changes them: each one's
access level and workflow roles, shown by name and email (from auth-api).

Managers see members' full email addresses; other members see the name and
the email's domain only (e.g. "j•••@lpa.gov.uk").
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import CaseAccessAuditLog, CaseUserAccess, CaseWorkflowRole
from app.services.access_levels import Level, at_least_editor, level_of, levels_for_display
from app.services.auth_user_service import lookup_users, resolve_user_id_by_email
from app.services.case_user_access_service import (
    create_case_access_audit_log,
    create_case_user_access,
    update_case_user_access,
)
from app.services.workflow_roles import case_roles, role_label, set_user_roles, workflow_roles


def mask_email(email: str | None) -> str | None:
    """j•••@lpa.gov.uk: the organisation's domain, not the person's address."""
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return f"{name[:1]}•••@{domain}"


def person(user_id: UUID | str, details: dict[str, dict], *, full_email: bool) -> dict[str, Any]:
    found = details.get(str(user_id)) or {}
    email = found.get("email")
    return {
        "user_id": str(user_id),
        "display_name": found.get("display_name"),
        "email": email if full_email else mask_email(email),
        # False for a closed account (or when auth-api couldn't be reached).
        "known": bool(found),
    }


async def project_members(
    db: AsyncSession,
    *,
    case_id: int,
    viewer: CaseUserAccess,
    workflow_config: dict[str, Any],
) -> dict[str, Any]:
    """Everything the Access tab shows."""
    members = (await db.scalars(
        select(CaseUserAccess).where(CaseUserAccess.case_id == case_id).order_by(CaseUserAccess.id)
    )).all()
    roles = await case_roles(db, case_id)
    can_manage = bool(viewer.can_assign_users)
    details = await lookup_users([m.user_id for m in members])
    listed = [
        {
            **person(member.user_id, details, full_email=can_manage),
            "level": level_of(member),
            "is_owner": member.is_owner,
            "roles": roles.get(str(member.user_id), []),
            "is_me": member.user_id == viewer.user_id,
        }
        for member in members
    ]
    # Owner first, then by level, then by name.
    order = {"owner": 0, "manager": 1, "editor": 2, "viewer": 3}
    listed.sort(key=lambda m: (order[m["level"]], (m["display_name"] or m["email"] or "").lower()))
    return {
        "members": listed,
        "roles": workflow_roles(workflow_config),
        "levels": levels_for_display(),
        "my_level": level_of(viewer),
        "can_manage": can_manage,
        "is_owner": bool(viewer.is_owner),
        # An administrator reading a project they aren't a member of.
        "support_view": viewer.id is None,
    }


async def add_member(
    db: AsyncSession,
    *,
    case_id: int,
    actor: CaseUserAccess,
    email: str,
    level: Level,
    roles: list[str],
    workflow_config: dict[str, Any],
) -> None:
    user_id = await resolve_user_id_by_email(email)
    if user_id == actor.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You are already a member of this project.")
    await create_case_user_access(
        db, case_id=case_id, user_id=user_id, actor_user_id=actor.user_id,
        level=at_least_editor(level) if roles else level,
    )
    await set_user_roles(
        db, case_id=case_id, user_id=user_id, roles=roles,
        actor_user_id=actor.user_id, workflow_config=workflow_config,
    )
    await db.commit()


async def change_member(
    db: AsyncSession,
    *,
    case_id: int,
    actor: CaseUserAccess,
    user_id: UUID,
    level: Level | None,
    roles: list[str] | None,
    workflow_config: dict[str, Any],
) -> None:
    """Change a member's level and/or roles (the owner keeps their level)."""
    member = await db.scalar(
        select(CaseUserAccess).where(CaseUserAccess.case_id == case_id, CaseUserAccess.user_id == user_id)
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This user isn't a member of the project.")

    if roles is not None:
        roles = await set_user_roles(
            db, case_id=case_id, user_id=user_id, roles=roles,
            actor_user_id=actor.user_id, workflow_config=workflow_config,
        )
    has_roles = bool(roles) if roles is not None else bool(
        await db.scalar(select(CaseWorkflowRole.id).where(
            CaseWorkflowRole.case_id == case_id, CaseWorkflowRole.user_id == user_id
        ).limit(1))
    )

    if not member.is_owner:
        wanted = level or level_of(member)
        if has_roles and wanted == "viewer":
            if level == "viewer":
                raise HTTPException(
                    status_code=422,
                    detail="A member with roles must be at least an Editor (to complete their steps). Remove their roles first.",
                )
            wanted = "editor"
        if wanted != level_of(member):
            await update_case_user_access(
                db, case_id=case_id, user_id=user_id, actor_user_id=actor.user_id, level=wanted
            )
    elif level is not None and level != "manager":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The project owner's access can't be changed.")
    await db.commit()


AUDIT_ACTION_LABELS = {
    "user_added": "Added",
    "user_removed": "Removed",
    "user_access_updated": "Access changed",
    "role_assigned": "Role given",
    "role_removed": "Role taken away",
    "ownership_transferred": "Became owner",
    "admin_viewed": "Viewed by an administrator",
}


def _audit_detail(action: str, details: str | None) -> str | None:
    """A short description of what changed."""
    if action in ("role_assigned", "role_removed"):
        return role_label(details)
    try:
        parsed = json.loads(details) if details else None
    except ValueError:
        return details
    if not isinstance(parsed, dict):
        return None
    if "before" in parsed and "after" in parsed:
        before, after = parsed["before"].get("level"), parsed["after"].get("level")
        if before and after and before != after:
            return f"{before.capitalize()} → {after.capitalize()}"
    if parsed.get("reason"):
        return parsed["reason"].capitalize()
    if parsed.get("level"):
        return parsed["level"].capitalize()
    return None


async def access_history(db: AsyncSession, *, case_id: int, limit: int = 200) -> list[dict[str, Any]]:
    """The project's access changes, newest first, with people's names."""
    logs = (await db.scalars(
        select(CaseAccessAuditLog)
        .where(CaseAccessAuditLog.case_id == case_id)
        .order_by(CaseAccessAuditLog.created_at.desc(), CaseAccessAuditLog.id.desc())
        .limit(limit)
    )).all()
    details = await lookup_users([log.actor_user_id for log in logs] + [log.target_user_id for log in logs])
    return [
        {
            "id": log.id,
            "action": log.action,
            "action_label": AUDIT_ACTION_LABELS.get(log.action, log.action),
            "detail": _audit_detail(log.action, log.details),
            "actor": person(log.actor_user_id, details, full_email=True),
            "target": person(log.target_user_id, details, full_email=True),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


async def record_admin_view(db: AsyncSession, *, case_id: int, admin_id: UUID) -> None:
    """
    An administrator opened the project (support access): recorded in its
    access history, at most once a day per administrator.
    """
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = await db.scalar(
        select(CaseAccessAuditLog.id).where(
            CaseAccessAuditLog.case_id == case_id,
            CaseAccessAuditLog.actor_user_id == admin_id,
            CaseAccessAuditLog.action == "admin_viewed",
            CaseAccessAuditLog.created_at >= since,
        ).limit(1)
    )
    if recent is None:
        await create_case_access_audit_log(
            db, case_id=case_id, actor_user_id=admin_id, target_user_id=admin_id, action="admin_viewed",
        )
        await db.commit()
