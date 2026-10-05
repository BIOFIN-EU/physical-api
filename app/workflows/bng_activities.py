"""
Step activities for the Biodiversity Net Gain (BNG) prototype workflows.

Only the bng_* workflows use these (registered in activity_registry). They
reuse the shared helpers of app.workflows.activities so saving, validation
errors and created_by / updated_by work exactly as for other steps.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from temporalio import activity

from app.models.bng import (
    ACTIVE_ALLOCATION_STATUSES,
    BNG_ALLOCATION_STEP,
    BNG_CATEGORIES,
    BNG_HABITAT_BANK_WORKFLOW,
    BNG_PRICING_STEP,
    LOCKED_ALLOCATION_STATUSES,
    PERMISSION_GRANTED,
    PLANNING_PERMISSION_STEP,
    BngCondition,
    BngHabitatParcel,
    BngHabitatType,
    BngStepData,
    BngStrategicSignificance,
    BngTransaction,
    BngUnitAllocation,
)
from app.models.case_data import Case
from app.schemas.bng import HabitatParcelsStepInput, UnitAllocationStepInput
from app.services.bng_finance import SHARE_FIELDS, prices_from_step, shares_error, shares_from_step, total_price
from app.services.bng_metric import ParcelUnits, parcel_units, summarise
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
    "gain_condition",
    "commencement",
)
# unit_pricing, planning_permission and gain_plan_approval are form steps too,
# with extra checks or changes to other records (see below).

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


def _answers(data: dict) -> dict:
    # Keys starting with "_" are transport metadata, not answers. "_saved"
    # marks the step as submitted even when it has no answers.
    answers = {key: value for key, value in data.items() if not key.startswith("_")}
    answers["_saved"] = True
    return answers


def _check_dates(answers: dict) -> None:
    """Date fields (named *_date) hold an ISO date, YYYY-MM-DD, or nothing."""
    errors = {}
    for key, value in answers.items():
        if not key.endswith("_date") or value in (None, ""):
            continue
        try:
            if not (isinstance(value, str) and len(value) == 10):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            errors[key] = "Enter a valid date."
    if errors:
        _raise_validation_error("Please correct the highlighted fields.", errors)


def _make_form_step_activity(step_code: str, after_save=None):
    """
    A form step storing its answers. `after_save(session, case_id, answers)`
    runs in the same transaction, for steps that also change other records.
    """
    @activity.defn(name=f"save_bng_{step_code}_step")
    def save_form_step(case_id: int, data: dict) -> None:
        actor = _pop_actor(data)
        answers = _answers(data)
        _log_activity_payload(f"save_bng_{step_code}_step", case_id, answers)
        _check_dates(answers)

        with SessionLocal() as session:
            _begin_user_write(session, case_id, actor)
            _save_step_data(session, case_id, step_code, answers)
            if after_save is not None:
                after_save(session, case_id, answers)
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
        select(BngUnitAllocation).where(
            BngUnitAllocation.habitat_bank_case_id == case_id,
            BngUnitAllocation.status.in_(ACTIVE_ALLOCATION_STATUSES),
        )
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


def _units(row) -> dict[str, Decimal]:
    return {category: getattr(row, column) for category, column in _UNIT_COLUMN.items()}


def _bank_prices(session, bank_id: int) -> dict[str, Decimal | None]:
    data = session.execute(
        select(BngStepData.data).where(
            BngStepData.case_id == bank_id,
            BngStepData.step_code == BNG_PRICING_STEP,
        )
    ).scalar_one_or_none()
    return prices_from_step(data)


@activity.defn(name="save_bng_offsite_allocation_step")
def save_bng_offsite_allocation_step(case_id: int, data: dict) -> None:
    """
    Request off-site units from habitat banks (diagram steps 10-11). Each
    submitted bank is matched to this development's existing allocation
    row: an unchanged request keeps its status (a reservation the bank has
    already accepted stays reserved), a changed or re-added one becomes a new
    request at the bank's current prices, and banks no longer listed are
    released. Allocated or retired units can't be changed here. The
    bng_unit_allocations_capacity trigger rejects taking more than a bank has.
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

    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        _begin_user_write(session, case_id, actor)

        existing = {
            row.habitat_bank_case_id: row
            for row in session.execute(
                select(BngUnitAllocation).where(BngUnitAllocation.development_case_id == case_id)
            ).scalars()
        }

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

            requested = {
                "area": allocation.habitat_units,
                "hedgerow": allocation.hedgerow_units,
                "watercourse": allocation.watercourse_units,
            }
            if sum(requested.values()) <= 0:
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {"allocations": f"Enter some units to take from habitat bank #{bank.id}, or remove it."},
                )

            row = existing.get(bank.id)

            if row is not None and row.status in LOCKED_ALLOCATION_STATUSES:
                if _units(row) != requested:
                    _raise_validation_error(
                        "Please correct the highlighted fields.",
                        {"allocations": f"Units from habitat bank #{bank.id} are already {row.status} and can't be changed."},
                    )
                continue

            if row is not None and row.status in ("requested", "reserved") and _units(row) == requested:
                continue  # unchanged request or accepted reservation

            prices = _bank_prices(session, bank.id)
            values = {
                "habitat_units": requested["area"],
                "hedgerow_units": requested["hedgerow"],
                "watercourse_units": requested["watercourse"],
                "status": "requested",
                "price_per_habitat_unit": prices["area"],
                "price_per_hedgerow_unit": prices["hedgerow"],
                "price_per_watercourse_unit": prices["watercourse"],
                "total_price": total_price(requested, prices),
                "decided_at": None,
                "released_at": None,
            }
            if row is None:
                session.add(BngUnitAllocation(development_case_id=case_id, habitat_bank_case_id=bank.id, **values))
            else:
                for field, value in values.items():
                    setattr(row, field, value)

        submitted = set(bank_ids)
        for bank_id, row in existing.items():
            if bank_id in submitted or row.status in ("declined", "released"):
                continue
            if row.status in LOCKED_ALLOCATION_STATUSES:
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {"allocations": f"Units from habitat bank #{bank_id} are already {row.status} and can't be removed."},
                )
            row.status = "released"
            row.released_at = now

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


def _check_revenue_shares(session, case_id: int, answers: dict) -> None:
    """Unit pricing: the revenue split must add up to 100% (step 31)."""
    error = shares_error(answers)
    if error:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {SHARE_FIELDS["landowner"]: error},
        )


def _allocate_on_permission(session, case_id: int, answers: dict) -> None:
    """Planning permission granted: reserved units become allocated (step 14)."""
    if answers.get("decision") not in PERMISSION_GRANTED:
        return
    _allocate_reserved(session, case_id)


def _permission_granted(session, case_id: int) -> bool:
    row = session.execute(
        select(BngStepData).where(
            BngStepData.case_id == case_id, BngStepData.step_code == PLANNING_PERMISSION_STEP
        )
    ).scalar_one_or_none()
    return bool(row and (row.data or {}).get("decision") in PERMISSION_GRANTED)


def _allocate_reserved(session, case_id: int) -> None:
    now = datetime.now(timezone.utc)
    for row in session.execute(
        select(BngUnitAllocation).where(
            BngUnitAllocation.development_case_id == case_id,
            BngUnitAllocation.status == "reserved",
        )
    ).scalars():
        row.status = "allocated"
        row.allocated_at = now


def _development_shortfall(session, case_id: int) -> dict[str, Decimal]:
    """Units still needed per category, counting only allocated/retired units."""
    parcels = [
        ParcelUnits(parcel.phase, parcel.category, parcel.units)
        for parcel in session.execute(
            select(BngHabitatParcel).where(BngHabitatParcel.case_id == case_id)
        ).scalars()
    ]
    secured = {category: Decimal(0) for category in BNG_CATEGORIES}
    for row in session.execute(
        select(BngUnitAllocation).where(
            BngUnitAllocation.development_case_id == case_id,
            BngUnitAllocation.status.in_(LOCKED_ALLOCATION_STATUSES),
        )
    ).scalars():
        for category, amount in _units(row).items():
            secured[category] += amount

    summary = summarise(parcels, role="development", allocated=secured)
    return {entry["category"]: Decimal(str(entry["remaining_shortfall_units"])) for entry in summary["categories"]}


def _retire_on_gain_plan_approval(session, case_id: int, answers: dict) -> None:
    """
    Gain plan approved: the units must cover the target, then they are
    retired and locked (step 16) with a permanent transaction record whose
    reference goes on the gain plan (step 17).
    """
    # Units reserved after permission was granted (accepted late, before
    # accepting allocated them) are allocated now.
    if _permission_granted(session, case_id):
        _allocate_reserved(session, case_id)
        session.flush()
    shortfall = _development_shortfall(session, case_id)
    missing = [f"{amount:.2f} {category}" for category, amount in shortfall.items() if amount > 0]
    if missing:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "gain_plan_reference": (
                    "The gain plan can't be approved yet: the 10% target still needs "
                    + ", ".join(missing)
                    + " units. Off-site units count once they are allocated (planning permission granted)."
                )
            },
        )

    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(BngUnitAllocation).where(
            BngUnitAllocation.development_case_id == case_id,
            BngUnitAllocation.status == "allocated",
        )
    ).scalars().all()
    for row in rows:
        row.status = "retired"
        row.retired_at = now
        # The bank's revenue split at the time of sale, kept with the record.
        shares = shares_from_step(session.execute(
            select(BngStepData.data).where(
                BngStepData.case_id == row.habitat_bank_case_id,
                BngStepData.step_code == BNG_PRICING_STEP,
            )
        ).scalar_one_or_none()) or {}
        session.add(
            BngTransaction(
                reference=f"BNG-{now.year}-{row.id:06d}",
                allocation_id=row.id,
                development_case_id=row.development_case_id,
                habitat_bank_case_id=row.habitat_bank_case_id,
                habitat_units=row.habitat_units,
                hedgerow_units=row.hedgerow_units,
                watercourse_units=row.watercourse_units,
                total_price=row.total_price,
                **{field: shares.get(party) for party, field in SHARE_FIELDS.items()},
            )
        )


BNG_ACTIVITIES = {
    **{
        f"save_bng_{step_code}_step": _make_form_step_activity(step_code)
        for step_code in BNG_FORM_STEPS
    },
    "save_bng_baseline_habitats_step": _make_habitat_parcels_activity("baseline"),
    "save_bng_proposed_habitats_step": _make_habitat_parcels_activity("proposed"),
    "save_bng_offsite_allocation_step": save_bng_offsite_allocation_step,
    "save_bng_unit_pricing_step": _make_form_step_activity(
        "unit_pricing", after_save=_check_revenue_shares
    ),
    "save_bng_planning_permission_step": _make_form_step_activity(
        "planning_permission", after_save=_allocate_on_permission
    ),
    "save_bng_gain_plan_approval_step": _make_form_step_activity(
        "gain_plan_approval", after_save=_retire_on_gain_plan_approval
    ),
}
