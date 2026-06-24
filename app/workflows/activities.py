from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import DataError, IntegrityError, StatementError
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
    CaseIntermediary,
    Intermediary,
    IntermediaryFunction
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
    IntermediaryStepInput
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
    """
    Raise a Temporal non-retryable validation error.

    Use this for user/input/data problems that should not be retried by Temporal.
    The optional field_errors dictionary is intended to be consumed by the API/UI
    so that specific fields can be highlighted.
    """
    raise ApplicationError(
        message,
        field_errors or {},
        type="ValidationError",
        non_retryable=True,
    )


def _raise_not_found_error(message: str) -> None:
    """
    Raise a Temporal non-retryable not-found error.

    Missing cases or workflow runs are deterministic business/data errors, not
    transient infrastructure failures, so retrying the activity is not useful.
    """
    raise ApplicationError(
        message,
        type="NotFoundError",
        non_retryable=True,
    )


def _handle_integrity_error(exc: IntegrityError) -> None:
    """
    Convert known database integrity constraint failures into user-facing,
    non-retryable Temporal validation errors.

    Unknown integrity errors are re-raised so truly unexpected DB failures are
    still visible and can be handled by Temporal retry policy.
    """
    text = str(exc)

    if "ck_case_financials_nature_positive_percentage" in text:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "nature_positive_percentage": (
                    "Nature positive percentage must be between 0 and 100."
                )
            },
        )

    if "ck_case_funding_requirements_total_matches_breakdown" in text:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "funding_amount": (
                    "Funding amount must equal direct funding plus indirect funding."
                ),
                "direct_funding_amount": (
                    "Direct funding plus indirect funding must match the total "
                    "funding amount."
                ),
                "indirect_funding_amount": (
                    "Direct funding plus indirect funding must match the total "
                    "funding amount."
                ),
            },
        )

    raise exc


def _handle_data_error(exc: DataError | StatementError) -> None:
    """
    Convert database data-shape/type errors into non-retryable validation errors.

    Examples include values that are too long for a VARCHAR column, invalid enum
    values, invalid numeric coercions, or other malformed persisted values.
    """
    text = str(exc)

    if "character varying(3)" in text or "value too long" in text:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "form": (
                    "One or more values are too long for the database field. "
                    "For currency, use a 3-letter code such as EUR, USD, or GBP."
                )
            },
        )

    _raise_validation_error(
        "Please correct the highlighted fields.",
        {
            "form": (
                "One or more values have an invalid format and could not be saved."
            )
        },
    )


def _commit_or_raise(session: Session) -> None:
    """
    Commit a SQLAlchemy session and normalize expected DB errors.

    Validation-like database errors are converted to non-retryable Temporal
    ApplicationErrors. Unknown exceptions are rolled back and re-raised so they
    can still be retried when appropriate.
    """
    try:
        session.commit()

    except IntegrityError as exc:
        session.rollback()
        _handle_integrity_error(exc)

    except DataError as exc:
        session.rollback()
        _handle_data_error(exc)

    except StatementError as exc:
        session.rollback()
        _handle_data_error(exc)

    except Exception:
        session.rollback()
        raise


# --- Validators ---

def _validate_percentage(value: Decimal | float | int | None, field_name: str) -> None:
    """
    Validate that a percentage value is between 0 and 100.

    None is accepted because optional fields may be omitted by the user.
    """
    if value is None:
        return

    numeric_value = Decimal(value)
    if numeric_value < 0 or numeric_value > 100:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: "Must be between 0 and 100."},
        )


def _validate_currency(value: Any, field_name: str = "currency") -> None:
    """
    Validate that a currency value is a 3-letter code.

    This prevents database DataError failures for VARCHAR(3) currency columns and
    gives the UI a clean validation error instead of allowing Temporal retries.
    """
    if not isinstance(value, str) or len(value.strip()) != 3:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                field_name: (
                    "Currency must be a 3-letter code such as EUR, USD, or GBP."
                )
            },
        )


def _validate_non_empty_string(value: Any, field_name: str, display_name: str) -> None:
    """
    Validate that a value is a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {field_name: f"{display_name} is required."},
        )


def _validate_non_empty_list_of_ints(
        value: Any,
        field_name: str,
        display_name: str,
) -> None:
    """
    Validate that a value is a non-empty list containing only integers.

    Kept for compatibility with existing validation helpers, even if not used by
    every activity in this module.
    """
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
    """
    Validate uploaded supporting document metadata.

    The workflow stores file references, not the physical file contents. This
    ensures the required storage metadata is present before the DB write.
    """
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
    """
    Validate that total funding equals direct plus indirect funding.

    Only validates when all three values are provided. This preserves the
    existing optional-field behavior.
    """
    if (
            funding_amount is not None
            and direct_funding_amount is not None
            and indirect_funding_amount is not None
    ):
        if funding_amount != direct_funding_amount + indirect_funding_amount:
            _raise_validation_error(
                "Please correct the highlighted fields.",
                {
                    "funding_amount": (
                        "Funding amount must equal direct funding plus indirect funding."
                    ),
                    "direct_funding_amount": (
                        "Direct funding plus indirect funding must match the total "
                        "funding amount."
                    ),
                    "indirect_funding_amount": (
                        "Direct funding plus indirect funding must match the total "
                        "funding amount."
                    ),
                },
            )


def _parse_pydantic(model_cls, data: dict) -> Any:
    """
    Parse and validate activity input with a Pydantic schema.

    Pydantic validation errors are converted to non-retryable Temporal
    validation errors so malformed user input does not cause repeated activity
    retries.
    """
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


def _payload_to_log_dict(payload: Any) -> dict[str, Any]:
    """
    Convert a Pydantic payload to a dictionary for safe structured logging.

    Supports both Pydantic v2's model_dump and Pydantic v1's dict method.
    """
    if hasattr(payload, "model_dump"):
        return payload.model_dump()

    if hasattr(payload, "dict"):
        return payload.dict()

    return dict(payload)


def _log_activity_payload(activity_name: str, case_id: int, payload: Any) -> None:
    """
    Log the validated activity payload immediately before persistence.

    This makes debugging much easier because it shows what the worker actually
    received, which may differ from what the API originally logged if Temporal is
    retrying an older activity input.
    """
    activity.logger.info(
        "%s for case %s with payload: %s",
        activity_name,
        case_id,
        _payload_to_log_dict(payload),
    )


# --- Shared helpers ---

def _get_case_or_raise(session: Session, case_id: int) -> Case:
    """
    Fetch a case by ID or raise a non-retryable not-found error.
    """
    case = session.execute(
        select(Case).where(Case.id == case_id)
    ).scalar_one_or_none()

    if not case:
        _raise_not_found_error(f"Case {case_id} not found.")

    return case


def _get_run_or_raise(session: Session, case_id: int) -> CaseWorkflowRun:
    """
    Fetch the workflow run for a case or raise a non-retryable not-found error.
    """
    run = session.execute(
        select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id)
    ).scalar_one_or_none()

    if not run:
        _raise_not_found_error(f"Workflow run for case {case_id} not found.")

    return run


# --- Activities ---

@activity.defn
def save_location_step(case_id: int, data: dict) -> None:
    """
    Save or update the location step for a case.
    """
    payload = _parse_pydantic(LocationStepInput, data)
    _log_activity_payload("save_location_step", case_id, payload)

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
    """
    Save or update the financial step for a case.
    """
    payload = _parse_pydantic(FinancialStepInput, data)

    _validate_currency(payload.currency)
    _validate_percentage(
        payload.nature_positive_percentage,
        "nature_positive_percentage",
    )

    _log_activity_payload("save_financial_step", case_id, payload)

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
    """
    Save or update the identifiers step for a case.
    """
    payload = _parse_pydantic(IdentifiersStepInput, data)
    _log_activity_payload("save_identifiers_step", case_id, payload)

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
    """
    Save or update the basic information step for a case.
    """
    payload = _parse_pydantic(BasicInfoStepInput, data)
    _log_activity_payload("save_basic_info_step", case_id, payload)

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
    """
    Save or update the financing type step for a case.
    """
    payload = _parse_pydantic(FinancingTypeStepInput, data)

    if not isinstance(payload.financing_type_id, int) or payload.financing_type_id <= 0:
        _raise_validation_error(
            "Please correct the highlighted fields.",
            {
                "financing_type_id": (
                    "Financing Type must be a positive integer."
                )
            },
        )

    _log_activity_payload("save_financing_type_step", case_id, payload)

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
    """
    Save or update the nature-based solution step for a case.
    """
    payload = _parse_pydantic(NatureBasedSolutionStepInput, data)
    _log_activity_payload("save_nature_based_solution_step", case_id, payload)

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
            existing.nbs_societal_challenge_type_id = (
                payload.nbs_societal_challenge_type_id
            )
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
                    nbs_societal_challenge_type_id=(
                        payload.nbs_societal_challenge_type_id
                    ),
                    nbs_description=payload.nbs_description,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_funding_requirements_step(case_id: int, data: dict) -> None:
    """
    Save or update the funding requirements step for a case.
    """
    payload = _parse_pydantic(FundingRequirementsStepInput, data)

    _validate_currency(payload.currency)
    _validate_funding_breakdown(
        payload.funding_amount,
        payload.direct_funding_amount,
        payload.indirect_funding_amount,
    )

    _log_activity_payload("save_funding_requirements_step", case_id, payload)

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
    """
    Save or update the investment rationale step for a case.
    """
    payload = _parse_pydantic(InvestmentRationaleStepInput, data)
    _log_activity_payload("save_investment_rationale_step", case_id, payload)

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
    """
    Update the case and workflow run status.

    This activity keeps the domain case status and the workflow-run status in
    sync.
    """
    activity.logger.info(
        "update_run_state for case %s: current_step=%s, status=%s",
        case_id,
        current_step,
        status,
    )

    with SessionLocal() as session:
        case = _get_case_or_raise(session, case_id)
        run = _get_run_or_raise(session, case_id)

        case.status = status
        run.status = status
        run.current_step = current_step

        _commit_or_raise(session)


@activity.defn
def save_supporting_document_step(case_id: int, data: dict) -> None:
    """
    Save or update a supporting document reference for a workflow step.
    """
    step_code = data.get("_step_code")
    field_name = data.get("_field_name")
    document_notes = data.get("document_notes")

    _validate_non_empty_string(step_code, "_step_code", "Step code")
    _validate_non_empty_string(field_name, "_field_name", "Field name")

    supporting_document = _validate_file_metadata(data.get(field_name), field_name)

    activity.logger.info(
        "save_supporting_document_step for case %s: step_code=%s, field_name=%s, "
        "document=%s",
        case_id,
        step_code,
        field_name,
        supporting_document,
    )

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


@activity.defn
def save_intermediary_step(case_id: int, data: dict) -> None:
    """
    Save intermediary assignments for a case.

    Each assignment links:
    - one case
    - one intermediary
    - one intermediary function
    """
    payload = _parse_pydantic(IntermediaryStepInput, data)
    _log_activity_payload("save_intermediary_step", case_id, payload)

    with SessionLocal() as session:
        _get_case_or_raise(session, case_id)

        # Replace all existing intermediary assignments for this case
        session.execute(
            CaseIntermediary.__table__.delete().where(
                CaseIntermediary.case_id == case_id
            )
        )

        seen: set[tuple[int, int]] = set()

        for assignment in payload.assignments:
            key = (
                assignment.intermediary_id,
                assignment.intermediary_function_id,
            )

            if key in seen:
                continue

            seen.add(key)

            intermediary = session.execute(
                select(Intermediary).where(
                    Intermediary.id == assignment.intermediary_id
                )
            ).scalar_one_or_none()

            if intermediary is None:
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {
                        "assignments": (
                            f"Intermediary {assignment.intermediary_id} does not exist."
                        )
                    },
                )

            intermediary_function = session.execute(
                select(IntermediaryFunction).where(
                    IntermediaryFunction.id == assignment.intermediary_function_id
                )
            ).scalar_one_or_none()

            if intermediary_function is None:
                _raise_validation_error(
                    "Please correct the highlighted fields.",
                    {
                        "assignments": (
                            "Selected intermediary function does not exist."
                        )
                    },
                )

            session.add(
                CaseIntermediary(
                    case_id=case_id,
                    intermediary_id=assignment.intermediary_id,
                    intermediary_function_id=assignment.intermediary_function_id,
                )
            )

        _commit_or_raise(session)


@activity.defn
def save_consent_step(case_id: int, data: dict) -> None:
    pass