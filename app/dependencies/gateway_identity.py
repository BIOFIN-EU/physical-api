from typing import List
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status


class RequestIdentity:
    def __init__(self, user_id: UUID, roles: List[str], permissions: List[str]):
        self.user_id = user_id
        self.roles = roles
        self.permissions = permissions


def _parse_csv_header(value: str | None) -> List[str]:
    if not value:
        return []

    return [item.strip() for item in value.split(",") if item.strip()]


async def get_request_identity(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_roles: str | None = Header(default=None, alias="X-User-Roles"),
    x_user_permissions: str | None = Header(default=None, alias="X-User-Permissions"),
) -> RequestIdentity:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing gateway identity header: X-User-Id",
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-Id format",
        )

    return RequestIdentity(
        user_id=user_id,
        roles=_parse_csv_header(x_user_roles),
        permissions=_parse_csv_header(x_user_permissions),
    )


async def get_request_user_id(
    identity: RequestIdentity = Depends(get_request_identity),
) -> UUID:
    return identity.user_id