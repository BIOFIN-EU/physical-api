# app/api/lookups.py

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Type

from app.core.db import get_db
from app.models.case_data import UseOfProceeds, OperatorSpecialty, Country
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# 🔑 Map lookup keys → ORM models
LOOKUP_MODELS: dict[str, Type] = {
    "use_of_proceeds": UseOfProceeds,
    "operator_specialties": OperatorSpecialty,
    "country": Country
}


@router.get("/{lookup_key}")
async def get_lookup(lookup_key: str, db: AsyncSession = Depends(get_db)):

    logger.debug(f"Received lookup request for key: {lookup_key}")

    model = LOOKUP_MODELS.get(lookup_key)

    if not model:
        raise HTTPException(status_code=404, detail="Lookup not found")

    result = await db.execute(
        select(model).order_by(model.id)
    )

    rows = result.scalars().all()

    return [
        {
            "value": str(row.id),
            "label": row.name,
        }
        for row in rows
    ]