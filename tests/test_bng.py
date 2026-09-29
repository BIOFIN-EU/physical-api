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
    # Requested, not yet accepted by the bank: pending, not secured.
    assert dev_area["pending_units"] == 20.0
    assert dev_area["allocated_units"] == 0.0

    assert bank_payload["bng_allocated_to"][0]["development_case_id"] == development
    listed = next(b for b in banks if b["case_id"] == bank)
    assert listed["available_units"]["area"] == 60.0  # 80 uplift - 20 allocated


def test_non_bng_payload_has_no_bng_keys(case_id):
    payload = _run(lambda db: build_case_payload(db, case_id))
    assert not [key for key in payload if key.startswith("bng_")]


# ---------- phase 2: marketplace lifecycle ----------

from app.models.bng import BngTransaction  # noqa: E402
from app.models.case_data import CaseUserAccess  # noqa: E402
from app.services.bng_marketplace import apply_allocation_action  # noqa: E402
from app.services.bng_payload import bank_finances  # noqa: E402
from app.workflows.case_workflow import ConfigDrivenCaseWorkflow  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _owner(case_id: int) -> uuid.UUID:
    user = uuid.uuid4()
    with SessionLocal() as session:
        session.add(CaseUserAccess(
            case_id=case_id, user_id=user, case_role="borrower", is_owner=True,
            can_view=True, can_update=True, can_delete=True, can_assign_users=True,
        ))
        session.commit()
    return user


def _priced_bank(cases, ref, price="100") -> int:
    bank = _bank_with_uplift(cases, ref)
    BNG_ACTIVITIES["save_bng_unit_pricing_step"](bank, {"price_per_habitat_unit": price, "delivery_cost": "3000"})
    return bank


def _allocation(development: int, bank: int) -> BngUnitAllocation:
    with SessionLocal() as session:
        return session.execute(
            select(BngUnitAllocation).where(
                BngUnitAllocation.development_case_id == development,
                BngUnitAllocation.habitat_bank_case_id == bank,
            )
        ).scalar_one()


def _action(allocation_id: int, action: str, user: uuid.UUID) -> str:
    return _run(lambda db: apply_allocation_action(db, allocation_id=allocation_id, action=action, user_id=user)).status


def _development_needing(cases, ref, needed_area_units: int) -> int:
    """A development whose area target needs `needed_area_units` off-site (nothing on-site afterwards)."""
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    # baseline: size x 4 x 1 x 1; target = baseline x 1.1; proposed is 0.
    size = Decimal(needed_area_units) / Decimal("4.4")
    BNG_ACTIVITIES["save_bng_baseline_habitats_step"](development, {"parcels": [_parcel(ref, "area", str(size))]})
    return development


def test_request_prices_are_snapshotted(cases, reference):
    bank = _priced_bank(cases, reference, price="120")
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "10"}],
    })
    row = _allocation(development, bank)
    assert row.status == "requested"
    assert float(row.price_per_habitat_unit) == 120.0
    assert float(row.total_price) == 1200.0


def test_full_lifecycle_to_transaction_record(cases, reference):
    bank = _priced_bank(cases, reference)
    bank_owner = _owner(bank)
    development = _development_needing(cases, reference, 44)

    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "44"}],
    })
    allocation_id = _allocation(development, bank).id

    assert _action(allocation_id, "accept", bank_owner) == "reserved"

    # Resubmitting the same amount keeps the accepted reservation.
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "44"}],
    })
    assert _allocation(development, bank).status == "reserved"

    # Refused permission leaves it reserved; granted allocates it.
    BNG_ACTIVITIES["save_bng_planning_permission_step"](development, {"decision": "Refused"})
    assert _allocation(development, bank).status == "reserved"
    BNG_ACTIVITIES["save_bng_planning_permission_step"](development, {"decision": "Granted"})
    assert _allocation(development, bank).status == "allocated"

    BNG_ACTIVITIES["save_bng_gain_plan_approval_step"](development, {"gain_plan_reference": "GP-1"})
    row = _allocation(development, bank)
    assert row.status == "retired"

    with SessionLocal() as session:
        transaction = session.execute(
            select(BngTransaction).where(BngTransaction.allocation_id == row.id)
        ).scalar_one()
        assert transaction.reference.startswith("BNG-") and transaction.reference.endswith(f"{row.id:06d}")
        assert float(transaction.habitat_units) == 44.0
        assert float(transaction.total_price) == 4400.0

    finances = _run(lambda db: bank_finances(db, session_get_case(bank)))
    assert finances["committed_revenue"] == 4400.0
    assert finances["potential_revenue"] == 8000.0  # 80 uplift x 100
    assert finances["potential_margin"] == 5000.0   # 8000 - 3000

    # Retired units can't be changed or released any more.
    with pytest.raises(ApplicationError):
        BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {"allocations": []})
    with pytest.raises(HTTPException) as exc:
        _action(row.id, "release", _owner(development))
    assert exc.value.status_code == 409


def session_get_case(case_id: int) -> Case:
    with SessionLocal() as session:
        return session.get(Case, case_id)


def test_gain_plan_needs_the_target_covered(cases, reference):
    bank = _priced_bank(cases, reference)
    development = _development_needing(cases, reference, 44)
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "44"}],
    })
    # Still only requested (not accepted, not allocated).
    with pytest.raises(ApplicationError) as exc:
        BNG_ACTIVITIES["save_bng_gain_plan_approval_step"](development, {"gain_plan_reference": "GP-1"})
    assert "can't be approved yet" in str(exc.value.details)


def test_decline_and_release_free_units(cases, reference):
    bank = _priced_bank(cases, reference)   # 80 units of uplift
    bank_owner = _owner(bank)
    first, second = cases(BNG_DEVELOPMENT_WORKFLOW), cases(BNG_DEVELOPMENT_WORKFLOW)

    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](first, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "70"}],
    })
    # Declined: the 70 units are free again for another development.
    assert _action(_allocation(first, bank).id, "decline", bank_owner) == "declined"
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](second, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "70"}],
    })

    # Released by the developer: free again too.
    assert _action(_allocation(second, bank).id, "release", _owner(second)) == "released"
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](first, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "75"}],
    })
    assert _allocation(first, bank).status == "requested"


def test_only_the_bank_can_accept(cases, reference):
    bank = _priced_bank(cases, reference)
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "5"}],
    })
    with pytest.raises(HTTPException) as exc:
        _action(_allocation(development, bank).id, "accept", _owner(development))
    assert exc.value.status_code == 404


def test_transaction_records_cannot_be_changed(cases, reference):
    bank = _priced_bank(cases, reference)
    development = _development_needing(cases, reference, 44)
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": "44"}],
    })
    _action(_allocation(development, bank).id, "accept", _owner(bank))
    BNG_ACTIVITIES["save_bng_planning_permission_step"](development, {"decision": "Granted"})
    BNG_ACTIVITIES["save_bng_gain_plan_approval_step"](development, {"gain_plan_reference": "GP-1"})

    with SessionLocal() as session:
        with pytest.raises(DBAPIError) as exc:
            session.execute(text(
                f"UPDATE case_data.bng_transactions SET total_price = 0 WHERE development_case_id = {development}"
            ))
        assert "bng_transaction_immutable" in str(exc.value)


def test_next_if_branching():
    wf = ConfigDrivenCaseWorkflow()
    wf.workflow_config = {"steps": {"a": {}, "b": {}, "c": {}}}
    step = {"next": "b", "next_if": [{"field": "choice", "equals": "skip", "next": "c"}]}

    assert wf._resolve_next_step(step, {"choice": "skip"}) == "c"
    assert wf._resolve_next_step(step, {"choice": "other"}) == "b"
    # Steps without next_if behave exactly as before.
    assert wf._resolve_next_step({"next": "b"}, {"choice": "skip"}) == "b"
    assert wf._resolve_next_step({"next": None}, {}) is None
