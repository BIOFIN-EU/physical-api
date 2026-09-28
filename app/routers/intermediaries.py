from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.dependencies.case_access import require_case_permission
from app.dependencies.gateway_identity import get_request_user_id
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
        intermediary_function_id=row.intermediary_function_id,
        created_at=row.created_at,
    )


DUPLICATE_EMAIL = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="An intermediary with this email already exists.",
)


async def _raise_if_email_taken(
    db: AsyncSession,
    email: str | None,
    exclude_id: int | None = None,
) -> None:
    """Mirror uq_intermediaries_active_email so a duplicate gets a clear 409."""
    if not email:
        return

    query = select(Intermediary.id).where(
        func.lower(Intermediary.email) == email.lower(),
        Intermediary.deleted_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(Intermediary.id != exclude_id)

    if await db.scalar(query) is not None:
        raise DUPLICATE_EMAIL


async def _commit_or_conflict(db: AsyncSession, *, flush_only: bool = False) -> None:
    # Covers two requests racing past _raise_if_email_taken.
    try:
        if flush_only:
            await db.flush()
        else:
            await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_intermediaries_active_email" in str(exc.orig):
            raise DUPLICATE_EMAIL from exc
        raise


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
    user_id: UUID = Depends(get_request_user_id),
):
    await _validate_intermediary_function_ids(db, payload.function_ids)
    await _raise_if_email_taken(db, str(payload.email) if payload.email else None)

    intermediary = Intermediary(
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        contact_details=payload.contact_details,
        notes=payload.notes,
        created_by=user_id,
        updated_by=user_id,
    )

    db.add(intermediary)
    await _commit_or_conflict(db, flush_only=True)

    for function_id in payload.function_ids:
        db.add(
            IntermediaryFunctionAssignment(
                intermediary_id=intermediary.id,
                intermediary_function_id=function_id,
            )
        )

    await _commit_or_conflict(db)

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
        .where(Intermediary.deleted_at.is_(None))
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
        .where(Intermediary.id == intermediary_id, Intermediary.deleted_at.is_(None))
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
    user_id: UUID = Depends(get_request_user_id),
):
    result = await db.execute(
        select(Intermediary).where(
            Intermediary.id == intermediary_id,
            Intermediary.deleted_at.is_(None),
        )
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    update_data = payload.model_dump(exclude_unset=True)
    function_ids = update_data.pop("function_ids", None)

    if update_data.get("email"):
        await _raise_if_email_taken(db, str(update_data["email"]), exclude_id=intermediary.id)

    for field, value in update_data.items():
        if field == "email" and value is not None:
            value = str(value)

        setattr(intermediary, field, value)

    intermediary.updated_by = user_id

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

    await _commit_or_conflict(db)

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
    user_id: UUID = Depends(get_request_user_id),
):
    """
    Soft delete: the intermediary disappears from lists, lookups and new
    assignments, but the row stays, so projects that already use it keep
    their assignment (a hard delete cascaded those away). Repeating it is a
    no-op.
    """
    result = await db.execute(
        select(Intermediary).where(Intermediary.id == intermediary_id)
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    if intermediary.deleted_at is None:
        intermediary.deleted_at = datetime.now(timezone.utc)
        intermediary.deleted_by = user_id
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
        select(Intermediary).where(
            Intermediary.id == payload.intermediary_id,
            Intermediary.deleted_at.is_(None),
        )
    )

    intermediary = result.scalar_one_or_none()

    if intermediary is None:
        raise HTTPException(status_code=404, detail="Intermediary not found")

    await _validate_intermediary_function_ids(db, [payload.intermediary_function_id])

    # Matches uq_case_intermediary_function: one row per intermediary *and*
    # function, so the same intermediary can hold several functions.
    existing_result = await db.execute(
        select(CaseIntermediary).where(
            CaseIntermediary.case_id == case_id,
            CaseIntermediary.intermediary_id == payload.intermediary_id,
            CaseIntermediary.intermediary_function_id == payload.intermediary_function_id,
        )
    )

    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Intermediary already assigned to this case with this function",
        )

    row = CaseIntermediary(
        case_id=case_id,
        intermediary_id=payload.intermediary_id,
        intermediary_function_id=payload.intermediary_function_id,
        created_by=access.user_id,
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
    intermediary_function_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
):
    """
    Remove an intermediary from a case: every function it holds there, or
    only `intermediary_function_id` when given.
    """
    query = select(CaseIntermediary).where(
        CaseIntermediary.case_id == case_id,
        CaseIntermediary.intermediary_id == intermediary_id,
    )
    if intermediary_function_id is not None:
        query = query.where(
            CaseIntermediary.intermediary_function_id == intermediary_function_id
        )

    rows = (await db.execute(query)).scalars().all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Case intermediary assignment not found",
        )

    for row in rows:
        await db.delete(row)
    await db.commit()