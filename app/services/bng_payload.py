"""
Read side of the BNG prototype: the per-case data the dashboard and pathway
screens show, the metric summary, and the habitat banks open for allocation.
Only called for bng_* cases (see case_state.build_case_payload).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bng import (
    BNG_ALLOCATION_STEP,
    BNG_CATEGORIES,
    BNG_HABITAT_BANK_WORKFLOW,
    BngCondition,
    BngHabitatParcel,
    BngHabitatType,
    BngStepData,
    BngStrategicSignificance,
    BngUnitAllocation,
)
from app.models.case_data import Case, CaseBasicInfo
from app.schemas.bng import HabitatParcelInput
from app.services.bng_metric import ParcelUnits, parcel_units, summarise

_UNIT_COLUMN = {
    "area": "habitat_units",
    "hedgerow": "hedgerow_units",
    "watercourse": "watercourse_units",
}


def _role(case_type: str) -> str:
    return "habitat_bank" if case_type == BNG_HABITAT_BANK_WORKFLOW else "development"


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


async def _allocated(db: AsyncSession, case: Case) -> dict[str, Decimal]:
    column = (
        BngUnitAllocation.habitat_bank_case_id
        if case.case_type == BNG_HABITAT_BANK_WORKFLOW
        else BngUnitAllocation.development_case_id
    )
    totals = {category: Decimal(0) for category in BNG_CATEGORIES}
    for allocation in (await db.execute(select(BngUnitAllocation).where(column == case.id))).scalars():
        for category, attribute in _UNIT_COLUMN.items():
            totals[category] += getattr(allocation, attribute)
    return totals


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

    return summarise(parcels, role=_role(case.case_type), allocated=await _allocated(db, case))


async def _names(db: AsyncSession, case_ids: set[int]) -> dict[int, str | None]:
    if not case_ids:
        return {}
    result = await db.execute(
        select(CaseBasicInfo.case_id, CaseBasicInfo.name).where(CaseBasicInfo.case_id.in_(case_ids))
    )
    return dict(result.all())


async def add_bng_sections(
    db: AsyncSession,
    case: Case,
    payload: dict[str, Any],
    workflow_config: dict[str, Any],
) -> None:
    """
    Add a BNG case's data to its dashboard payload, keyed by step code like
    other steps (so the dashboard and stepper read it the same way), plus
    `bng_metric`.
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

    if BNG_ALLOCATION_STEP in payload:
        allocations = (
            await db.execute(
                select(BngUnitAllocation)
                .where(BngUnitAllocation.development_case_id == case.id)
                .order_by(BngUnitAllocation.id)
            )
        ).scalars().all()
        names = await _names(db, {allocation.habitat_bank_case_id for allocation in allocations})
        payload[BNG_ALLOCATION_STEP] = {
            "_saved": True,
            "allocations": [
                {
                    "habitat_bank_case_id": allocation.habitat_bank_case_id,
                    "habitat_bank_name": names.get(allocation.habitat_bank_case_id),
                    "habitat_units": float(allocation.habitat_units),
                    "hedgerow_units": float(allocation.hedgerow_units),
                    "watercourse_units": float(allocation.watercourse_units),
                }
                for allocation in allocations
            ],
        }

    if case.case_type == BNG_HABITAT_BANK_WORKFLOW:
        developments = (
            await db.execute(
                select(BngUnitAllocation).where(BngUnitAllocation.habitat_bank_case_id == case.id)
            )
        ).scalars().all()
        names = await _names(db, {allocation.development_case_id for allocation in developments})
        payload["bng_allocated_to"] = [
            {
                "development_case_id": allocation.development_case_id,
                "development_name": names.get(allocation.development_case_id),
                "habitat_units": float(allocation.habitat_units),
                "hedgerow_units": float(allocation.hedgerow_units),
                "watercourse_units": float(allocation.watercourse_units),
            }
            for allocation in developments
        ]

    payload["bng_metric"] = await case_metric(db, case)


async def available_habitat_banks(db: AsyncSession) -> list[dict[str, Any]]:
    """Completed, non-deleted habitat banks with units still available."""
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
        if any(value > 0 for value in available.values()):
            listed.append({
                "case_id": bank.id,
                "name": names.get(bank.id),
                "available_units": available,
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
