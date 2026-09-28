from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.gateway_identity import get_request_user_id
from app.models.case_data import Case, CaseUserAccess
from app.services.case_user_access_service import get_case_user_access


def require_case_permission(permission: str):
    async def dependency(
        case_id: int,
        db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(get_request_user_id),
    ) -> CaseUserAccess:
        access = await get_case_user_access(
            db=db,
            case_id=case_id,
            user_id=user_id,
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