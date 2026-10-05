"""
Which NbS classifications fit together, for the NbS step:

    Environment -> Intervention -> Approach
                                -> Societal challenge

Used by the lookups endpoint (to offer only what fits the choice above) and
by the step's save (to refuse what doesn't), so both apply the same rules.
The links and flags are seeded in app/core/seed_case_data_lookups.py.
"""
from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select

from app.models.case_data import (
    NbSApproachType,
    NbSEnvironmentIntervention,
    NbSEnvironmentType,
    NbSInterventionApproach,
    NbSInterventionSocietalChallenge,
    NbSInterventionType,
    NbSSocietalChallengeType,
)


def _intervention_matches_all(intervention_id: int) -> ColumnElement[bool]:
    flag = select(NbSInterventionType.matches_all).where(NbSInterventionType.id == intervention_id)
    return flag.scalar_subquery().is_(True)


def interventions_for_environment(environment_id: int) -> ColumnElement[bool]:
    """Condition on NbSInterventionType: fits the environment."""
    environment_matches_all = (
        select(NbSEnvironmentType.matches_all_interventions)
        .where(NbSEnvironmentType.id == environment_id)
        .scalar_subquery()
        .is_(True)
    )
    linked = select(NbSEnvironmentIntervention.intervention_type_id).where(
        NbSEnvironmentIntervention.environment_type_id == environment_id
    )
    return or_(environment_matches_all, NbSInterventionType.matches_all, NbSInterventionType.id.in_(linked))


def approaches_for_intervention(intervention_id: int) -> ColumnElement[bool]:
    """Condition on NbSApproachType: an approach the intervention can follow."""
    linked = select(NbSInterventionApproach.approach_type_id).where(
        NbSInterventionApproach.intervention_type_id == intervention_id
    )
    return or_(_intervention_matches_all(intervention_id), NbSApproachType.id.in_(linked))


def challenges_for_intervention(intervention_id: int) -> ColumnElement[bool]:
    """Condition on NbSSocietalChallengeType: a challenge the intervention addresses."""
    linked = select(NbSInterventionSocietalChallenge.societal_challenge_type_id).where(
        NbSInterventionSocietalChallenge.intervention_type_id == intervention_id
    )
    return or_(
        NbSSocietalChallengeType.cross_cutting,
        _intervention_matches_all(intervention_id),
        NbSSocietalChallengeType.id.in_(linked),
    )


# Filters the lookups endpoint accepts: (lookup key, query parameter) ->
# (the lookup's model, the condition for a parent id). The parameter is the
# parent field's name in the workflow config ("filter_by").
LOOKUP_FILTERS = {
    ("nbs_intervention_type", "nbs_environment_type_id"): (NbSInterventionType, interventions_for_environment),
    ("nbs_approach_type", "nbs_intervention_type_id"): (NbSApproachType, approaches_for_intervention),
    ("nbs_societal_challenge_type", "nbs_intervention_type_id"): (NbSSocietalChallengeType, challenges_for_intervention),
}

# For the step's save: (child field, parent field, child model, condition).
STEP_LINKS = [
    ("nbs_intervention_type_id", "nbs_environment_type_id", NbSInterventionType, interventions_for_environment,
     "This intervention doesn't fit the chosen environment."),
    ("nbs_approach_type_id", "nbs_intervention_type_id", NbSApproachType, approaches_for_intervention,
     "This approach doesn't fit the chosen intervention."),
    ("nbs_societal_challenge_type_id", "nbs_intervention_type_id", NbSSocietalChallengeType, challenges_for_intervention,
     "This societal challenge doesn't fit the chosen intervention."),
]


def mismatches(session, values: dict) -> dict[str, str]:
    """
    {field: message} for the chosen options that don't fit the option above
    them (sync session). A field whose parent is not chosen is not checked.
    """
    errors: dict[str, str] = {}
    for child_field, parent_field, model, condition, message in STEP_LINKS:
        child_id, parent_id = values.get(child_field), values.get(parent_field)
        if child_id is None or parent_id is None:
            continue
        fits = session.execute(
            select(model.id).where(model.id == child_id, condition(parent_id))
        ).first()
        if fits is None:
            errors[child_field] = message
    return errors
