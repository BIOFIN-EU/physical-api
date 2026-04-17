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
from app.models.workflow import CaseWorkflowRun
from app.models.case_data import (
    CaseLocation,
    CaseFinancial,
    CaseIdentifiers,
    CaseDocument,
)
from app.schemas.case_workflow import (
    LocationStepInput,
    FinancialStepInput,
    IdentifiersStepInput,
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
            existing.country = payload.country
            existing.region = payload.region
            existing.notes = payload.notes
        else:
            session.add(
                CaseLocation(
                    case_id=case_id,
                    polygon_wkt=payload.polygon_wkt,
                    country=payload.country,
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
def update_run_state(case_id: int, current_step: str, status: str) -> None:
    with SessionLocal() as session:
        run = session.execute(
            select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id)
        ).scalar_one()

        run.current_step = current_step
        run.status = status

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