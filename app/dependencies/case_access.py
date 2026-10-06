from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.gateway_identity import RequestIdentity, get_request_identity
from app.models.case_data import Case, CaseUserAccess
from app.services.case_user_access_service import get_case_user_access

ADMIN_ROLE = "admin"


def is_admin(identity: RequestIdentity) -> bool:
    """A platform administrator (auth-api role, passed on by the gateway)."""
    return ADMIN_ROLE in identity.roles


def support_access(case_id: int, identity: RequestIdentity) -> CaseUserAccess:
    """
    An administrator who isn't a member may read a project for support:
    view only, never saved (not a member). Each visit is recorded in the
    project's access history.
    """
    return CaseUserAccess(
        case_id=case_id, user_id=identity.user_id, is_owner=False,
        can_view=True, can_update=False, can_delete=False, can_assign_users=False,
    )


def is_support_access(access: CaseUserAccess) -> bool:
    return access.id is None


def require_case_permission(permission: str):
    async def dependency(
        case_id: int,
        db: AsyncSession = Depends(get_db),
        identity: RequestIdentity = Depends(get_request_identity),
    ) -> CaseUserAccess:
        access = await get_case_user_access(
            db=db,
            case_id=case_id,
            user_id=identity.user_id,
        )

        if access is None:
            # A missing or deleted case is "not found" for everyone; an
            # existing one the user has no access row for stays 403.
            case = await db.get(Case, case_id)
            if case is None or case.deleted_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found",
                )

            if permission == "can_view" and is_admin(identity):
                # Imported here: project_members imports the access service.
                from app.services.project_members import record_admin_view

                await record_admin_view(db, case_id=case_id, admin_id=identity.user_id)
                return support_access(case_id, identity)

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this case",
            )

        if not getattr(access, permission, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )

        return access

    return dependency
