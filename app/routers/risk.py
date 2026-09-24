import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.dependencies.case_access import require_case_permission
from app.models.case_data import CaseLocation, CaseUserAccess
from app.schemas.risk import LocationRiskInput
from app.services.risk_framework_service import RiskFrameworkError, get_id_from_risk_framework, get_risk_result

logger = logging.getLogger(__name__)

router = APIRouter()


async def _ensure_location_risk_id(db: AsyncSession, location: CaseLocation) -> str:
    """
    Return the location's risk_id, requesting and storing one first if the
    completion-time fetch hasn't set it (e.g. it failed, or the locations
    step was edited, which recreates the rows).
    """
    if location.risk_id:
        return location.risk_id

    risk_id = await asyncio.to_thread(
        get_id_from_risk_framework,
        LocationRiskInput(
            country_code=location.country.code,
            wkt_polygon=location.geometry_wkt,
        ),
    )

    # Plain UPDATE: the row may have been removed by a concurrent locations
    # edit while the framework call was running.
    await db.execute(
        update(CaseLocation)
        .where(CaseLocation.id == location.id, CaseLocation.risk_id.is_(None))
        .values(risk_id=risk_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    return risk_id


@router.get("/cases/{case_id}")
async def get_case_risk(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    """
    Return the Risk Score Framework risk result for every polygon location of
    a case. Locations are processed one by one; a failure on one location is
    reported in its entry and does not fail the others.
    """
    result = await db.execute(
        select(CaseLocation)
        .options(selectinload(CaseLocation.country))
        .where(
            CaseLocation.case_id == case_id,
            CaseLocation.location_type == "polygon",
        )
        .order_by(CaseLocation.id)
    )
    locations = result.scalars().all()

    risks: list[dict[str, Any]] = []

    for location in locations:
        entry: dict[str, Any] = {
            "case_id": case_id,
            "location_id": location.id,
            "friendly_name": location.friendly_name,
            "risk_id": location.risk_id,
            "result": None,
            "error": None,
        }

        try:
            entry["risk_id"] = await _ensure_location_risk_id(db, location)
            entry["result"] = await asyncio.to_thread(get_risk_result, entry["risk_id"])
        except RiskFrameworkError as exc:
            logger.warning(
                "Risk lookup failed for case %s location %s: %s",
                case_id,
                location.id,
                exc,
            )
            entry["error"] = str(exc)

        risks.append(entry)

    return risks

