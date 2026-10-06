"""
Only the gateway may call this API: it checks the user's token and passes
the user on in X-User-Id, which this API trusts. Every request must carry
the secret shared with the gateway (X-Internal-Secret), so nothing else that
can reach this API (another container, a published port) can claim to be a
user.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.settings import settings

logger = logging.getLogger(__name__)

INTERNAL_SECRET_HEADER = "X-Internal-Secret"

# The API's own description (no data), readable without the secret.
OPEN_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def is_internal_request(request: Request) -> bool:
    expected = settings.INTERNAL_API_SECRET
    sent = request.headers.get(INTERNAL_SECRET_HEADER)
    if not expected or not sent:
        return False
    return hmac.compare_digest(sent.encode(), expected.encode())


async def require_internal_secret(request: Request, call_next):
    if request.url.path in OPEN_PATHS or is_internal_request(request):
        return await call_next(request)
    if not settings.INTERNAL_API_SECRET:
        logger.error("INTERNAL_API_SECRET is not set: refusing every request")
    return JSONResponse(status_code=401, content={"detail": "Requests must come through the gateway"})
