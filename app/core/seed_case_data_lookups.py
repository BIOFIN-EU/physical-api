from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import (
    UseOfProceeds,
    OperatorSpecialty,
    Country
)


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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

        if hasattr(existing, "description"):
            existing.description = description

        return existing

    row_data = {
        "code": code,
        "name": name,
    }

    if hasattr(model, "description"):
        row_data["description"] = description

    row = model(**row_data)
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
# Countries
# ---------------------------------------------------------

async def seed_countries(db: AsyncSession):
    countries = [
        {"code": "AL", "name": "Albania"},
        {"code": "AD", "name": "Andorra"},
        {"code": "AT", "name": "Austria"},
        {"code": "BY", "name": "Belarus"},
        {"code": "BE", "name": "Belgium"},
        {"code": "BA", "name": "Bosnia and Herzegovina"},
        {"code": "BG", "name": "Bulgaria"},
        {"code": "HR", "name": "Croatia"},
        {"code": "CY", "name": "Cyprus"},
        {"code": "CZ", "name": "Czechia"},
        {"code": "DK", "name": "Denmark"},
        {"code": "EE", "name": "Estonia"},
        {"code": "FI", "name": "Finland"},
        {"code": "FR", "name": "France"},
        {"code": "DE", "name": "Germany"},
        {"code": "GI", "name": "Gibraltar"},
        {"code": "GR", "name": "Greece"},
        {"code": "HU", "name": "Hungary"},
        {"code": "IS", "name": "Iceland"},
        {"code": "IE", "name": "Ireland"},
        {"code": "IT", "name": "Italy"},
        {"code": "XK", "name": "Kosovo"},
        {"code": "LV", "name": "Latvia"},
        {"code": "LI", "name": "Liechtenstein"},
        {"code": "LT", "name": "Lithuania"},
        {"code": "LU", "name": "Luxembourg"},
        {"code": "MT", "name": "Malta"},
        {"code": "MD", "name": "Moldova"},
        {"code": "MC", "name": "Monaco"},
        {"code": "ME", "name": "Montenegro"},
        {"code": "NL", "name": "Netherlands"},
        {"code": "MK", "name": "North Macedonia"},
        {"code": "NO", "name": "Norway"},
        {"code": "PL", "name": "Poland"},
        {"code": "PT", "name": "Portugal"},
        {"code": "RO", "name": "Romania"},
        {"code": "RU", "name": "Russian Federation"},
        {"code": "SM", "name": "San Marino"},
        {"code": "RS", "name": "Serbia"},
        {"code": "SK", "name": "Slovakia"},
        {"code": "SI", "name": "Slovenia"},
        {"code": "ES", "name": "Spain"},
        {"code": "SE", "name": "Sweden"},
        {"code": "CH", "name": "Switzerland"},
        {"code": "UA", "name": "Ukraine"},
        {"code": "GB", "name": "United Kingdom"},
        {"code": "VA", "name": "Vatican City"},
        {"code": "BR", "name": "Brazil"},
    ]

    for country in countries:
        await _upsert_by_code(
            db,
            Country,
            country["code"],
            country["name"],
        )

# ---------------------------------------------------------
# Main entry
# ---------------------------------------------------------

async def seed_case_data_lookups(db: AsyncSession):
    await seed_use_of_proceeds_types(db)
    await seed_operator_specialties(db)
    await seed_countries(db)

    await db.commit()