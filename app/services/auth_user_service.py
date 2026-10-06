from uuid import UUID
import logging
import httpx
from fastapi import HTTPException, status

from app.core.settings import settings

logger = logging.getLogger(__name__)


async def resolve_user_id_by_email(email: str) -> UUID:
    async with httpx.AsyncClient(timeout=10.0) as client:

        logger.info("Resolving user ID for an email address")
        response = await client.get(
            f"{settings.AUTH_URL}/api/auth/users/by-email",
            params={"email": email},
            headers={
                "X-Client-Id": settings.AUTH_CLIENT_ID,
                "X-Client-Secret": settings.AUTH_CLIENT_SECRET,
            },
        )
        logger.info("Received response from auth service: %s", response.status_code)


    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this email address. Please ask them to register before assigning access.",
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not resolve user email",
        )

    data = response.json()
    return UUID(data["id"])

async def lookup_users(user_ids: list[UUID]) -> dict[str, dict]:
    """
    {user id: {"email", "display_name"}} from auth-api, for showing people.
    Closed accounts are left out. If auth-api can't be reached the result
    is empty (people are then shown without their details), not an error.
    """
    ids = sorted({str(user_id) for user_id in user_ids})
    if not ids:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.AUTH_URL}/api/auth/users/lookup",
                json={"ids": ids},
                headers={
                    "X-Client-Id": settings.AUTH_CLIENT_ID,
                    "X-Client-Secret": settings.AUTH_CLIENT_SECRET,
                },
            )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Could not look up %s users in auth-api", len(ids))
        return {}
    return {user["id"]: user for user in response.json()}
