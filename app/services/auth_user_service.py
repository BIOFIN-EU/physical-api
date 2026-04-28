from uuid import UUID
import logging
import httpx
from fastapi import HTTPException, status

from app.core.settings import settings

logger = logging.getLogger(__name__)


async def resolve_user_id_by_email(email: str) -> UUID:
    async with httpx.AsyncClient(timeout=10.0) as client:

        logger.info(f"Resolving user ID for email: {email}")
        response = await client.get(
            f"{settings.AUTH_URL}/api/auth/users/by-email",
            params={"email": email},
            headers={
                "X-Client-Id": settings.AUTH_CLIENT_ID,
                "X-Client-Secret": settings.AUTH_CLIENT_SECRET,
            },
        )
        logger.info(f"Received response from auth service: {response.status_code} - {response.text}")


    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with this email does not exist",
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not resolve user email",
        )

    data = response.json()
    return UUID(data["id"])