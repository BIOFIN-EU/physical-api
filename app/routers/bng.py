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
from app.models.bng import BNG_HABITAT_BANK_WORKFLOW, BNG_WORKFLOWS
from app.models.case_data import Case, CaseUserAccess
from app.schemas.bng import HabitatParcelsPreview
from app.services.bng_marketplace import apply_allocation_action
from app.services.bng_payload import (
    available_habitat_banks,
    bank_finances,
    case_allocations,
    case_metric,
    case_transactions,
    reference_data,
)

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
    """
    Marketplace inventory: registered habitat banks with units still
    available, their prices and sites.
    """
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


@router.get("/cases/{case_id}/allocations")
async def get_case_allocations(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    """A development's allocations, or the requests and allocations to a habitat bank."""
    return await case_allocations(db, await _bng_case_or_404(db, case_id))


@router.get("/cases/{case_id}/transactions")
async def get_case_transactions(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    return await case_transactions(db, await _bng_case_or_404(db, case_id))


@router.get("/cases/{case_id}/financials")
async def get_case_financials(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    case = await _bng_case_or_404(db, case_id)
    if case.case_type != BNG_HABITAT_BANK_WORKFLOW:
        raise HTTPException(status_code=404, detail="Financials are only kept for habitat banks")
    return await bank_finances(db, case)


async def _allocation_action(allocation_id: int, action: str, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    allocation = await apply_allocation_action(db, allocation_id=allocation_id, action=action, user_id=user_id)
    return {"id": allocation.id, "status": allocation.status}


@router.post("/allocations/{allocation_id}/accept")
async def accept_allocation(
    allocation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The habitat bank accepts a request: its units become reserved."""
    return await _allocation_action(allocation_id, "accept", db, user_id)


@router.post("/allocations/{allocation_id}/decline")
async def decline_allocation(
    allocation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The habitat bank declines a request: its units are freed."""
    return await _allocation_action(allocation_id, "decline", db, user_id)


@router.post("/allocations/{allocation_id}/release")
async def release_allocation(
    allocation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The development gives back requested or reserved units."""
    return await _allocation_action(allocation_id, "release", db, user_id)
