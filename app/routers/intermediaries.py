from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.dependencies.case_access import require_case_permission
from app.models.case_data import (
    CaseUserAccess,
    Intermediary,
    IntermediaryFunction,
    IntermediaryFunctionAssignment,
    CaseIntermediary,
)
from app.schemas.case_data import (
    IntermediaryCreate,
    IntermediaryUpdate,
    IntermediaryRead,
    IntermediaryFunctionAssignmentRead,
    CaseIntermediaryAssign,
    CaseIntermediaryRead,
)

router = APIRouter()


def _map_intermediary_read(intermediary: Intermediary) -> IntermediaryRead:
    return IntermediaryRead(
        id=intermediary.id,
        name=intermediary.name,
        address=intermediary.address,
        phone=intermediary.phone,
        email=intermediary.email,
        contact_details=intermediary.contact_details,
        notes=intermediary.notes,
        created_at=intermediary.created_at,
        updated_at=intermediary.updated_at,
        functions=[
            IntermediaryFunctionAssignmentRead(
                id=assignment.id,
                intermediary_id=assignment.intermediary_id,
                intermediary_function_id=assignment.intermediary_function_id,
                intermediary_function_name=assignment.intermediary_function.name,
                intermediary_function_category=assignment.intermediary_function.function_category,
                created_at=assignment.created_at,
            )
            for assignment in intermediary.functions
        ],
    )


def _map_case_intermediary_read(row: CaseIntermediary) -> CaseIntermediaryRead:
    return CaseIntermediaryRead(
        id=row.id,
        case_id=row.case_id,
        intermediary_id=row.intermediary_id,
        intermediary_name=row.intermediary.name if row.intermediary else None,
        created_at=row.created_at,
    )


async def _validate_intermediary_function_ids(
    db: AsyncSession,
    function_ids: list[int],
) -> None:
    if not function_ids:
        return

    result = await db.execute(
        select(IntermediaryFunction.id).where(
            IntermediaryFunction.id.in_(function_ids)
        )
    )

    existing_ids = set(result.scalars().all())
    missing_ids = set(function_ids) - existing_ids

    if missing_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid intermediary function ids",
                "missing_function_ids": sorted(missing_ids),
            },
        )


# ---------------------------------------------------------
# Intermediary master data CRUD
# ---------------------------------------------------------

@router.post(
    "",
    response_model=IntermediaryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_intermediary(
    payload: IntermediaryCreate,
    db: AsyncSession = Depends(get_db),
):
    await _validate_intermediary_function_ids(db, payload.function_ids)

    intermediary = Intermediary(
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        contact_details=payload.contact_details,
        notes=payload.notes,
    )

    db.add(intermediary)
    await db.flush()

    for function_id in payload.function_ids:
        db.add(
            IntermediaryFunctionAssignment(
                intermediary_id=intermediary.id,
                intermediary_function_id=function_id,
            )
        )

    await db.commit()

    result = await db.execute(
        select(Intermediary)
        .where(Intermediary.id == intermediary.id)
        .options(
            selectinload(Intermediary.functions).selectinload(
                IntermediaryFunctionAssignment.intermediary_function
            )
        )
    )

    return _map_intermediary_read(result.scalar_one())


@router.get(
    "",
    response_model=list[IntermediaryRead],
)
async def list_intermediaries(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Intermediary)
        .options(
            selectinload(Intermediary.functions).selectinload(
                IntermediaryFunctionAssignment.intermediary_function
            )
        )
        .order_by(Intermediary.name)
    )

    return [
        _map_intermediary_read(intermediary)
        for intermediary in result.scalars().all()
    ]


@router.get(
    "/{intermediary_id}",
    response_model=IntermediaryRead,
)
async def get_intermediary(
    intermediary_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Intermediary)
        .where(Intermediary.id == intermediary_id)
        .options(
            selectinload(Intermediary.functions).selectinload(
                IntermediaryFunctionAssignment.intermediary_function
            )
        )
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    return _map_intermediary_read(intermediary)


@router.patch(
    "/{intermediary_id}",
    response_model=IntermediaryRead,
)
async def update_intermediary(
    intermediary_id: int,
    payload: IntermediaryUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Intermediary).where(Intermediary.id == intermediary_id)
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    update_data = payload.model_dump(exclude_unset=True)
    function_ids = update_data.pop("function_ids", None)

    for field, value in update_data.items():
        if field == "email" and value is not None:
            value = str(value)

        setattr(intermediary, field, value)

    if function_ids is not None:
        await _validate_intermediary_function_ids(db, function_ids)

        await db.execute(
            IntermediaryFunctionAssignment.__table__.delete().where(
                IntermediaryFunctionAssignment.intermediary_id == intermediary_id
            )
        )

        for function_id in function_ids:
            db.add(
                IntermediaryFunctionAssignment(
                    intermediary_id=intermediary_id,
                    intermediary_function_id=function_id,
                )
            )

    await db.commit()

    result = await db.execute(
        select(Intermediary)
        .where(Intermediary.id == intermediary_id)
        .options(
            selectinload(Intermediary.functions).selectinload(
                IntermediaryFunctionAssignment.intermediary_function
            )
        )
    )

    return _map_intermediary_read(result.scalar_one())


@router.delete(
    "/{intermediary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_intermediary(
    intermediary_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Intermediary).where(Intermediary.id == intermediary_id)
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    await db.delete(intermediary)
    await db.commit()


# ---------------------------------------------------------
# Case intermediary assignment
# ---------------------------------------------------------

@router.post(
    "/cases/{case_id}/intermediaries",
    response_model=CaseIntermediaryRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_intermediary_to_case(
    case_id: int,
    payload: CaseIntermediaryAssign,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
):
    result = await db.execute(
        select(Intermediary).where(Intermediary.id == payload.intermediary_id)
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    existing_result = await db.execute(
        select(CaseIntermediary).where(
            CaseIntermediary.case_id == case_id,
            CaseIntermediary.intermediary_id == payload.intermediary_id,
        )
    )

    existing = existing_result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Intermediary already assigned to this case",
        )

    row = CaseIntermediary(
        case_id=case_id,
        intermediary_id=payload.intermediary_id,
    )

    db.add(row)
    await db.commit()

    result = await db.execute(
        select(CaseIntermediary)
        .where(CaseIntermediary.id == row.id)
        .options(selectinload(CaseIntermediary.intermediary))
    )

    return _map_case_intermediary_read(result.scalar_one())


@router.get(
    "/cases/{case_id}/intermediaries",
    response_model=list[CaseIntermediaryRead],
)
async def list_case_intermediaries(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
):
    result = await db.execute(
        select(CaseIntermediary)
        .where(CaseIntermediary.case_id == case_id)
        .options(selectinload(CaseIntermediary.intermediary))
        .order_by(CaseIntermediary.created_at.desc())
    )

    return [
        _map_case_intermediary_read(row)
        for row in result.scalars().all()
    ]


@router.delete(
    "/cases/{case_id}/intermediaries/{intermediary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_intermediary_from_case(
    case_id: int,
    intermediary_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
):
    result = await db.execute(
        select(CaseIntermediary).where(
            CaseIntermediary.case_id == case_id,
            CaseIntermediary.intermediary_id == intermediary_id,
        )
    )

    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Case intermediary assignment not found",
        )

    await db.delete(row)
    await db.commit()