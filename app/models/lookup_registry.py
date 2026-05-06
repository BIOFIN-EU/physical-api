from app.models.case_data import (
    UseOfProceeds,
    OperatorSpecialty,
    Country,
    FinancingType,
    NBSType,
    ImplementationStage,
    NbSEnvironmentType,
    NbSApproachType,
    NbSInterventionType,
    NbSSocietalChallengeType,
    Intermediary,
    IntermediaryFunction,
)

LOOKUP_REGISTRY = {
    "use_of_proceeds": UseOfProceeds,
    "operator_specialty": OperatorSpecialty,
    "country": Country,
    "financing_type": FinancingType,
    "nbs_type": NBSType,
    "implementation_stage": ImplementationStage,
    "nbs_environment_type": NbSEnvironmentType,
    "nbs_approach_type": NbSApproachType,
    "nbs_intervention_type": NbSInterventionType,
    "nbs_societal_challenge_type": NbSSocietalChallengeType,
    "intermediary": Intermediary,
    "intermediary_function": IntermediaryFunction,
}