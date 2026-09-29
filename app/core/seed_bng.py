"""
Reference data for the BNG prototype's simplified metric. Seeded on startup
(idempotent, matched by code).

ILLUSTRATIVE ONLY: a short, representative list of habitats with
distinctiveness bands and multipliers modelled on the structure of the
Statutory Biodiversity Metric. It is not the official habitat list or scores.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bng import BngCondition, BngHabitatType, BngStrategicSignificance

DISTINCTIVENESS_SCORES = {
    "very_low": Decimal("0"),
    "low": Decimal("2"),
    "medium": Decimal("4"),
    "high": Decimal("6"),
    "very_high": Decimal("8"),
}

# (code, name, category, distinctiveness, description)
HABITAT_TYPES = [
    # Area habitats (hectares)
    ("area_cropland_cereal", "Cropland – Cereal crops", "area", "low", "Arable fields under cereal crops."),
    ("area_grassland_modified", "Grassland – Modified grassland", "area", "low", "Improved, species-poor grassland such as intensive pasture or amenity grass."),
    ("area_grassland_neutral", "Grassland – Other neutral grassland", "area", "medium", "Semi-improved grassland with a moderate range of grasses and wildflowers."),
    ("area_grassland_lowland_meadow", "Grassland – Lowland meadows", "area", "very_high", "Species-rich hay meadow grassland, a priority habitat."),
    ("area_scrub_mixed", "Heathland and shrub – Mixed scrub", "area", "medium", "Dense stands of mixed native shrubs."),
    ("area_heathland_lowland", "Heathland and shrub – Lowland heathland", "area", "high", "Open heather-dominated habitat on poor, acidic soils."),
    ("area_woodland_broadleaved", "Woodland – Other broadleaved woodland", "area", "medium", "Broadleaved woodland that is not a priority woodland type."),
    ("area_woodland_lowland_mixed", "Woodland – Lowland mixed deciduous woodland", "area", "high", "Native mixed deciduous woodland, a priority habitat."),
    ("area_wetland_reedbed", "Wetland – Reedbeds", "area", "high", "Wetland dominated by common reed."),
    ("area_lakes_pond", "Lakes – Ponds (priority habitat)", "area", "high", "Small permanent or seasonal water bodies of high ecological value."),
    ("area_urban_garden", "Urban – Vegetated garden", "area", "low", "Private gardens with lawns, beds and shrubs."),
    ("area_urban_green_roof", "Urban – Intensive green roof", "area", "low", "Planted roof areas with deep substrate."),
    ("area_urban_sealed", "Urban – Developed land; sealed surface", "area", "very_low", "Buildings, roads and other hard surfaces."),
    # Hedgerows (km)
    ("hedgerow_non_native", "Non-native and ornamental hedgerow", "hedgerow", "very_low", "Hedges of non-native or ornamental species such as leylandii."),
    ("hedgerow_native", "Native hedgerow", "hedgerow", "low", "A line of mainly native shrubs."),
    ("hedgerow_native_with_trees", "Native hedgerow with trees", "hedgerow", "medium", "A native hedgerow with mature standard trees along it."),
    ("hedgerow_species_rich", "Species-rich native hedgerow", "hedgerow", "medium", "A native hedgerow with a wide mix of woody species."),
    ("hedgerow_species_rich_with_trees", "Species-rich native hedgerow with trees", "hedgerow", "high", "A species-rich native hedgerow with mature standard trees."),
    # Watercourses (km)
    ("watercourse_culvert", "Culvert", "watercourse", "very_low", "A watercourse enclosed in a pipe or channel."),
    ("watercourse_ditch", "Ditches", "watercourse", "medium", "Man-made drainage channels that hold water for most of the year."),
    ("watercourse_canal", "Canals", "watercourse", "medium", "Artificial navigable waterways."),
    ("watercourse_other_river", "Other rivers and streams", "watercourse", "high", "Natural rivers and streams that are not priority habitat."),
    ("watercourse_priority_river", "Priority habitat rivers", "watercourse", "very_high", "Rivers of the highest ecological value, such as chalk rivers."),
]

# (code, name, multiplier, description)
CONDITIONS = [
    ("poor", "Poor", Decimal("1"), "Well below what the habitat should look like when healthy."),
    ("fairly_poor", "Fairly poor", Decimal("1.5"), "Between poor and moderate."),
    ("moderate", "Moderate", Decimal("2"), "Some of the features of a healthy habitat, with clear room for improvement."),
    ("fairly_good", "Fairly good", Decimal("2.5"), "Between moderate and good."),
    ("good", "Good", Decimal("3"), "Close to the best example of this habitat."),
]

# (code, name, multiplier, description)
STRATEGIC_SIGNIFICANCE = [
    ("low", "Low", Decimal("1"), "Not identified in any local nature strategy."),
    ("medium", "Medium", Decimal("1.1"), "Ecologically desirable, but not in a local strategy."),
    ("high", "High", Decimal("1.15"), "Formally identified in a local nature recovery strategy or plan."),
]


async def _upsert(db: AsyncSession, model, code: str, values: dict) -> None:
    existing = await db.scalar(select(model).where(model.code == code))
    if existing is None:
        db.add(model(code=code, **values))
        return
    for field, value in values.items():
        setattr(existing, field, value)


async def seed_bng_reference_data(db: AsyncSession) -> None:
    for code, name, category, distinctiveness, description in HABITAT_TYPES:
        await _upsert(db, BngHabitatType, code, {
            "name": name,
            "category": category,
            "distinctiveness": distinctiveness,
            "distinctiveness_score": DISTINCTIVENESS_SCORES[distinctiveness],
            "description": description,
        })

    for code, name, multiplier, description in CONDITIONS:
        await _upsert(db, BngCondition, code, {
            "name": name, "multiplier": multiplier, "description": description,
        })

    for code, name, multiplier, description in STRATEGIC_SIGNIFICANCE:
        await _upsert(db, BngStrategicSignificance, code, {
            "name": name, "multiplier": multiplier, "description": description,
        })

    await db.commit()
