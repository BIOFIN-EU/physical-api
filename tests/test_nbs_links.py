"""
Linked NbS classifications (environment -> intervention -> approach /
societal challenge): the seeded links and flags, the lookups endpoint's
filters, and the NbS step's check on save.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from starlette.requests import Request
from temporalio.exceptions import ApplicationError

from app.core.seed_case_data_lookups import NBS_INTERVENTION_LINKS, seed_case_data_lookups
from app.models.case_data import (
    CaseNatureBasedSolution,
    NbSEnvironmentIntervention,
    NbSInterventionType,
    NbSSocietalChallengeType,
)
from app.routers.lookups import get_lookup
from app.workflows.activities import SessionLocal, save_nature_based_solution_step

from tests.test_bng import _run, cases  # noqa: F401 (fixture)


@pytest.fixture(scope="module", autouse=True)
def seeded():
    async def seed(db):
        await seed_case_data_lookups(db)
    _run(seed)


def _ids(table: str) -> dict[str, int]:
    with SessionLocal() as session:
        return dict(session.execute(text(f"SELECT code, id FROM case_data.{table}")).all())


def _lookup(key: str, **filters) -> list[str]:
    query = "&".join(f"{k}={v}" for k, v in filters.items()).encode()
    request = Request({"type": "http", "query_string": query, "headers": []})
    rows = _run(lambda db: get_lookup(key, db=db, intermediary_id=None, request=request))
    codes = {row["value"]: row.get("code") for row in rows}
    return sorted(codes.values())




# ---------- seed ----------

def test_seed_sets_flags_and_links():
    with SessionLocal() as session:
        assert session.scalar(select(NbSInterventionType.code).where(NbSInterventionType.matches_all)) == "ecosystem_monitoring"
        cross_cutting = session.scalars(
            select(NbSSocietalChallengeType.code).where(NbSSocietalChallengeType.cross_cutting)
        ).all()
        assert set(cross_cutting) == {
            "climate_resilience", "biodiversity_enhancement", "social_justice_cohesion",
            "green_jobs", "participatory_governance", "knowledge_capacity_building",
        }
        links = session.scalar(select(func.count()).select_from(NbSEnvironmentIntervention))
    expected = sum(len(v["environments"]) for v in NBS_INTERVENTION_LINKS.values())
    assert links == expected


def test_seed_syncs_links_to_the_table():
    env, interventions = _ids("nbs_environment_types"), _ids("nbs_intervention_types")
    with SessionLocal() as session:
        # A stray link, and a missing one.
        session.execute(text(
            "INSERT INTO case_data.nbs_environment_interventions VALUES (:e, :i) ON CONFLICT DO NOTHING"
        ), {"e": env["urban_ecosystem"], "i": interventions["coastal_landscape_management"]})
        session.execute(text(
            "DELETE FROM case_data.nbs_environment_interventions WHERE environment_type_id = :e AND intervention_type_id = :i"
        ), {"e": env["cropland"], "i": interventions["agricultural_landscape_management"]})
        session.commit()

    async def seed(db):
        await seed_case_data_lookups(db)
    _run(seed)

    assert "coastal_landscape_management" not in _lookup("nbs_intervention_type", nbs_environment_type_id=env["urban_ecosystem"])
    assert "agricultural_landscape_management" in _lookup("nbs_intervention_type", nbs_environment_type_id=env["cropland"])


# ---------- lookups endpoint ----------

def test_interventions_follow_the_environment():
    env = _ids("nbs_environment_types")
    assert _lookup("nbs_intervention_type", nbs_environment_type_id=env["cropland"]) == [
        "agricultural_landscape_management", "ecosystem_monitoring", "restoration_degraded_terrestrial",
    ]
    urban = _lookup("nbs_intervention_type", nbs_environment_type_id=env["urban_ecosystem"])
    assert "urban_planning_strategies" in urban and "agricultural_landscape_management" not in urban
    # "Multiple" offers every intervention.
    assert len(_lookup("nbs_intervention_type", nbs_environment_type_id=env["multiple"])) == len(_lookup("nbs_intervention_type"))


def test_approaches_and_challenges_follow_the_intervention():
    interventions = _ids("nbs_intervention_types")
    urban_water = interventions["urban_water_management"]

    approaches = _lookup("nbs_approach_type", nbs_intervention_type_id=urban_water)
    assert "ecosystem_based_water_management" in approaches
    assert "ecosystem_based_fisheries_management" not in approaches

    challenges = _lookup("nbs_societal_challenge_type", nbs_intervention_type_id=urban_water)
    assert {"water_management", "climate_resilience", "biodiversity_enhancement"} <= set(challenges)  # linked + cross-cutting
    assert "food_security" not in challenges

    # "Monitoring" offers every approach and challenge.
    monitoring = interventions["ecosystem_monitoring"]
    assert len(_lookup("nbs_approach_type", nbs_intervention_type_id=monitoring)) == len(_lookup("nbs_approach_type"))
    assert len(_lookup("nbs_societal_challenge_type", nbs_intervention_type_id=monitoring)) == len(
        _lookup("nbs_societal_challenge_type")
    )


def test_unknown_filters_are_refused():
    with pytest.raises(HTTPException) as exc:
        _lookup("nbs_approach_type", nbs_environment_type_id=1)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        _lookup("nbs_intervention_type", nbs_environment_type_id="abc")
    assert exc.value.status_code == 422


# ---------- the NbS step ----------

def _saved(case_id: int) -> CaseNatureBasedSolution:
    with SessionLocal() as session:
        return session.scalar(select(CaseNatureBasedSolution).where(CaseNatureBasedSolution.case_id == case_id))


def test_step_saves_a_combination_that_fits(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    env, interventions = _ids("nbs_environment_types"), _ids("nbs_intervention_types")
    approaches, challenges = _ids("nbs_approach_types"), _ids("nbs_societal_challenge_types")
    save_nature_based_solution_step(case_id, {
        "nbs_environment_type_id": env["cropland"],
        "nbs_intervention_type_id": interventions["agricultural_landscape_management"],
        "nbs_approach_type_id": approaches["ecosystem_based_agricultural_management"],
        "nbs_societal_challenge_type_id": challenges["food_security"],
        # Sent by cases still on the old step config: ignored.
        "nbs_type_id": 1,
    })
    assert _saved(case_id).nbs_intervention_type_id == interventions["agricultural_landscape_management"]


def test_step_refuses_a_combination_that_does_not_fit(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    env, interventions = _ids("nbs_environment_types"), _ids("nbs_intervention_types")
    approaches, challenges = _ids("nbs_approach_types"), _ids("nbs_societal_challenge_types")
    with pytest.raises(ApplicationError) as exc:
        save_nature_based_solution_step(case_id, {
            "nbs_environment_type_id": env["cropland"],
            "nbs_intervention_type_id": interventions["urban_planning_strategies"],
            "nbs_approach_type_id": approaches["ecosystem_based_fisheries_management"],
            "nbs_societal_challenge_type_id": challenges["food_security"],
        })
    field_errors = exc.value.details[0]
    assert set(field_errors) == {"nbs_intervention_type_id", "nbs_approach_type_id", "nbs_societal_challenge_type_id"}
    assert _saved(case_id) is None


def test_options_without_a_parent_are_not_checked(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    approaches = _ids("nbs_approach_types")
    save_nature_based_solution_step(case_id, {"nbs_approach_type_id": approaches["green_infrastructure"]})
    assert _saved(case_id).nbs_approach_type_id == approaches["green_infrastructure"]
