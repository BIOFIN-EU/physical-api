from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from temporalio import activity

from app.core.settings import settings
from app.models.workflow import CaseWorkflowRun
from app.models.case_data import CaseLocation, CaseFinancial, CaseIdentifiers, CaseDocument
from app.schemas.case_workflow import (
    LocationStepInput,
    FinancialStepInput,
    IdentifiersStepInput,
)

# IMPORTANT:
# Use the SYNC database URL for Temporal sync activities.
# Recommended URL format in settings.sync_database_url:
#   postgresql+psycopg://user:pass@host:5432/dbname
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


@activity.defn
def save_location_step(case_id: int, data: dict) -> None:
    payload = LocationStepInput(**data)

    with SessionLocal() as session:
        try:
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

            session.commit()
        except Exception:
            session.rollback()
            raise


@activity.defn
def save_financial_step(case_id: int, data: dict) -> None:
    payload = FinancialStepInput(**data)

    with SessionLocal() as session:
        try:
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

            session.commit()
        except Exception:
            session.rollback()
            raise


@activity.defn
def save_identifiers_step(case_id: int, data: dict) -> None:
    payload = IdentifiersStepInput(**data)

    with SessionLocal() as session:
        try:
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

            session.commit()
        except Exception:
            session.rollback()
            raise


@activity.defn
def update_run_state(case_id: int, current_step: str, status: str) -> None:
    with SessionLocal() as session:
        try:
            run = session.execute(
                select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id)
            ).scalar_one()

            run.current_step = current_step
            run.status = status

            session.commit()
        except Exception:
            session.rollback()
            raise

@activity.defn
def save_supporting_document_step(case_id: int, data: dict) -> None:
    step_code = data.get("_step_code")
    field_name = data.get("_field_name")

    if not step_code or not isinstance(step_code, str):
        raise ValueError("_step_code is required")

    if not field_name or not isinstance(field_name, str):
        raise ValueError("_field_name is required")

    supporting_document = data.get(field_name)

    if not supporting_document or not isinstance(supporting_document, dict):
        raise ValueError(f"{field_name} file metadata is required")

    document_notes = data.get("document_notes")

    with SessionLocal() as session:
        try:
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

            session.commit()
        except Exception:
            session.rollback()
            raise