"""
BNG matching (diagram steps 9-10): how well each habitat bank covers what a
development still needs, and at what cost. Used by the marketplace and by the
Off-Site Unit Reservation step's suggestions, so both rank banks the same way.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import (
    ACTIVE_ALLOCATION_STATUSES,
    BNG_ALLOCATION_STEP,
    BNG_CATEGORIES,
    BNG_DEVELOPMENT_WORKFLOW,
    BngStepData,
)
from app.models.case_data import Case, CaseUserAccess
from app.models.workflow import CaseWorkflowRun
from app.services.bng_payload import (
    ONSITE_ACHIEVED,
    ONSITE_DECISION_STEP,
    _names,
    available_habitat_banks,
    case_allocations,
    case_metric,
)

Units = Mapping[str, float]


def _zero() -> dict[str, float]:
    return {category: 0.0 for category in BNG_CATEGORIES}


def match(available: Units, prices: Mapping[str, float | None] | None, need: Units) -> dict[str, Any]:
    """
    What a bank with `available` units can cover of `need`: the units to
    take, the share of the need they cover (0-1) and their cost at the bank's
    prices (None when a needed price is not set).
    """
    take = {c: max(min(float(available.get(c) or 0), float(need.get(c) or 0)), 0.0) for c in BNG_CATEGORIES}
    total = sum(max(float(need.get(c) or 0), 0.0) for c in BNG_CATEGORIES)
    cost: float | None = 0.0
    for category in BNG_CATEGORIES:
        if take[category] <= 0:
            continue
        price = (prices or {}).get(category)
        cost = None if price is None or cost is None else cost + take[category] * float(price)
    return {"take": take, "coverage": sum(take.values()) / total if total > 0 else 0.0, "cost": cost}


def _best_first(m: dict[str, Any]) -> tuple[float, float]:
    return (-m["coverage"], m["cost"] if m["cost"] is not None else float("inf"))


def rank(matches: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best first: most of the need covered, then the lowest cost (unpriced last)."""
    return sorted(matches, key=_best_first)


async def _run(db: AsyncSession, case_id: int) -> CaseWorkflowRun | None:
    return (
        await db.execute(
            select(CaseWorkflowRun)
            .where(CaseWorkflowRun.case_id == case_id)
            .order_by(CaseWorkflowRun.case_workflow_run_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _step_saved(db: AsyncSession, case_id: int, step_code: str) -> dict | None:
    row = (
        await db.execute(select(BngStepData).where(BngStepData.case_id == case_id, BngStepData.step_code == step_code))
    ).scalar_one_or_none()
    return row.data if row is not None else None


async def reservation_status(db: AsyncSession, case: Case) -> str:
    """
    Whether a development can reserve units now: "open" (at or past its
    reservation step), "not_reached", "not_needed" (the target is met
    on-site, so the step was skipped) or "completed".
    """
    run = await _run(db, case.id)
    if run is not None and run.status == "completed":
        return "completed"
    saved = await _step_saved(db, case.id, BNG_ALLOCATION_STEP)
    onsite = await _step_saved(db, case.id, ONSITE_DECISION_STEP) or {}
    if saved is None and onsite.get("onsite_decision") == ONSITE_ACHIEVED:
        return "not_needed"
    if saved is not None or (run is not None and run.current_step == BNG_ALLOCATION_STEP):
        return "open"
    return "not_reached"


async def development_summary(db: AsyncSession, case: Case) -> dict[str, Any]:
    """A development as the marketplace matches for it."""
    metric = await case_metric(db, case)
    need = _zero()
    for entry in metric.get("categories") or []:
        # Still needed, less what is already requested and awaiting the bank.
        need[entry["category"]] = max(
            float(entry.get("remaining_shortfall_units") or 0) - float(entry.get("pending_units") or 0), 0.0
        )
    allocations = await case_allocations(db, case)
    return {
        "case_id": case.id,
        "name": (await _names(db, {case.id})).get(case.id),
        "need": need,
        "reservation_status": await reservation_status(db, case),
        "reservation_step": BNG_ALLOCATION_STEP,
        "requested_bank_ids": sorted(
            {a["habitat_bank_case_id"] for a in allocations if a.get("status") in ACTIVE_ALLOCATION_STATUSES}
        ),
    }


async def user_developments(db: AsyncSession, user_id) -> list[dict[str, Any]]:
    """The BNG developments the user can open, for the marketplace's picker."""
    ids = (
        await db.execute(
            select(Case.id)
            .join(CaseUserAccess, (CaseUserAccess.case_id == Case.id) & (CaseUserAccess.user_id == user_id))
            .where(
                Case.case_type == BNG_DEVELOPMENT_WORKFLOW,
                Case.deleted_at.is_(None),
                CaseUserAccess.can_view.is_(True),
            )
            .order_by(Case.id)
        )
    ).scalars().all()
    names = await _names(db, set(ids))
    return [{"case_id": case_id, "name": names.get(case_id)} for case_id in ids]


async def marketplace(db: AsyncSession, development: Case | None) -> dict[str, Any]:
    """
    The inventory, and when a development is chosen, how well each bank
    covers its remaining need (bank["match"]), best match first.
    """
    banks = await available_habitat_banks(db)
    summary = await development_summary(db, development) if development is not None else None
    for bank in banks:
        bank["match"] = match(bank["available_units"], bank.get("prices"), summary["need"]) if summary else None
    if summary:
        banks.sort(key=lambda bank: _best_first(bank["match"]))
    return {"banks": banks, "development": summary}


async def allocation_options(db: AsyncSession, case: Case) -> dict[str, Any]:
    """
    For a development's reservation step: the off-site units it needs, and
    the banks it can reserve from with the most it can take from each (their
    available units, plus what this development already holds there, so a
    saved request can be kept or changed).
    """
    metric = await case_metric(db, case)
    needed = _zero()
    for entry in metric.get("categories") or []:
        needed[entry["category"]] = float(entry.get("onsite_shortfall_units") or 0)

    options: dict[int, dict[str, Any]] = {}
    for bank in await available_habitat_banks(db):
        options[bank["case_id"]] = {
            "case_id": bank["case_id"],
            "name": bank.get("name"),
            "countries": bank.get("countries") or [],
            "site_names": bank.get("site_names") or [],
            "max": {c: float(bank["available_units"].get(c) or 0) for c in BNG_CATEGORIES},
            "prices": bank.get("prices") or {},
        }
    for allocation in await case_allocations(db, case):
        if allocation.get("status") not in ACTIVE_ALLOCATION_STATUSES:
            continue
        bank_id = allocation["habitat_bank_case_id"]
        option = options.setdefault(bank_id, {
            "case_id": bank_id,
            "name": allocation.get("habitat_bank_name"),
            "countries": [],
            "site_names": [],
            "max": _zero(),
            "prices": {
                "area": allocation.get("price_per_habitat_unit"),
                "hedgerow": allocation.get("price_per_hedgerow_unit"),
                "watercourse": allocation.get("price_per_watercourse_unit"),
            },
        })
        for category in BNG_CATEGORIES:
            option["max"][category] += float(allocation.get(f"{_UNIT_FIELD[category]}") or 0)
    return {"needed": needed, "banks": list(options.values())}


# The allocation's units field per category.
_UNIT_FIELD = {"area": "habitat_units", "hedgerow": "hedgerow_units", "watercourse": "watercourse_units"}


async def allocation_suggestions(
    db: AsyncSession, case: Case, need: Units, exclude_bank_ids: Iterable[int] = ()
) -> list[dict[str, Any]]:
    """Banks (not already in the form) ranked by how much of `need` they cover."""
    excluded = set(exclude_bank_ids)
    options = (await allocation_options(db, case))["banks"]
    matches = [
        {"bank_id": option["case_id"], **match(option["max"], option["prices"], need)}
        for option in options
        if option["case_id"] not in excluded
    ]
    return rank(m for m in matches if m["coverage"] > 0)
