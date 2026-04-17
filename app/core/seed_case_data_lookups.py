from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import (
    UseOfProceeds,
    OperatorSpecialty,
)


async def _upsert_by_code(
    db: AsyncSession,
    model,
    code: str,
    name: str,
    description: str | None = None,
):
    result = await db.execute(
        select(model).where(model.code == code)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = name
        existing.description = description
        return existing

    row = model(
        code=code,
        name=name,
        description=description,
    )
    db.add(row)
    return row


# ---------------------------------------------------------
# Use of proceeds
# ---------------------------------------------------------

async def seed_use_of_proceeds_types(db: AsyncSession):
    values = [
        ("farm_machinery", "Farm Machinery", "Purchase of agricultural machinery and equipment"),
        ("working_capital", "Working Capital", "Short term operational expenses"),
        ("land_purchase", "Land Purchase", "Purchase of agricultural land"),
        ("buildings", "Farm Equipment", "Farm Equipment"),
        ("livestock", "Livestock Purchase", "Purchase of livestock"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, UseOfProceeds, code, name, description)


# ---------------------------------------------------------
# Operator specialties
# ---------------------------------------------------------

async def seed_operator_specialties(db: AsyncSession):
    values = [
        ("agronomy", "Agronomy", "Crop production and agronomic management"),
        ("soil_management", "Soil Management", "Soil health and soil improvement"),
        ("biodiversity", "Biodiversity Management", "Biodiversity monitoring and restoration"),
        ("forestry", "Forestry", "Forest management and restoration"),
        ("water_management", "Water Management", "Irrigation, drainage and water conservation"),
        ("organic_farming", "Organic Farming", "Organic farming certification and practices"),
        ("carbon_farming", "Carbon Farming", "Carbon sequestration and carbon farming practices"),
        ("nature_restoration", "Nature Restoration", "Habitat restoration and ecosystem recovery"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, OperatorSpecialty, code, name, description)


# ---------------------------------------------------------
# Main entry
# ---------------------------------------------------------

async def seed_case_data_lookups(db: AsyncSession):
    await seed_use_of_proceeds_types(db)
    await seed_operator_specialties(db)

    await db.commit()