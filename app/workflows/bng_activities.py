"""
Step activities for the Biodiversity Net Gain (BNG) prototype workflows.

Only the bng_* workflows use these (registered in activity_registry). They
reuse the shared helpers of app.workflows.activities so saving, validation
errors and created_by / updated_by work exactly as for other steps.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from temporalio import activity

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
from app.models.case_data import Case
from app.schemas.bng import HabitatParcelsStepInput, UnitAllocationStepInput
from app.services.bng_metric import parcel_units
from app.workflows.activities import (
    SessionLocal,
    _begin_user_write,
    _commit_or_raise,
    _log_activity_payload,
    _parse_pydantic,
    _pop_actor,
    _raise_validation_error,
)

# Plain form steps: answers are stored as submitted in bng_step_data.
BNG_FORM_STEPS = (
    # Habitat bank
    "site_registration",
    "feasibility",
    "baseline_metric",
    "hmmp",
    "legal_security",
    "gain_site_register",
    # Development
    "development_details",
    "mitigation_hierarchy",
    "onsite_decision",
    "planning_application",
    "planning_permission",
    "gain_condition",
    "gain_plan_approval",
    "commencement",
)

_UNIT_COLUMN = {
    "area": "habitat_units",
    "hedgerow": "hedgerow_units",
    "watercourse": "watercourse_units",
}


def _save_step_data(session, case_id: int, step_code: str, data: dict) -> None:
    row = session.execute(
        select(BngStepData).where(
            BngStepData.case_id == case_id,
            BngStepData.step_code == step_code,
        )
    ).scalar_one_or_none()

    if row is None:
        session.add(BngStepData(case_id=case_id, step_code=step_code, data=data))
    else:
        row.data = data


def _make_form_step_activity(step_code: str):
    @activity.defn(name=f"save_bng_{step_code}_step")
    def save_form_step(case_id: int, data: dict) -> None:
        actor = _pop_actor(data)
        # Keys starting with "_" are transport metadata, not answers.
        answers = {key: value for key, value in data.items() if not key.startswith("_")}
        # Marks the step as submitted even when it has no answers.
        answers["_saved"] = True
        _log_activity_payload(f"save_bng_{step_code}_step", case_id, answers)

        with SessionLocal() as session:
            _begin_user_write(session, case_id, actor)
            _save_step_data(session, case_id, step_code, answers)
            _commit_or_raise(session)

    save_form_step.__name__ = f"save_bng_{step_code}_step"
    return save_form_step


def _lock_case(session, case_id: int) -> Case:
    # Same lock as the allocation trigger takes, so parcel edits and
    # allocations against one habitat bank are applied one at a time.
    return session.execute(
        select(Case).where(Case.id == case_id).with_for_update()
    ).scalar_one()


def _bank_totals(session, case_id: int) -> tuple[dict, dict]:
    """(uplift per category, allocated per category) for a habitat bank."""
    uplift = {category: Decimal(0) for category in BNG_CATEGORIES}
    for parcel in session.execute(
        select(BngHabitatParcel).where(BngHabitatParcel.case_id == case_id)
    ).scalars():
        sign = 1 if parcel.phase == "proposed" else -1
        uplift[parcel.category] += sign * parcel.units

    allocated = {category: Decimal(0) for category in BNG_CATEGORIES}
    for allocation in session.execute(
        select(BngUnitAllocation).where(BngUnitAllocation.habitat_bank_case_id == case_id)
    ).scalars():
        for category, column in _UNIT_COLUMN.items():
            allocated[category] += getattr(allocation, column)

    return uplift, allocated


def _make_habitat_parcels_activity(phase: str):
    @activity.defn(name=f"save_bng_{phase}_habitats_step")
    def save_habitat_parcels(case_id: int, data: dict) -> None:
        """
        Replace this case's parcels for one phase (baseline or proposed),
        computing each parcel's units. For a habitat bank, refuse a change
        that would leave less uplift than developments have already taken.
        """
        actor = _pop_actor(data)
        payload = _parse_pydantic(HabitatParcelsStepInput, data)
        _log_activity_payload(f"save_bng_{phase}_habitats_step", case_id, payload)

        with SessionLocal() as session:
            _begin_user_write(session, case_id, actor)
            case = _lock_case(session, case_id)

            habitat_types = {
                row.id: row
                for row in session.execute(
                    select(BngHabitatType).where(
                        BngHabitatType.id.in_({p.habitat_type_id for p in payload.parcels})
                    )
                ).scalars()
            }
            conditions = {row.id: row for row in session.execute(select(BngCondition)).scalars()}
            significance = {
                row.id: row for row in session.execute(select(BngStrategicSignificance)).scalars()
            }

            new_rows = []
            for index, parcel in enumerate(payload.parcels, start=1):
                habitat = habitat_types.get(parcel.habitat_type_id)
                condition = conditions.get(parcel.condition_id)
                strategic = significance.get(parcel.strategic_significance_id)

                if habitat is None or condition is None or strategic is None:
                    _raise_validation_error(
                        "Please correct the highlighted fields.",
                        {"parcels": f"Row {index}: choose a habitat, condition and strategic significance."},
                    )

                new_rows.append(
                    BngHabitatParcel(
                        case_id=case_id,
                        phase=phase,
                        category=habitat.category,
                        parcel_name=(parcel.parcel_name or "").strip() or None,
                        habitat_type_id=habitat.id,
                        condition_id=condition.id,
                        strategic_significance_id=strategic.id,
                        size=parcel.size,
                        units=parcel_units(
                            parcel.size,
                            habitat.distinctiveness_score,
                            condition.multiplier,
                            strategic.multiplier,
                        ),
                    )
                )

            session.execute(
                BngHabitatParcel.__table__.delete().where(
                    BngHabitatParcel.case_id == case_id,
                    BngHabitatParcel.phase == phase,
                )
            )
            session.add_all(new_rows)
            session.flush()

            if case.case_type == BNG_HABITAT_BANK_WORKFLOW:
                uplift, allocated = _bank_totals(session, case_id)
                for category in BNG_CATEGORIES:
                    if allocated[category] > max(uplift[category], Decimal(0)):
                        _raise_validation_error(
                            "Please correct the highlighted fields.",
                            {
                                "parcels": (
                                    f"Developments have already taken {allocated[category]:.2f} "
                                    f"{category} units from this habitat bank; this change would "
                                    f"leave only {max(uplift[category], Decimal(0)):.2f}."
                                )
                            },
                        )

            _commit_or_raise(session)

    save_habitat_parcels.__name__ = f"save_bng_{phase}_habitats_step"
    return save_habitat_parcels


@activity.defn(name="save_bng_offsite_allocation_step")
def save_bng_offsite_allocation_step(case_id: int, data: dict) -> None:
    """
    Replace the off-site units this development takes from habitat banks.
    The bng_unit_allocations_capacity trigger rejects taking more than a
    bank has; that error is shown to the user as a validation error.
    """
    actor = _pop_actor(data)
    payload = _parse_pydantic(UnitAllocationStepInput, data)
    _log_activity_payload("save_bng_offsite_allocation_step", case_id, payload)

    bank_ids = [allocation.habitat_bank_case_id for allocation in payload.allocations]
    if len(bank_ids) != len(set(bank_ids)):
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {"allocations": "Each habitat bank can only be listed once."},
        )

    with SessionLocal() as session:
        _begin_user_write(session, case_id, actor)

        for allocation in payload.allocations:
            bank = session.get(Case, allocation.habitat_bank_case_id)
            if (
                bank is None
                or bank.id == case_id
                or bank.case_type != BNG_HABITAT_BANK_WORKFLOW
                or bank.status != "completed"
                or bank.deleted_at is not None
            ):
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {"allocations": f"Habitat bank #{allocation.habitat_bank_case_id} is not available."},
                )

            if allocation.habitat_units + allocation.hedgerow_units + allocation.watercourse_units <= 0:
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {"allocations": f"Enter some units to take from habitat bank #{bank.id}, or remove it."},
                )

        session.execute(
            BngUnitAllocation.__table__.delete().where(
                BngUnitAllocation.development_case_id == case_id
            )
        )
        session.add_all(
            BngUnitAllocation(
                development_case_id=case_id,
                habitat_bank_case_id=allocation.habitat_bank_case_id,
                habitat_units=allocation.habitat_units,
                hedgerow_units=allocation.hedgerow_units,
                watercourse_units=allocation.watercourse_units,
            )
            for allocation in payload.allocations
        )
        _save_step_data(session, case_id, BNG_ALLOCATION_STEP, {"_saved": True})

        try:
            session.flush()
        except DBAPIError as exc:
            session.rollback()
            message = str(getattr(exc, "orig", exc))
            if "bng_allocation_exceeds_capacity" in message:
                detail = message.split("bng_allocation_exceeds_capacity:", 1)[1].split("\n", 1)[0].strip()
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {"allocations": f"Not enough units: {detail}."},
                )
            raise

        _commit_or_raise(session)


BNG_ACTIVITIES = {
    **{
        f"save_bng_{step_code}_step": _make_form_step_activity(step_code)
        for step_code in BNG_FORM_STEPS
    },
    "save_bng_baseline_habitats_step": _make_habitat_parcels_activity("baseline"),
    "save_bng_proposed_habitats_step": _make_habitat_parcels_activity("proposed"),
    "save_bng_offsite_allocation_step": save_bng_offsite_allocation_step,
}
