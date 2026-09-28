from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.db import get_db
from app.models.case_data import IntermediaryFunctionAssignment
from app.models.lookup_registry import LOOKUP_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{lookup_key}")
async def get_lookup(
    lookup_key: str,
    db: AsyncSession = Depends(get_db),
    # Only the functions this intermediary provides (intermediary_function
    # lookup only), for dropdowns that depend on a chosen intermediary.
    intermediary_id: int | None = Query(default=None),
):
    logger.debug(f"Received lookup request for key: {lookup_key}")

    model = LOOKUP_REGISTRY.get(lookup_key)

    if not model:
        raise HTTPException(status_code=404, detail="Lookup not found")

    query = select(model).order_by(model.id)

    if intermediary_id is not None:
        if lookup_key != "intermediary_function":
            raise HTTPException(
                status_code=400,
                detail="intermediary_id only filters the intermediary_function lookup",
            )
        query = query.join(
            IntermediaryFunctionAssignment,
            IntermediaryFunctionAssignment.intermediary_function_id == model.id,
        ).where(IntermediaryFunctionAssignment.intermediary_id == intermediary_id)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))

    result = await db.execute(query)
    rows = result.scalars().all()

    response = []
    for row in rows:
        # "currency" is the one lookup whose referencing field stores the
        # code itself (a plain String(3) column, e.g. CaseFinancial.currency)
        # rather than a foreign key to this table's row id, so its dropdown
        # value must be the code - every other lookup key is a real FK and
        # keeps using the row id.
        value = row.code if lookup_key == "currency" else str(row.id)

        item = {
            "value": value,
            "label": row.name,
        }

        if hasattr(row, "code"):
            item["code"] = row.code

        if hasattr(row, "description"):
            item["description"] = row.description

        if hasattr(row, "intervention_type"):
            item["intervention_type"] = row.intervention_type

        response.append(item)

    return response