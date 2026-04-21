from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_data import (
    UseOfProceeds,
    OperatorSpecialty,
    Country,
    FinancingType,
    NBSType,
    ImplementationStage,
    NbSEnvironmentType,
    NbSApproachType,
    NbSInterventionType,
    NbSSocietalChallengeType,
)

async def _upsert_by_code(
    db: AsyncSession,
    model,
    code: str,
    name: str,
    description: str | None = None,
    extra_fields: dict | None = None,
):
    result = await db.execute(
        select(model).where(model.code == code)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = name

        if hasattr(existing, "description"):
            existing.description = description

        if extra_fields:
            for field, value in extra_fields.items():
                if hasattr(existing, field):
                    setattr(existing, field, value)

        return existing

    row_data = {
        "code": code,
        "name": name,
    }

    if hasattr(model, "description"):
        row_data["description"] = description

    if extra_fields:
        row_data.update(extra_fields)

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
# Financing Types
# ---------------------------------------------------------

async def seed_financing_types(db: AsyncSession):
    values = [
        ("private", "Private Financing", "Financing from private investors or institutions"),
        ("public", "Public Financing", "Funding from government or public sector"),
        ("hybrid", "Hybrid Financing", "Combination of public and private funding"),
        ("blended_finance", "Blended Finance", "Use of public funds to de-risk private investment"),
        ("philanthropic", "Philanthropic Funding", "Grants or donations from foundations"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, FinancingType, code, name, description)


# ---------------------------------------------------------
# NBS Types
# ---------------------------------------------------------

async def seed_nbs_types(db: AsyncSession):
    values = [
        ("agroforestry", "Agroforestry", "Integration of trees into agricultural systems"),
        ("wetland_restoration", "Wetland Restoration", "Restoration of wetlands for biodiversity and water regulation"),
        ("reforestation", "Reforestation", "Planting trees to restore forest ecosystems"),
        ("soil_restoration", "Soil Restoration", "Improving soil health and fertility"),
        ("river_restoration", "River Restoration", "Restoration of river ecosystems and natural flow"),
        ("urban_greening", "Urban Greening", "Green infrastructure in urban environments"),
        ("coastal_restoration", "Coastal Restoration", "Restoration of coastal and marine ecosystems"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, NBSType, code, name, description)

# ---------------------------------------------------------
# Implementation Stages
# ---------------------------------------------------------

async def seed_implementation_stages(db: AsyncSession):
    values = [
        ("concept", "Concept", "Early stage idea or concept development"),
        ("feasibility", "Feasibility", "Feasibility analysis and planning"),
        ("pilot", "Pilot", "Small-scale pilot implementation"),
        ("scaling", "Scaling", "Scaling up implementation"),
        ("operational", "Operational", "Fully implemented and operational"),
        ("maintenance", "Maintenance", "Ongoing maintenance and monitoring"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, ImplementationStage, code, name, description)


# ---------------------------------------------------------
# NbS Environment Types - Taken from D2.2 - Table 7
# ---------------------------------------------------------

async def seed_nbs_environment_types(db: AsyncSession):
    values = [
        ("coastal_shelf_open_ocean", "Coastal, Shelf and Open Ocean", "Marine environments including coastal zones, continental shelves, and open ocean systems"),
        ("cropland", "Cropland", "Agricultural land used for crop production"),
        ("forest", "Forest", "Land dominated by trees and forest ecosystems"),
        ("grassland", "Grassland", "Areas dominated by grasses and herbaceous vegetation"),
        ("inland_wetland", "Inland Wetland", "Wetlands located inland such as marshes, swamps, and peatlands"),
        ("marine_inlets_transitional", "Marine Inlets and Transitional Water", "Estuaries, lagoons, and transitional zones between freshwater and marine systems"),
        ("rivers_lakes_ponds", "Rivers, Lakes and Ponds", "Freshwater ecosystems including rivers, lakes, and ponds"),
        ("sparsely_vegetated", "Sparsely Vegetated Land", "Areas with minimal vegetation such as deserts or rocky regions"),
        ("urban_ecosystem", "Urban Ecosystem", "Built environments with green infrastructure and urban biodiversity"),
        ("multiple", "Multiple", "Projects spanning multiple environment types"),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, NbSEnvironmentType, code, name, description)

# ---------------------------------------------------------
# NbS Approach Types - Taken from D2.2 - Table 5
# ---------------------------------------------------------

async def seed_nbs_approach_types(db: AsyncSession):
    values = [
        (
            "ecological_restoration",
            "Ecological Restoration",
            "Ecosystem restoration approaches: The process of assisting the recovery of an ecosystem that has been degraded, damaged or destroyed."
        ),
        (
            "ecological_engineering",
            "Ecological Engineering",
            "Ecosystem restoration approaches: The design of sustainable ecosystems that integrate human society with its natural environment for mutual benefit."
        ),
        (
            "ecosystem_based_adaptation",
            "Ecosystem-based Adaptation",
            "Issue-specific ecosystem-related approaches: The use of biodiversity and ecosystem services to help people adapt to the adverse effects of climate change."
        ),
        (
            "ecosystem_based_mitigation",
            "Ecosystem-based Mitigation",
            "Issue-specific ecosystem-related approaches: Enhancing biodiversity and ecosystem services to support climate change mitigation while avoiding negative impacts."
        ),
        (
            "ecosystem_based_drr",
            "Ecosystem-based Disaster Risk Reduction (DRR)",
            "Issue-specific ecosystem-related approaches: The sustainable management, conservation, and restoration of ecosystems to reduce disaster risk and increase resilience."
        ),
        (
            "green_infrastructure",
            "Green Infrastructure",
            "Infrastructure-related approaches: A strategically planned network of natural and semi-natural areas designed to deliver a wide range of ecosystem services."
        ),
        (
            "ecosystem_based_water_management",
            "Ecosystem-based Water Management",
            "Ecosystem-based management approaches: Integrated management of water resources to sustain ecosystem health while supporting human needs."
        ),
        (
            "ecosystem_based_fisheries_management",
            "Ecosystem-based Fisheries Management",
            "Ecosystem-based management approaches: Managing fisheries in a way that maintains ecosystem health and resilience."
        ),
        (
            "ecosystem_based_forest_management",
            "Ecosystem-based Forest Management",
            "Ecosystem-based management approaches: Sustainable forest management that maintains biodiversity, productivity, and ecosystem processes."
        ),
        (
            "ecosystem_based_agricultural_management",
            "Ecosystem-based Agricultural Management",
            "Ecosystem-based management approaches: Agricultural practices that sustain ecosystem services and biodiversity while enabling production."
        ),
        (
            "area_based_conservation",
            "Area-based Conservation Approaches",
            "Ecosystem protection approaches: Conservation of ecosystems through protected or managed areas."
        ),
    ]

    for code, name, description in values:
        await _upsert_by_code(db, NbSApproachType, code, name, description)

# ---------------------------------------------------------
# NbS Intervention Types - taken from D2.2 Table 43
# ---------------------------------------------------------

async def seed_nbs_intervention_types(db: AsyncSession):
    values = [
        # Type 1
        (
            "protection_conservation_terrestrial",
            "Protection & Conservation (Terrestrial Ecosystems)",
            "type_1",
        ),
        (
            "protection_conservation_marine_coastal",
            "Protection & Conservation (Marine & Coastal Ecosystems)",
            "type_1",
        ),

        # Type 2
        (
            "agricultural_landscape_management",
            "Agricultural Landscape Management",
            "type_2",
        ),
        (
            "coastal_landscape_management",
            "Coastal Landscape Management",
            "type_2",
        ),
        (
            "extensive_urban_green_management",
            "Extensive Urban Green Space Management",
            "type_2",
        ),
        (
            "ecosystem_monitoring",
            "Monitoring",
            "type_2",
        ),

        # Type 3
        (
            "intensive_urban_green_management",
            "Intensive Urban Green Space Management",
            "type_3",
        ),
        (
            "urban_planning_strategies",
            "Urban Planning Strategies",
            "type_3",
        ),
        (
            "urban_water_management",
            "Urban Water Management",
            "type_3",
        ),
        (
            "restoration_degraded_terrestrial",
            "Ecological Restoration of Degraded Terrestrial Ecosystems",
            "type_3",
        ),
        (
            "restoration_semi_natural_water",
            "Restoration & Creation of Semi-natural Water Bodies",
            "type_3",
        ),
        (
            "restoration_degraded_marine_coastal",
            "Ecological Restoration of Degraded Coastal & Marine Ecosystems",
            "type_3",
        ),
    ]

    for code, name, intervention_type in values:
        await _upsert_by_code(
            db,
            NbSInterventionType,
            code,
            name,
            name,  # 👈 description = name
            extra_fields={"intervention_type": intervention_type},
        )

# ---------------------------------------------------------
# NbS Societal Challenge Types - taken from D2.2 Table 8
# ---------------------------------------------------------

async def seed_nbs_societal_challenge_types(db: AsyncSession):
    values = [
        ("climate_resilience", "Climate Resilience"),
        ("water_management", "Water Management"),
        ("food_security", "Food Security"),
        ("social_justice_cohesion", "Social Justice and Social Cohesion"),
        ("green_jobs", "New Economic Opportunities and Green Jobs"),
        ("participatory_governance", "Participatory Planning and Governance"),
        ("disaster_risk_reduction", "Natural and Climate Hazards (Disaster Risk Reduction)"),
        ("human_health_wellbeing", "Human Health and Well-being"),
        ("air_quality", "Air Quality"),
        ("green_space_management", "Green Space Management"),
        ("place_regeneration", "Place Regeneration"),
        ("knowledge_capacity_building", "Knowledge and Social Capacity Building for Sustainable Transformation"),
        ("biodiversity_enhancement", "Biodiversity Enhancement"),
    ]

    for code, name in values:
        await _upsert_by_code(
            db,
            NbSSocietalChallengeType,
            code,
            name,
            name,  # description = name
        )

# ---------------------------------------------------------
# Main entry
# ---------------------------------------------------------

async def seed_case_data_lookups(db: AsyncSession):
    await seed_use_of_proceeds_types(db)
    await seed_operator_specialties(db)
    await seed_countries(db)
    await seed_financing_types(db)
    await seed_nbs_types(db)
    await seed_implementation_stages(db)

    await seed_nbs_environment_types(db)
    await seed_nbs_approach_types(db)
    await seed_nbs_intervention_types(db)
    await seed_nbs_societal_challenge_types(db)

    await db.commit()