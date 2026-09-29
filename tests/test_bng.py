"""
Biodiversity Net Gain prototype: metric, step activities, the allocation
capacity rule (activity and database trigger), and the case payload.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from temporalio.exceptions import ApplicationError

from app.core.settings import settings
from app.models.bng import (
    BNG_DEVELOPMENT_WORKFLOW,
    BNG_HABITAT_BANK_WORKFLOW,
    BngCondition,
    BngHabitatParcel,
    BngHabitatType,
    BngStepData,
    BngStrategicSignificance,
    BngUnitAllocation,
)
from app.models.case_data import Case
from app.services.bng_metric import ParcelUnits, parcel_units, summarise
from app.services.bng_payload import available_habitat_banks
from app.services.case_state import build_case_payload
from app.workflows.activities import SessionLocal
from app.workflows.bng_activities import BNG_ACTIVITIES


def _run(coro_fn):
    async def main():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await coro_fn(db)
        finally:
            await engine.dispose()

    return asyncio.run(main())


@pytest.fixture(scope="module")
def reference():
    """Minimal reference data: one habitat per category, two conditions, one significance."""
    with SessionLocal() as session:
        def get_or_add(model, code, **values):
            row = session.execute(select(model).where(model.code == code)).scalar_one_or_none()
            if row is None:
                row = model(code=code, **values)
                session.add(row)
                session.flush()
            return row.id

        ids = {
            "area": get_or_add(BngHabitatType, "test_area", name="Test grassland", category="area",
                               distinctiveness="medium", distinctiveness_score=Decimal(4)),
            "hedgerow": get_or_add(BngHabitatType, "test_hedge", name="Test hedge", category="hedgerow",
                                   distinctiveness="low", distinctiveness_score=Decimal(2)),
            "watercourse": get_or_add(BngHabitatType, "test_ditch", name="Test ditch", category="watercourse",
                                      distinctiveness="medium", distinctiveness_score=Decimal(4)),
            "poor": get_or_add(BngCondition, "test_poor", name="Poor", multiplier=Decimal(1)),
            "good": get_or_add(BngCondition, "test_good", name="Good", multiplier=Decimal(3)),
            "low": get_or_add(BngStrategicSignificance, "test_low", name="Low", multiplier=Decimal(1)),
        }
        session.commit()
        return ids


def _case(case_type: str, status: str = "in_progress") -> int:
    with SessionLocal() as session:
        case = Case(case_type=case_type, status=status, created_by=uuid.uuid4(), updated_by=uuid.uuid4())
        session.add(case)
        session.commit()
        return case.id


@pytest.fixture()
def cases():
    created: list[int] = []

    def make(case_type: str, status: str = "in_progress") -> int:
        case_id = _case(case_type, status)
        created.append(case_id)
        return case_id

    yield make

    with SessionLocal() as session:
        session.execute(
            BngUnitAllocation.__table__.delete().where(
                BngUnitAllocation.development_case_id.in_(created)
                | BngUnitAllocation.habitat_bank_case_id.in_(created)
            )
        )
        session.execute(Case.__table__.delete().where(Case.id.in_(created)))
        session.commit()


def _parcel(ref, category, size, condition="poor"):
    return {
        "habitat_type_id": ref[category],
        "condition_id": ref[condition],
        "strategic_significance_id": ref["low"],
        "size": size,
    }


def _bank_with_uplift(cases, ref) -> int:
    """A completed habitat bank: 10 ha poor -> good grassland = 40 -> 120 units (uplift 80)."""
    bank = cases(BNG_HABITAT_BANK_WORKFLOW, status="completed")
    BNG_ACTIVITIES["save_bng_baseline_habitats_step"](bank, {"parcels": [_parcel(ref, "area", "10")]})
    BNG_ACTIVITIES["save_bng_proposed_habitats_step"](bank, {"parcels": [_parcel(ref, "area", "10", "good")]})
    return bank


# ---------- metric ----------

def test_parcel_units_formula():
    assert parcel_units(Decimal("2.5"), Decimal(4), Decimal("2"), Decimal("1.1")) == Decimal("22.0000")


def test_development_summary_shortfall_and_allocation():
    parcels = [
        ParcelUnits("baseline", "area", Decimal(100)),
        ParcelUnits("proposed", "area", Decimal(90)),
    ]
    summary = summarise(parcels, role="development", allocated={"area": Decimal(15)})
    area = next(c for c in summary["categories"] if c["category"] == "area")

    assert area["target_units"] == 110.0
    assert area["onsite_shortfall_units"] == 20.0
    assert area["remaining_shortfall_units"] == 5.0
    assert area["change_percent"] == -10.0
    assert summary["meets_target"] is False


def test_bank_summary_available_units():
    parcels = [ParcelUnits("baseline", "hedgerow", Decimal(10)), ParcelUnits("proposed", "hedgerow", Decimal(30))]
    hedgerow = next(
        c for c in summarise(parcels, role="habitat_bank", allocated={"hedgerow": Decimal(5)})["categories"]
        if c["category"] == "hedgerow"
    )
    assert hedgerow["available_units"] == 15.0


# ---------- activities ----------

def test_habitat_step_stores_parcels_with_units(cases, reference):
    case_id = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_baseline_habitats_step"](case_id, {
        "parcels": [_parcel(reference, "area", "2.5"), _parcel(reference, "hedgerow", "0.4")],
    })

    with SessionLocal() as session:
        rows = session.execute(select(BngHabitatParcel).where(BngHabitatParcel.case_id == case_id)).scalars().all()
        assert {(r.category, r.phase, float(r.units)) for r in rows} == {
            ("area", "baseline", 10.0),      # 2.5 ha x 4 x 1 x 1
            ("hedgerow", "baseline", 0.8),   # 0.4 km x 2 x 1 x 1
        }


def test_form_step_stores_answers(cases):
    case_id = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_development_details_step"](case_id, {
        "planning_authority": "Test Council",
        "_step_code": "ignored",
    })

    with SessionLocal() as session:
        row = session.execute(select(BngStepData).where(BngStepData.case_id == case_id)).scalar_one()
        assert row.step_code == "development_details"
        assert row.data == {"planning_authority": "Test Council", "_saved": True}


def test_allocation_within_capacity(cases, reference):
    bank = _bank_with_uplift(cases, reference)
    development = cases(BNG_DEVELOPMENT_WORKFLOW)

    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "50"}],
    })

    with SessionLocal() as session:
        allocation = session.execute(
            select(BngUnitAllocation).where(BngUnitAllocation.development_case_id == development)
        ).scalar_one()
        assert float(allocation.habitat_units) == 50.0


def test_allocation_over_capacity_is_refused(cases, reference):
    bank = _bank_with_uplift(cases, reference)
    first, second = cases(BNG_DEVELOPMENT_WORKFLOW), cases(BNG_DEVELOPMENT_WORKFLOW)

    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](first, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "60"}],
    })
    with pytest.raises(ApplicationError) as exc:
        BNG_ACTIVITIES["save_bng_offsite_allocation_step"](second, {
            "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "30"}],
        })
    assert "Not enough units" in str(exc.value.details)


def test_trigger_refuses_direct_over_allocation(cases, reference):
    bank = _bank_with_uplift(cases, reference)
    development = cases(BNG_DEVELOPMENT_WORKFLOW)

    with SessionLocal() as session:
        session.add(BngUnitAllocation(
            development_case_id=development, habitat_bank_case_id=bank,
            habitat_units=Decimal(81), hedgerow_units=Decimal(0), watercourse_units=Decimal(0),
        ))
        with pytest.raises(DBAPIError) as exc:
            session.commit()
        assert "bng_allocation_exceeds_capacity" in str(exc.value)


def test_bank_redesign_cannot_drop_below_allocated(cases, reference):
    bank = _bank_with_uplift(cases, reference)
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "70"}],
    })

    # Downgrading the design to "poor" would leave no uplift at all.
    with pytest.raises(ApplicationError):
        BNG_ACTIVITIES["save_bng_proposed_habitats_step"](bank, {"parcels": [_parcel(reference, "area", "10")]})


def test_unfinished_bank_is_not_available(cases, reference):
    bank = cases(BNG_HABITAT_BANK_WORKFLOW, status="in_progress")
    development = cases(BNG_DEVELOPMENT_WORKFLOW)

    with pytest.raises(ApplicationError):
        BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
            "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "1"}],
        })


# ---------- read side ----------

def test_bng_payload_and_bank_listing(cases, reference):
    bank = _bank_with_uplift(cases, reference)
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_baseline_habitats_step"](development, {"parcels": [_parcel(reference, "area", "5")]})
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "20"}],
    })

    async def body(db):
        return (
            await build_case_payload(db, development),
            await build_case_payload(db, bank),
            await available_habitat_banks(db),
        )

    dev_payload, bank_payload, banks = _run(body)

    assert dev_payload["development_baseline"][0]["units"] == 20.0
    assert dev_payload["offsite_allocation"]["allocations"][0]["habitat_units"] == 20.0
    dev_area = next(c for c in dev_payload["bng_metric"]["categories"] if c["category"] == "area")
    assert dev_area["allocated_units"] == 20.0

    assert bank_payload["bng_allocated_to"][0]["development_case_id"] == development
    listed = next(b for b in banks if b["case_id"] == bank)
    assert listed["available_units"]["area"] == 60.0  # 80 uplift - 20 allocated


def test_non_bng_payload_has_no_bng_keys(case_id):
    payload = _run(lambda db: build_case_payload(db, case_id))
    assert not [key for key in payload if key.startswith("bng_")]
