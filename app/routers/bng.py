"""
Biodiversity Net Gain (BNG) prototype endpoints, mounted at /api/bng.
"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.case_access import require_case_permission
from app.dependencies.gateway_identity import get_request_user_id
from app.models.bng import BNG_WORKFLOWS
from app.models.case_data import Case, CaseUserAccess
from app.schemas.bng import HabitatParcelsPreview
from app.services.bng_payload import available_habitat_banks, case_metric, reference_data

router = APIRouter()


async def _bng_case_or_404(db: AsyncSession, case_id: int) -> Case:
    case = await db.get(Case, case_id)
    if case is None or case.case_type not in BNG_WORKFLOWS:
        raise HTTPException(status_code=404, detail="Not a Biodiversity Net Gain project")
    return case


@router.get("/reference-data")
async def get_reference_data(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """Habitat types, conditions and strategic significance for the metric."""
    return await reference_data(db)


@router.get("/habitat-banks")
async def list_habitat_banks(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> list[dict[str, Any]]:
    """Registered habitat banks with units still available, for allocation."""
    return await available_habitat_banks(db)


@router.get("/cases/{case_id}/metric")
async def get_case_metric(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    return await case_metric(db, await _bng_case_or_404(db, case_id))


@router.post("/cases/{case_id}/metric/preview")
async def preview_case_metric(
    case_id: int,
    payload: HabitatParcelsPreview,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """The metric with one phase's parcels replaced by unsaved ones (live preview)."""
    return await case_metric(
        db,
        await _bng_case_or_404(db, case_id),
        preview_phase=payload.phase,
        preview_parcels=payload.parcels,
    )
