from typing import Any

import httpx

from app.core.settings import settings
from app.schemas.risk import LocationRiskInput


class RiskFrameworkError(Exception):
    """
    Raised when a Risk Score Framework call fails.

    retryable is False for 4xx responses (bad input such as an unsupported
    country), where calling again would fail the same way.
    """

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _risk_url(path: str) -> str:
    return f"{settings.RISK_URL.rstrip('/')}/{path}"


def _raise_for_response(exc: httpx.HTTPError, action: str) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        raise RiskFrameworkError(
            f"Risk framework {action} failed with {status_code}: {exc.response.text[:500]}",
            retryable=status_code >= 500,
        ) from exc

    raise RiskFrameworkError(f"Risk framework {action} failed: {exc}") from exc


def get_id_from_risk_framework(payload: LocationRiskInput) -> str:
    """
    Request the priority management actions for a polygon and return the id
    of the related Biodiversity Risk Index record.

    The response's own `id` is the Management Actions record, which
    risk/get/ does not know about; the risk record is only referenced by its
    `risk` URL (e.g. "/api/v1/risk/get/<uuid>/"), so the id is taken from there.
    """
    try:
        response = httpx.post(
            _risk_url("management-actions/priority/"),
            json=payload.model_dump(),
            timeout=settings.RISK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        _raise_for_response(exc, "priority request")

    risk_url = response.json().get("risk")
    if not risk_url:
        raise RiskFrameworkError(
            "Risk framework priority response has no 'risk' reference.",
            retryable=False,
        )

    return risk_url.rstrip("/").rsplit("/", 1)[-1]


def get_risk_result(risk_id: str) -> dict[str, Any]:
    """
    Fetch a stored Biodiversity Risk Index record by id.
    """
    try:
        response = httpx.get(
            _risk_url(f"risk/get/{risk_id}/"),
            timeout=settings.RISK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        _raise_for_response(exc, "risk lookup")

    return response.json()
