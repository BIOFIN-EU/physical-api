"""
BNG rules the frontend now reads from the API: bank matching, the
reservation step's options, a development's reservation status, what a user
may do (capacities) and the labels.
"""
from __future__ import annotations

from app.models.bng import BNG_DEVELOPMENT_WORKFLOW, BNG_HABITAT_BANK_WORKFLOW
from app.models.case_data import Case
from app.services.bng_matching import (
    allocation_options,
    allocation_suggestions,
    marketplace,
    match,
    rank,
    reservation_status,
)
from app.services.bng_payload import vocabulary
from app.services.workflow_config_service import WorkflowConfigService
from app.services.workflow_roles import bng_capacities, capacity_for, step_capacities, user_roles
from app.workflows.activities import SessionLocal
from app.workflows.bng_activities import BNG_ACTIVITIES

from tests.test_bng import (  # noqa: F401 (fixtures)
    _access,
    _development_needing,
    _member,
    _priced_bank,
    _run,
    cases,
    reference,
)


def _case(case_id: int) -> Case:
    with SessionLocal() as session:
        return session.get(Case, case_id)


def _request(development: int, bank: int, units: str) -> None:
    BNG_ACTIVITIES["save_bng_offsite_allocation_step"](development, {
        "allocations": [{"habitat_bank_case_id": bank, "habitat_units": units}],
    })


# ---------- pure rules ----------

def test_match_takes_what_the_bank_can_cover_at_its_prices():
    result = match({"area": 5, "hedgerow": 1}, {"area": 100, "hedgerow": None}, {"area": 8, "hedgerow": 0})
    assert result["take"] == {"area": 5.0, "hedgerow": 0.0, "watercourse": 0.0}
    assert result["coverage"] == 5 / 8
    assert result["cost"] == 500.0

    # A needed category without a price: the cost is unknown.
    assert match({"hedgerow": 2}, {"hedgerow": None}, {"hedgerow": 1})["cost"] is None
    # Nothing needed: nothing covered.
    assert match({"area": 5}, {}, {})["coverage"] == 0.0


def test_rank_puts_coverage_first_then_the_lowest_cost():
    ranked = rank([
        {"bank_id": 1, "coverage": 0.5, "cost": 10.0},
        {"bank_id": 2, "coverage": 1.0, "cost": None},
        {"bank_id": 3, "coverage": 1.0, "cost": 50.0},
        {"bank_id": 4, "coverage": 1.0, "cost": 20.0},
    ])
    assert [m["bank_id"] for m in ranked] == [4, 3, 2, 1]


def test_capacity_for_own_role_on_behalf_or_none():
    assert capacity_for({"lpa"}, ["developer", "lpa"], can_record_on_behalf=False)["kind"] == "own"
    assert capacity_for({"lpa"}, ["developer", "lpa"], can_record_on_behalf=False)["role"] == "lpa"
    assert capacity_for(set(), ["lpa"], can_record_on_behalf=True) == {
        "kind": "on_behalf", "role": "lpa", "roles": ["lpa"],
    }
    assert capacity_for(set(), ["lpa"], can_record_on_behalf=True, allow_on_behalf=False)["kind"] == "none"
    assert capacity_for({"developer"}, ["lpa"], can_record_on_behalf=False)["kind"] == "none"


def test_vocabulary_labels_every_code():
    labels = vocabulary()
    assert {r["code"] for r in labels["roles"]} == {"landowner", "investor", "developer", "ecologist", "lpa", "responsible_body"}
    assert {c["code"]: c["size_unit"] for c in labels["categories"]} == {"area": "ha", "hedgerow": "km", "watercourse": "km"}
    assert labels["allocation_statuses"]["requested"] == "Requested"
    assert labels["monitoring_statuses"]["submitted"] == "Awaiting verification"
    assert labels["signoff_decisions"]["submitted"] == "Completed"


# ---------- with the database ----------

def test_marketplace_matches_the_remaining_need(cases, reference):
    bank = _priced_bank(cases, reference, price="100")        # 80 area units, 100 each
    development = _development_needing(cases, reference, 22)   # a 5 ha site

    result = _run(lambda db: marketplace(db, _case(development)))
    assert result["development"]["need"]["area"] == 22.0
    assert result["development"]["reservation_step"] == "offsite_allocation"
    # Best match first: both cover all 22 units, so the cheaper one (created
    # later, so not first by id) comes first.
    cheaper = _priced_bank(cases, reference, price="50")
    ranked = _run(lambda db: marketplace(db, _case(development)))["banks"]
    assert [b["case_id"] for b in ranked if b["case_id"] in (bank, cheaper)] == [cheaper, bank]
    listed = next(b for b in result["banks"] if b["case_id"] == bank)
    assert listed["match"]["take"]["area"] == 22.0
    assert listed["match"]["coverage"] == 1.0
    assert listed["match"]["cost"] == 2200.0

    # Once requested, the units no longer count as needed, and the bank is listed as requested.
    _request(development, bank, "22")
    summary = _run(lambda db: marketplace(db, _case(development)))["development"]
    assert summary["need"]["area"] == 0.0
    assert summary["requested_bank_ids"] == [bank]

    # Browsing without a development: no matches.
    assert all(b["match"] is None for b in _run(lambda db: marketplace(db, None))["banks"])


def test_reservation_status_follows_the_step(cases, reference):
    development = _development_needing(cases, reference, 22)
    assert _run(lambda db: reservation_status(db, _case(development))) == "not_reached"
    bank = _priced_bank(cases, reference)
    _request(development, bank, "5")
    assert _run(lambda db: reservation_status(db, _case(development))) == "open"


def test_allocation_options_add_back_the_developments_own_request(cases, reference):
    bank = _priced_bank(cases, reference)                     # 80 area units
    first = _development_needing(cases, reference, 22)
    second = _development_needing(cases, reference, 22)
    _request(first, bank, "70")

    # The first can keep (or change) its 70; the second can only have the 10 left.
    options = _run(lambda db: allocation_options(db, _case(first)))
    assert options["needed"]["area"] == 22.0
    assert next(o for o in options["banks"] if o["case_id"] == bank)["max"]["area"] == 80.0
    others = _run(lambda db: allocation_options(db, _case(second)))["banks"]
    assert next(o for o in others if o["case_id"] == bank)["max"]["area"] == 10.0

    # Suggestions leave out banks already in the form.
    need = {"area": 5.0}
    suggested = _run(lambda db: allocation_suggestions(db, _case(second), need))
    assert bank in [s["bank_id"] for s in suggested]
    excluded = _run(lambda db: allocation_suggestions(db, _case(second), need, [bank]))
    assert bank not in [s["bank_id"] for s in excluded]


def test_my_capacities_per_step_and_action(cases):
    development = cases(BNG_DEVELOPMENT_WORKFLOW)
    developer = _member(development, "developer")
    manager = _member(development, manager=True)
    config = WorkflowConfigService().get_workflow(BNG_DEVELOPMENT_WORKFLOW)

    def steps(case_id, user):
        held = _run(lambda db: user_roles(db, case_id, user))
        return step_capacities(held, _access(case_id, user), config)

    assert steps(development, developer)["offsite_allocation"]["kind"] == "own"
    assert steps(development, developer)["planning_permission"]["kind"] == "none"     # the LPA's
    mine = _run(lambda db: bng_capacities(db, _case(development), _access(development, developer)))
    assert mine["allocations"]["kind"] == "own"                        # the developer releases
    assert mine["monitoring_submit"] is None and mine["monitoring_verify"] is None

    # A manager may record the developer's steps on their behalf, but not
    # the LPA's decisions (no allow_on_behalf).
    assert steps(development, manager)["planning_application"] == {
        "kind": "on_behalf", "role": "developer", "roles": ["developer"],
    }
    assert steps(development, manager)["planning_permission"] == {"kind": "none", "role": "lpa", "roles": ["lpa"]}

    bank = cases(BNG_HABITAT_BANK_WORKFLOW)
    ecologist = _member(bank, "ecologist")
    at_bank = _run(lambda db: bng_capacities(db, _case(bank), _access(bank, ecologist)))
    assert at_bank["allocations"]["kind"] == "none"                   # landowner or investor decide
    assert at_bank["monitoring_verify"]["kind"] == "own"
    assert at_bank["monitoring_submit"]["kind"] == "none"