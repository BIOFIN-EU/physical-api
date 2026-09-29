"""
Read side of the BNG prototype: the per-case data the dashboard and pathway
screens show, the metric summary, the marketplace listing of habitat banks,
allocations and transaction records. Only called for bng_* cases (see
case_state.build_case_payload) and the /api/bng endpoints.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bng import (
    ACCEPTED_ALLOCATION_STATUSES,
    ACTIVE_ALLOCATION_STATUSES,
    BNG_ALLOCATION_STEP,
    BNG_CATEGORIES,
    BNG_HABITAT_BANK_WORKFLOW,
    BNG_PRICING_STEP,
    BngCondition,
    BngHabitatParcel,
    BngHabitatType,
    BngStepData,
    BngStrategicSignificance,
    BngTransaction,
    BngUnitAllocation,
)
from app.models.case_data import Case, CaseBasicInfo, CaseLocation
from app.schemas.bng import HabitatParcelInput
from app.services.bng_finance import bank_financials, delivery_cost_from_step, prices_from_step
from app.services.bng_metric import ParcelUnits, parcel_units, summarise

UNIT_COLUMN = {
    "area": "habitat_units",
    "hedgerow": "hedgerow_units",
    "watercourse": "watercourse_units",
}

# onsite_decision answer that skips the off-site step (next_if in the config)
ONSITE_DECISION_STEP = "onsite_decision"
ONSITE_ACHIEVED = "10% net gain achieved on-site"


def _role(case_type: str) -> str:
    return "habitat_bank" if case_type == BNG_HABITAT_BANK_WORKFLOW else "development"


def _units(row) -> dict[str, Decimal]:
    return {category: getattr(row, column) for category, column in UNIT_COLUMN.items()}


def _float_or_none(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _serialize_parcel(parcel: BngHabitatParcel) -> dict[str, Any]:
    return {
        "id": parcel.id,
        "phase": parcel.phase,
        "category": parcel.category,
        "parcel_name": parcel.parcel_name,
        "habitat_type_id": parcel.habitat_type_id,
        "habitat_type_name": parcel.habitat_type.name,
        "distinctiveness": parcel.habitat_type.distinctiveness,
        "condition_id": parcel.condition_id,
        "condition_name": parcel.condition.name,
        "strategic_significance_id": parcel.strategic_significance_id,
        "strategic_significance_name": parcel.strategic_significance.name,
        "size": float(parcel.size),
        "units": float(parcel.units),
    }


def _serialize_allocation(allocation: BngUnitAllocation, names: dict[int, str | None]) -> dict[str, Any]:
    return {
        "id": allocation.id,
        "status": allocation.status,
        "development_case_id": allocation.development_case_id,
        "development_name": names.get(allocation.development_case_id),
        "habitat_bank_case_id": allocation.habitat_bank_case_id,
        "habitat_bank_name": names.get(allocation.habitat_bank_case_id),
        "habitat_units": float(allocation.habitat_units),
        "hedgerow_units": float(allocation.hedgerow_units),
        "watercourse_units": float(allocation.watercourse_units),
        "price_per_habitat_unit": _float_or_none(allocation.price_per_habitat_unit),
        "price_per_hedgerow_unit": _float_or_none(allocation.price_per_hedgerow_unit),
        "price_per_watercourse_unit": _float_or_none(allocation.price_per_watercourse_unit),
        "total_price": _float_or_none(allocation.total_price),
        "requested_at": allocation.created_at.isoformat() if allocation.created_at else None,
        "decided_at": allocation.decided_at.isoformat() if allocation.decided_at else None,
        "allocated_at": allocation.allocated_at.isoformat() if allocation.allocated_at else None,
        "retired_at": allocation.retired_at.isoformat() if allocation.retired_at else None,
        "released_at": allocation.released_at.isoformat() if allocation.released_at else None,
    }


def _serialize_transaction(transaction: BngTransaction, names: dict[int, str | None]) -> dict[str, Any]:
    return {
        "reference": transaction.reference,
        "development_case_id": transaction.development_case_id,
        "development_name": names.get(transaction.development_case_id),
        "habitat_bank_case_id": transaction.habitat_bank_case_id,
        "habitat_bank_name": names.get(transaction.habitat_bank_case_id),
        "habitat_units": float(transaction.habitat_units),
        "hedgerow_units": float(transaction.hedgerow_units),
        "watercourse_units": float(transaction.watercourse_units),
        "total_price": _float_or_none(transaction.total_price),
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
    }


async def _parcels(db: AsyncSession, case_id: int) -> list[BngHabitatParcel]:
    result = await db.execute(
        select(BngHabitatParcel)
        .where(BngHabitatParcel.case_id == case_id)
        .options(
            selectinload(BngHabitatParcel.habitat_type),
            selectinload(BngHabitatParcel.condition),
            selectinload(BngHabitatParcel.strategic_significance),
        )
        .order_by(BngHabitatParcel.id)
    )
    return list(result.scalars().all())


async def _allocation_rows(db: AsyncSession, case: Case) -> list[BngUnitAllocation]:
    column = (
        BngUnitAllocation.habitat_bank_case_id
        if case.case_type == BNG_HABITAT_BANK_WORKFLOW
        else BngUnitAllocation.development_case_id
    )
    result = await db.execute(select(BngUnitAllocation).where(column == case.id).order_by(BngUnitAllocation.id))
    return list(result.scalars().all())


def _sum(rows, statuses) -> dict[str, Decimal]:
    totals = {category: Decimal(0) for category in BNG_CATEGORIES}
    for row in rows:
        if row.status in statuses:
            for category, amount in _units(row).items():
                totals[category] += amount
    return totals


async def _step_data(db: AsyncSession, case_id: int, step_code: str) -> dict | None:
    return await db.scalar(
        select(BngStepData.data).where(BngStepData.case_id == case_id, BngStepData.step_code == step_code)
    )


async def preview_units(db: AsyncSession, parcels: list[HabitatParcelInput]) -> list[tuple[str, Decimal]]:
    """(category, units) for unsaved parcels; invalid rows are skipped."""
    habitat_types = {row.id: row for row in (await db.execute(select(BngHabitatType))).scalars()}
    conditions = {row.id: row for row in (await db.execute(select(BngCondition))).scalars()}
    significance = {row.id: row for row in (await db.execute(select(BngStrategicSignificance))).scalars()}

    units = []
    for parcel in parcels:
        habitat = habitat_types.get(parcel.habitat_type_id)
        condition = conditions.get(parcel.condition_id)
        strategic = significance.get(parcel.strategic_significance_id)
        if habitat and condition and strategic:
            units.append((
                habitat.category,
                parcel_units(parcel.size, habitat.distinctiveness_score, condition.multiplier, strategic.multiplier),
            ))
    return units


async def case_metric(
    db: AsyncSession,
    case: Case,
    *,
    preview_phase: str | None = None,
    preview_parcels: list[HabitatParcelInput] | None = None,
) -> dict[str, Any]:
    """Metric summary; with preview_*, that phase's saved parcels are replaced."""
    parcels = [
        ParcelUnits(parcel.phase, parcel.category, parcel.units)
        for parcel in await _parcels(db, case.id)
        if parcel.phase != preview_phase
    ]
    if preview_phase is not None:
        parcels += [
            ParcelUnits(preview_phase, category, units)
            for category, units in await preview_units(db, preview_parcels or [])
        ]

    rows = await _allocation_rows(db, case)
    held = ACTIVE_ALLOCATION_STATUSES if case.case_type == BNG_HABITAT_BANK_WORKFLOW else ACCEPTED_ALLOCATION_STATUSES
    return summarise(
        parcels,
        role=_role(case.case_type),
        allocated=_sum(rows, held),
        pending=_sum(rows, ("requested",)),
    )


async def _uplift(db: AsyncSession, case_id: int) -> dict[str, Decimal]:
    uplift = {category: Decimal(0) for category in BNG_CATEGORIES}
    for parcel in (await db.execute(select(BngHabitatParcel).where(BngHabitatParcel.case_id == case_id))).scalars():
        uplift[parcel.category] += parcel.units if parcel.phase == "proposed" else -parcel.units
    return uplift


async def bank_finances(db: AsyncSession, case: Case) -> dict[str, Any]:
    pricing = await _step_data(db, case.id, BNG_PRICING_STEP)
    rows = await _allocation_rows(db, case)
    return bank_financials(
        prices=prices_from_step(pricing),
        delivery_cost=delivery_cost_from_step(pricing),
        uplift=await _uplift(db, case.id),
        by_status={status: _sum(rows, (status,)) for status in ACTIVE_ALLOCATION_STATUSES},
    )


async def _names(db: AsyncSession, case_ids: set[int]) -> dict[int, str | None]:
    if not case_ids:
        return {}
    result = await db.execute(
        select(CaseBasicInfo.case_id, CaseBasicInfo.name).where(CaseBasicInfo.case_id.in_(case_ids))
    )
    return dict(result.all())


async def case_allocations(db: AsyncSession, case: Case) -> list[dict[str, Any]]:
    """A development's allocations, or the requests and allocations to a habitat bank."""
    rows = await _allocation_rows(db, case)
    names = await _names(db, {r.development_case_id for r in rows} | {r.habitat_bank_case_id for r in rows})
    return [_serialize_allocation(row, names) for row in rows]


async def case_transactions(db: AsyncSession, case: Case) -> list[dict[str, Any]]:
    column = (
        BngTransaction.habitat_bank_case_id
        if case.case_type == BNG_HABITAT_BANK_WORKFLOW
        else BngTransaction.development_case_id
    )
    rows = (await db.execute(select(BngTransaction).where(column == case.id).order_by(BngTransaction.id))).scalars().all()
    names = await _names(db, {r.development_case_id for r in rows} | {r.habitat_bank_case_id for r in rows})
    return [_serialize_transaction(row, names) for row in rows]


async def add_bng_sections(
    db: AsyncSession,
    case: Case,
    payload: dict[str, Any],
    workflow_config: dict[str, Any],
) -> None:
    """
    Add a BNG case's data to its dashboard payload, keyed by step code like
    other steps (so the dashboard and stepper read it the same way), plus
    bng_metric, bng_transactions and, for habitat banks, bng_allocated_to and
    bng_financials.
    """
    for row in (await db.execute(select(BngStepData).where(BngStepData.case_id == case.id))).scalars():
        payload[row.step_code] = row.data

    parcels = await _parcels(db, case.id)
    for step_code, step in (workflow_config.get("steps") or {}).items():
        if step.get("ui_mode") != "habitat_table":
            continue
        phase = next(
            (field.get("phase") for field in step.get("fields", []) if field.get("type") == "habitat_table"),
            None,
        )
        rows = [_serialize_parcel(parcel) for parcel in parcels if parcel.phase == phase]
        payload[step_code] = rows or None

    allocations = await case_allocations(db, case)

    if case.case_type == BNG_HABITAT_BANK_WORKFLOW:
        payload["bng_allocated_to"] = allocations
        payload["bng_financials"] = await bank_finances(db, case)
    elif BNG_ALLOCATION_STEP in payload:
        payload[BNG_ALLOCATION_STEP] = {"_saved": True, "allocations": allocations}
    elif (payload.get(ONSITE_DECISION_STEP) or {}).get("onsite_decision") == ONSITE_ACHIEVED:
        # Skipped by next_if: shown as done, with nothing allocated.
        payload[BNG_ALLOCATION_STEP] = {"_saved": True, "_skipped": True, "allocations": []}

    payload["bng_transactions"] = await case_transactions(db, case)
    payload["bng_metric"] = await case_metric(db, case)


async def available_habitat_banks(db: AsyncSession) -> list[dict[str, Any]]:
    """
    The marketplace inventory: completed, non-deleted habitat banks with
    units still available, their prices and where they are.
    """
    banks = (
        await db.execute(
            select(Case)
            .where(
                Case.case_type == BNG_HABITAT_BANK_WORKFLOW,
                Case.status == "completed",
                Case.deleted_at.is_(None),
            )
            .order_by(Case.id)
        )
    ).scalars().all()
    names = await _names(db, {bank.id for bank in banks})

    listed = []
    for bank in banks:
        metric = await case_metric(db, bank)
        available = {entry["category"]: entry["available_units"] for entry in metric["categories"]}
        if not any(value > 0 for value in available.values()):
            continue

        locations = (
            await db.execute(
                select(CaseLocation).where(CaseLocation.case_id == bank.id).options(selectinload(CaseLocation.country))
            )
        ).scalars().all()
        finances = await bank_finances(db, bank)

        listed.append({
            "case_id": bank.id,
            "name": names.get(bank.id),
            "available_units": available,
            "uplift_units": {entry["category"]: max(entry["change_units"], 0) for entry in metric["categories"]},
            "prices": finances["prices"],
            "countries": sorted({loc.country.name for loc in locations if loc.country}),
            "site_names": [loc.friendly_name for loc in locations if loc.friendly_name],
            "site_area_ha": round(sum(loc.area_sqm or 0 for loc in locations) / 10_000, 2),
        })
    return listed


async def reference_data(db: AsyncSession) -> dict[str, Any]:
    habitat_types = (await db.execute(select(BngHabitatType).order_by(BngHabitatType.category, BngHabitatType.name))).scalars()
    conditions = (await db.execute(select(BngCondition).order_by(BngCondition.multiplier))).scalars()
    significance = (await db.execute(select(BngStrategicSignificance).order_by(BngStrategicSignificance.multiplier))).scalars()

    return {
        "habitat_types": [
            {
                "id": row.id,
                "name": row.name,
                "category": row.category,
                "distinctiveness": row.distinctiveness,
                "description": row.description,
            }
            for row in habitat_types
        ],
        "conditions": [
            {"id": row.id, "name": row.name, "multiplier": float(row.multiplier), "description": row.description}
            for row in conditions
        ],
        "strategic_significance": [
            {"id": row.id, "name": row.name, "multiplier": float(row.multiplier), "description": row.description}
            for row in significance
        ],
    }
