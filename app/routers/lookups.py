from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.db import get_db
from app.models.lookup_registry import LOOKUP_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{lookup_key}")
async def get_lookup(lookup_key: str, db: AsyncSession = Depends(get_db)):
    logger.debug(f"Received lookup request for key: {lookup_key}")

    model = LOOKUP_REGISTRY.get(lookup_key)

    if not model:
        raise HTTPException(status_code=404, detail="Lookup not found")

    result = await db.execute(select(model).order_by(model.id))
    rows = result.scalars().all()

    response = []
    for row in rows:
        item = {
            "value": str(row.id),
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