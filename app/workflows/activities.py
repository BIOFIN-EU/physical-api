from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from temporalio import activity
from temporalio.exceptions import ApplicationError

from pydantic import ValidationError

from app.core.settings import settings
from app.models.case_data import Case
from app.models.workflow import CaseWorkflowRun
from app.models.case_data import (
    CaseLocation,
    CaseFinancial,
    CaseIdentifiers,
    CaseDocument,
    CaseBasicInfo,
    CaseFinancingType,
    CaseNatureBasedSolution,
    CaseFundingRequirement,
    CaseInvestmentRationale,
)
from app.schemas.case_workflow import (
    LocationStepInput,
    FinancialStepInput,
    IdentifiersStepInput,
    BasicInfoStepInput,
    FinancingTypeStepInput,
    NatureBasedSolutionStepInput,
    FundingRequirementsStepInput,
    InvestmentRationaleStepInput,
)


# --- DB setup ---
engine = create_engine(
    settings.sync_database_url,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


# --- Error helpers ---
def _raise_validation_error(
    message: str,
    field_errors: dict[str, str] | None = None,
) -> None:
    raise ApplicationError(
        message,
        field_errors or {},
        type="ValidationError",
        non_retryable=True,
    )


def _handle_integrity_error(exc: IntegrityError) -> None:
    text = str(exc)

    if "ck_case_financials_nature_positive_percentage" in text:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "nature_positive_percentage": "Nature positive percentage must be between 0 and 100."
            },
        )

    if "ck_case_funding_requirements_total_matches_breakdown" in text:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "funding_amount": "Funding amount must equal direct funding plus indirect funding.",
                "direct_funding_amount": "Direct funding plus indirect funding must match the total funding amount.",
                "indirect_funding_amount": "Direct funding plus indirect funding must match the total funding amount.",
            },
        )

    raise exc


def _commit_or_raise(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        _handle_integrity_error(exc)
    except Exception:
        session.rollback()
        raise


# --- Validators ---
def _validate_percentage(value: Decimal | float | int | None, field_name: str) -> None:
    if value is None:
        return

    numeric_value = Decimal(value)
    if numeric_value < 0 or numeric_value > 100:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: "Must be between 0 and 100."},
        )


def _validate_non_empty_string(value: Any, field_name: str, display_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: f"{display_name} is required."},
        )


def _validate_non_empty_list_of_ints(value: Any, field_name: str, display_name: str) -> None:
    if not isinstance(value, list) or not value:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: f"{display_name} must contain at least one selection."},
        )

    for item in value:
        if not isinstance(item, int):
            _raise_validation_error(
                "Please correct the highlighted fields.",
                {field_name: f"Each {display_name} value must be an integer."},
            )


def _validate_file_metadata(
    supporting_document: Any,
    field_name: str,
) -> dict[str, Any]:
    if not supporting_document or not isinstance(supporting_document, dict):
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: "File metadata is required."},
        )

    required_keys = [
        "original_filename",
        "stored_filename",
        "upload_token",
        "storage_provider",
        "bucket_name",
        "object_key",
    ]

    missing_keys: list[str] = []

    for key in required_keys:
        value = supporting_document.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_keys.append(key)

    if missing_keys:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: f"Missing file metadata: {', '.join(missing_keys)}"},
        )

    return supporting_document


def _validate_funding_breakdown(
    funding_amount: Decimal | None,
    direct_funding_amount: Decimal | None,
    indirect_funding_amount: Decimal | None,
) -> None:
    if (
        funding_amount is not None
        and direct_funding_amount is not None
        and indirect_funding_amount is not None
    ):
        if funding_amount != direct_funding_amount + indirect_funding_amount:
            _raise_validation_error(
                "Please correct the highlighted fields.",
                {
                    "funding_amount": "Funding amount must equal direct funding plus indirect funding.",
                    "direct_funding_amount": "Direct funding plus indirect funding must match the total funding amount.",
                    "indirect_funding_amount": "Direct funding plus indirect funding must match the total funding amount.",
                },
            )


def _parse_pydantic(model_cls, data: dict) -> Any:
    try:
        return model_cls(**data)
    except ValidationError as exc:
        field_errors: dict[str, str] = {}

        for err in exc.errors():
            loc = err.get("loc", [])
            msg = err.get("msg", "Invalid value")
            if loc:
                field_errors[str(loc[-1])] = msg

        _raise_validation_error(
            "Please correct the highlighted fields.",
            field_errors or {"form": "Invalid input."},
        )


# --- Shared helpers ---
def _get_case_or_raise(session: Session, case_id: int) -> Case:
    case = session.execute(
        select(Case).where(Case.id == case_id)
    ).scalar_one_or_none()

    if not case:
        raise ApplicationError(
            f"Case {case_id} not found.",
            type="NotFoundError",
            non_retryable=True,
        )

    return case


def _get_run_or_raise(session: Session, case_id: int) -> CaseWorkflowRun:
    run = session.execute(
        select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id)
    ).scalar_one_or_none()

    if not run:
        raise ApplicationError(
            f"Workflow run for case {case_id} not found.",
            type="NotFoundError",
            non_retryable=True,
        )

    return run


# --- Activities ---

@activity.defn
def save_location_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(LocationStepInput, data)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseLocation).where(CaseLocation.case_id == case_id)
        ).scalar_one_or_none()

        if existing:
            existing.polygon_wkt = payload.polygon_wkt
            existing.country_id = payload.country_id
            existing.region = payload.region
            existing.notes = payload.notes
        else:
            session.add(
                CaseLocation(
                    case_id=case_id,
                    polygon_wkt=payload.polygon_wkt,
                    country_id=payload.country_id,
                    region=payload.region,
                    notes=payload.notes,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_financial_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(FinancialStepInput, data)

    _validate_percentage(
        payload.nature_positive_percentage,
        "nature_positive_percentage",
    )

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseFinancial).where(CaseFinancial.case_id == case_id)
        ).scalar_one_or_none()

        if existing:
            existing.loan_amount = payload.loan_amount
            existing.currency = payload.currency
            existing.use_of_proceeds_id = payload.use_of_proceeds_id
            existing.nature_positive_percentage = payload.nature_positive_percentage
            existing.notes = payload.notes
        else:
            session.add(
                CaseFinancial(
                    case_id=case_id,
                    loan_amount=payload.loan_amount,
                    currency=payload.currency,
                    use_of_proceeds_id=payload.use_of_proceeds_id,
                    nature_positive_percentage=payload.nature_positive_percentage,
                    notes=payload.notes,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_identifiers_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(IdentifiersStepInput, data)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseIdentifiers).where(CaseIdentifiers.case_id == case_id)
        ).scalar_one_or_none()

        if existing:
            existing.organic_farmer_number = payload.organic_farmer_number
            existing.environment_scheme_number = payload.environment_scheme_number
            existing.subsidy_reference = payload.subsidy_reference
            existing.registry_notes = payload.registry_notes
        else:
            session.add(
                CaseIdentifiers(
                    case_id=case_id,
                    organic_farmer_number=payload.organic_farmer_number,
                    environment_scheme_number=payload.environment_scheme_number,
                    subsidy_reference=payload.subsidy_reference,
                    registry_notes=payload.registry_notes,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_basic_info_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(BasicInfoStepInput, data)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseBasicInfo).where(CaseBasicInfo.case_id == case_id)
        ).scalar_one_or_none()

        if existing:
            existing.name = payload.name
            existing.high_level_description = payload.high_level_description
        else:
            session.add(
                CaseBasicInfo(
                    case_id=case_id,
                    name=payload.name,
                    high_level_description=payload.high_level_description,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_financing_type_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(FinancingTypeStepInput, data)

    if not isinstance(payload.financing_type_id, int) or payload.financing_type_id <= 0:
        raise ValueError("Financing Type must be a positive integer.")

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseFinancingType).where(CaseFinancingType.case_id == case_id)
        ).scalar_one_or_none()

        if existing:
            existing.financing_type_id = payload.financing_type_id
        else:
            session.add(
                CaseFinancingType(
                    case_id=case_id,
                    financing_type_id=payload.financing_type_id,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_nature_based_solution_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(NatureBasedSolutionStepInput, data)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseNatureBasedSolution).where(
                CaseNatureBasedSolution.case_id == case_id
            )
        ).scalar_one_or_none()

        if existing:
            existing.nbs_type_id = payload.nbs_type_id
            existing.implementation_stage_id = payload.implementation_stage_id
            existing.nbs_environment_type_id = payload.nbs_environment_type_id
            existing.nbs_approach_type_id = payload.nbs_approach_type_id
            existing.nbs_intervention_type_id = payload.nbs_intervention_type_id
            existing.nbs_societal_challenge_type_id = payload.nbs_societal_challenge_type_id
            existing.nbs_description = payload.nbs_description
        else:
            session.add(
                CaseNatureBasedSolution(
                    case_id=case_id,
                    nbs_type_id=payload.nbs_type_id,
                    implementation_stage_id=payload.implementation_stage_id,
                    nbs_environment_type_id=payload.nbs_environment_type_id,
                    nbs_approach_type_id=payload.nbs_approach_type_id,
                    nbs_intervention_type_id=payload.nbs_intervention_type_id,
                    nbs_societal_challenge_type_id=payload.nbs_societal_challenge_type_id,
                    nbs_description=payload.nbs_description,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_funding_requirements_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(FundingRequirementsStepInput, data)

    _validate_funding_breakdown(
        payload.funding_amount,
        payload.direct_funding_amount,
        payload.indirect_funding_amount,
    )

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseFundingRequirement).where(
                CaseFundingRequirement.case_id == case_id
            )
        ).scalar_one_or_none()

        if existing:
            existing.funding_amount = payload.funding_amount
            existing.currency = payload.currency
            existing.upfront_costs = payload.upfront_costs
            existing.maintenance_costs = payload.maintenance_costs
            existing.direct_funding_amount = payload.direct_funding_amount
            existing.indirect_funding_amount = payload.indirect_funding_amount
            existing.funding_notes = payload.funding_notes
        else:
            session.add(
                CaseFundingRequirement(
                    case_id=case_id,
                    funding_amount=payload.funding_amount,
                    currency=payload.currency,
                    upfront_costs=payload.upfront_costs,
                    maintenance_costs=payload.maintenance_costs,
                    direct_funding_amount=payload.direct_funding_amount,
                    indirect_funding_amount=payload.indirect_funding_amount,
                    funding_notes=payload.funding_notes,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_investment_rationale_step(case_id: int, data: dict) -> None:
    payload = _parse_pydantic(InvestmentRationaleStepInput, data)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseInvestmentRationale).where(
                CaseInvestmentRationale.case_id == case_id
            )
        ).scalar_one_or_none()

        if existing:
            existing.nature_positive_benefits = payload.nature_positive_benefits
            existing.legislation_compliance = payload.legislation_compliance
            existing.additional_rationale = payload.additional_rationale
        else:
            session.add(
                CaseInvestmentRationale(
                    case_id=case_id,
                    nature_positive_benefits=payload.nature_positive_benefits,
                    legislation_compliance=payload.legislation_compliance,
                    additional_rationale=payload.additional_rationale,
                )
            )

        _commit_or_raise(session)


@activity.defn
def update_run_state(
    case_id: int,
    current_step: str | None,
    status: str,
) -> None:
    with SessionLocal() as session:
        case = _get_case_or_raise(session, case_id)
        run = _get_run_or_raise(session, case_id)

        case.status = status
        run.status = status
        run.current_step = current_step

        _commit_or_raise(session)


@activity.defn
def save_supporting_document_step(case_id: int, data: dict) -> None:
    step_code = data.get("_step_code")
    field_name = data.get("_field_name")
    document_notes = data.get("document_notes")

    _validate_non_empty_string(step_code, "_step_code", "Step code")
    _validate_non_empty_string(field_name, "_field_name", "Field name")

    supporting_document = _validate_file_metadata(data.get(field_name), field_name)

    with SessionLocal() as session:
        existing = session.execute(
            select(CaseDocument).where(
                CaseDocument.case_id == case_id,
                CaseDocument.step_code == step_code,
                CaseDocument.field_name == field_name,
            )
        ).scalar_one_or_none()

        if existing:
            existing.original_filename = supporting_document["original_filename"]
            existing.stored_filename = supporting_document["stored_filename"]
            existing.upload_token = supporting_document["upload_token"]
            existing.content_type = supporting_document.get("content_type")
            existing.size_bytes = supporting_document.get("size_bytes")
            existing.storage_provider = supporting_document["storage_provider"]
            existing.bucket_name = supporting_document["bucket_name"]
            existing.object_key = supporting_document["object_key"]
            existing.notes = document_notes
        else:
            session.add(
                CaseDocument(
                    case_id=case_id,
                    step_code=step_code,
                    field_name=field_name,
                    original_filename=supporting_document["original_filename"],
                    stored_filename=supporting_document["stored_filename"],
                    upload_token=supporting_document["upload_token"],
                    content_type=supporting_document.get("content_type"),
                    size_bytes=supporting_document.get("size_bytes"),
                    storage_provider=supporting_document["storage_provider"],
                    bucket_name=supporting_document["bucket_name"],
                    object_key=supporting_document["object_key"],
                    notes=document_notes,
                )
            )

        _commit_or_raise(session)