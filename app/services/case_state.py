from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.workflow_config_service import WorkflowConfigService
from app.models.bng import BNG_WORKFLOWS
from app.services.bng_payload import add_bng_sections
from app.models.case_data import (
    Case,
    CaseUserAccess,
    Operator,
    CaseConsent,
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
    IntermediaryFunctionAssignment
)


def to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def orm_to_dict(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()

    mapper = inspect(obj.__class__)
    data: dict[str, Any] = {}

    for attr in mapper.column_attrs:
        key = attr.key
        if key in exclude:
            continue
        data[key] = to_json_value(getattr(obj, key))

    return data


def serialize_lookup(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None

    data = {
        "id": row.id,
        "code": row.code,
        "name": row.name,
    }

    if hasattr(row, "description"):
        data["description"] = row.description

    if hasattr(row, "intervention_type"):
        data["intervention_type"] = row.intervention_type

    return data


@dataclass
class SectionConfig:
    model: type
    many: bool = False
    exclude: set[str] | None = None
    loader_options: tuple[Any, ...] = ()
    serializer: Callable[[Any], dict[str, Any]] | None = None


def serialize_location(row: CaseLocation) -> dict[str, Any]:
    data = orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at", "country_id"},
    )

    data["case_location_id"] = row.id

    data["area_hectares"] = (
        row.area_sqm / 10000 if row.area_sqm is not None else None
    )

    data["country"] = (
        {
            "id": row.country.id,
            "code": row.country.code,
            "name": row.country.name,
        }
        if row.country
        else None
    )

    return data


def serialize_identifiers(row: CaseIdentifiers) -> dict[str, Any]:
    return orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at"},
    )


def serialize_financial(row: CaseFinancial) -> dict[str, Any]:
    data = orm_to_dict(
        row,
        exclude={
            "id",
            "case_id",
            "created_at",
            "updated_at",
            "use_of_proceeds_id",
        },
    )

    data["use_of_proceeds"] = serialize_lookup(row.use_of_proceeds)

    return data


def serialize_operator(row: Operator) -> dict[str, Any]:
    data = orm_to_dict(
        row,
        exclude={
            "id",
            "case_id",
            "created_at",
            "updated_at",
            "operator_specialty_id",
        },
    )

    data["operator_specialty"] = serialize_lookup(row.operator_specialty)

    return data


def serialize_consent(row: CaseConsent) -> dict[str, Any]:
    return orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at"},
    )


def serialize_basic_info(row: CaseBasicInfo) -> dict[str, Any]:
    return orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at"},
    )


def serialize_investment_rationale(row: CaseInvestmentRationale) -> dict[str, Any]:
    return orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at"},
    )


def serialize_nbs(row: CaseNatureBasedSolution) -> dict[str, Any]:
    data = orm_to_dict(
        row,
        exclude={
            "id",
            "case_id",
            "created_at",
            "updated_at",
            "implementation_stage_id",
            "nbs_environment_type_id",
            "nbs_approach_type_id",
            "nbs_intervention_type_id",
            "nbs_societal_challenge_type_id",
        },
    )

    data["implementation_stage"] = serialize_lookup(row.implementation_stage)
    data["nbs_environment_type"] = serialize_lookup(row.nbs_environment_type)
    data["nbs_approach_type"] = serialize_lookup(row.nbs_approach_type)
    data["nbs_intervention_type"] = serialize_lookup(row.nbs_intervention_type)
    data["nbs_societal_challenge_type"] = serialize_lookup(row.nbs_societal_challenge_type)

    return data


def serialize_funding_requirement(row: CaseFundingRequirement) -> dict[str, Any]:
    return orm_to_dict(
        row,
        exclude={"id", "case_id", "created_at", "updated_at"},
    )


def serialize_financing_type(row: CaseFinancingType) -> dict[str, Any]:
    data = orm_to_dict(
        row,
        exclude={
            "id",
            "case_id",
            "created_at",
            "updated_at",
            "financing_type_id",
        },
    )

    data["financing_type"] = serialize_lookup(row.financing_type)

    return data


def serialize_intermediary(row: CaseIntermediary) -> dict[str, Any]:
    return {
        "intermediary": (
            {
                "id": row.intermediary.id,
                "code": f"intermediary_{row.intermediary.id}",
                "name": row.intermediary.name,
                "description": row.intermediary.notes,
            }
            if row.intermediary
            else None
        ),
        "intermediary_function": serialize_lookup(row.intermediary_function),
    }


def serialize_document(row: CaseDocument) -> dict[str, Any]:
    return {
        "case_document_id": row.id,
        "case_id": row.case_id,
        "step_code": row.step_code,
        "field_name": row.field_name,
        "original_filename": row.original_filename,
        "upload_token": row.upload_token,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "created_at": to_json_value(row.created_at),
    }


SECTION_CONFIG: dict[str, SectionConfig] = {
    "location": SectionConfig(
        model=CaseLocation,
        many=True,
        loader_options=(selectinload(CaseLocation.country),),
        serializer=serialize_location,
    ),
    "financial": SectionConfig(
        model=CaseFinancial,
        loader_options=(selectinload(CaseFinancial.use_of_proceeds),),
        serializer=serialize_financial,
    ),
    "identifiers": SectionConfig(
        model=CaseIdentifiers,
        serializer=serialize_identifiers,
    ),
    "operators": SectionConfig(
        model=Operator,
        many=True,
        loader_options=(selectinload(Operator.operator_specialty),),
        serializer=serialize_operator,
    ),
    "documents": SectionConfig(
        model=CaseDocument,
        many=True,
        serializer=serialize_document,
    ),
    "consent": SectionConfig(
        model=CaseConsent,
        serializer=serialize_consent,
    ),
    "basic_info": SectionConfig(
        model=CaseBasicInfo,
        serializer=serialize_basic_info,
    ),
    "investment_rationale": SectionConfig(
        model=CaseInvestmentRationale,
        serializer=serialize_investment_rationale,
    ),
    "nature_based_solution": SectionConfig(
        model=CaseNatureBasedSolution,
        serializer=serialize_nbs,
        loader_options=(
            selectinload(CaseNatureBasedSolution.implementation_stage),
            selectinload(CaseNatureBasedSolution.nbs_environment_type),
            selectinload(CaseNatureBasedSolution.nbs_approach_type),
            selectinload(CaseNatureBasedSolution.nbs_intervention_type),
            selectinload(CaseNatureBasedSolution.nbs_societal_challenge_type),
        ),
    ),
    "funding_requirements": SectionConfig(
        model=CaseFundingRequirement,
        serializer=serialize_funding_requirement,
    ),
    "financing_type": SectionConfig(
        model=CaseFinancingType,
        serializer=serialize_financing_type,
        loader_options=(selectinload(CaseFinancingType.financing_type),),
    ),
    "intermediary": SectionConfig(
        model=CaseIntermediary,
        many=True,
        serializer=serialize_intermediary,
        loader_options=(
            selectinload(CaseIntermediary.intermediary),
            selectinload(CaseIntermediary.intermediary_function),
        ),
    ),
}


async def fetch_section(
        db: AsyncSession,
        *,
        model: type,
        case_id: int,
        many: bool,
        loader_options: tuple[Any, ...] = (),
) -> Any:
    stmt = select(model).where(model.case_id == case_id)

    for option in loader_options:
        stmt = stmt.options(option)

    result = await db.execute(stmt)
    scalars = result.scalars()

    if many:
        return scalars.all()

    return scalars.one_or_none()


def serialize_row(row: Any, cfg: SectionConfig) -> dict[str, Any]:
    if cfg.serializer:
        return cfg.serializer(row)

    return orm_to_dict(row, exclude=cfg.exclude)


async def build_case_payload(
        db: AsyncSession,
        case_id: int,
) -> dict[str, Any] | None:
    case = await db.get(Case, case_id)
    if case is None:
        return None

    workflows = WorkflowConfigService().load_all().get("workflows", {})

    payload: dict[str, Any] = {
        "caseId": case.id,
        "caseType": case.case_type,
        "caseTypeName": workflows.get(case.case_type, {}).get("name", case.case_type),
        "status": case.status,
        "createdBy": str(case.created_by),
        "createdAt": to_json_value(case.created_at),
        "updatedBy": str(case.updated_by),
        "updatedAt": to_json_value(case.updated_at),
    }

    for section_name, cfg in SECTION_CONFIG.items():
        rows = await fetch_section(
            db,
            model=cfg.model,
            case_id=case_id,
            many=cfg.many,
            loader_options=cfg.loader_options,
        )

        if cfg.many:
            payload[section_name] = [
                serialize_row(row, cfg)
                for row in rows
            ]
        else:
            payload[section_name] = (
                serialize_row(rows, cfg)
                if rows is not None
                else None
            )

    # Biodiversity Net Gain prototype cases only; no other case type is
    # affected.
    if case.case_type in BNG_WORKFLOWS:
        await add_bng_sections(db, case, payload, workflows.get(case.case_type, {}))

    return payload


async def fetch_cases(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """The projects the user is a member of."""
    stmt = (
        select(
            Case,
            CaseBasicInfo.name,
            CaseBasicInfo.high_level_description,
            CaseUserAccess.can_delete,
        )
        .join(CaseUserAccess, CaseUserAccess.case_id == Case.id)
        .outerjoin(CaseBasicInfo, CaseBasicInfo.case_id == Case.id)
        .where(
            CaseUserAccess.user_id == user_id,
            Case.deleted_at.is_(None),
        )
    )
    return _case_list((await db.execute(stmt)).all())


async def fetch_all_cases(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """
    Every project (administrators' support list), newest first; isMember
    says whether the administrator is on it themselves.
    """
    stmt = (
        select(
            Case,
            CaseBasicInfo.name,
            CaseBasicInfo.high_level_description,
            CaseUserAccess.can_delete,
            CaseUserAccess.id.is_not(None),
        )
        .outerjoin(
            CaseUserAccess,
            (CaseUserAccess.case_id == Case.id) & (CaseUserAccess.user_id == user_id),
        )
        .outerjoin(CaseBasicInfo, CaseBasicInfo.case_id == Case.id)
        .where(Case.deleted_at.is_(None))
        .order_by(Case.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    listed = _case_list([row[:4] for row in rows])
    for item, row in zip(listed, rows):
        item["isMember"] = bool(row[4])
    return listed


def _case_list(rows) -> list[dict[str, Any]]:
    workflows = WorkflowConfigService().load_all().get("workflows", {})

    return [
        {
            "caseId": case.id,
            "caseType": case.case_type,
            "caseTypeName": workflows.get(case.case_type, {}).get("name", case.case_type),
            "status": case.status,
            "name": name,
            "description": high_level_description,
            "createdBy": str(case.created_by),
            "createdAt": to_json_value(case.created_at),
            "updatedBy": str(case.updated_by),
            "updatedAt": to_json_value(case.updated_at),
            "canDelete": bool(can_delete),
        }
        for case, name, high_level_description, can_delete in rows
    ]


async def get_case_workflow_config(
        db: AsyncSession,
        case_id: int,
) -> dict[str, Any] | None:
    config_service = WorkflowConfigService()

    workflow_code = await db.scalar(
        select(Case.case_type).where(Case.id == case_id)
    )

    if workflow_code is None:
        return None

    return config_service.get_workflow(workflow_code)
