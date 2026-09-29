"""
Simplified biodiversity metric for the BNG prototype.

Follows the shape of the Statutory Biodiversity Metric, but is NOT it:

    units = size x distinctiveness score x condition x strategic significance

computed separately for area habitats (size in hectares), hedgerows and
watercourses (size in km). The statutory metric's difficulty, temporal and
spatial-risk multipliers and its trading rules are left out.

The net gain target is 10% for each category separately, as in BNG.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CATEGORIES = ("area", "hedgerow", "watercourse")
NET_GAIN_TARGET = Decimal("0.10")
_FOUR_PLACES = Decimal("0.0001")


def parcel_units(
    size: Decimal,
    distinctiveness_score: Decimal,
    condition_multiplier: Decimal,
    significance_multiplier: Decimal,
) -> Decimal:
    units = size * distinctiveness_score * condition_multiplier * significance_multiplier
    return units.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ParcelUnits:
    phase: str  # "baseline" or "proposed"
    category: str
    units: Decimal


def _round(value: Decimal) -> float:
    return float(value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP))


def summarise(
    parcels: Iterable[ParcelUnits],
    *,
    role: str,
    allocated: dict[str, Decimal] | None = None,
) -> dict:
    """
    Per-category totals for a case.

    role "habitat_bank": the uplift (proposed - baseline) is what the bank can
    sell; `allocated` is what developments have already taken.

    role "development": the target is baseline x 1.10; any on-site shortfall
    must be met with off-site units, of which `allocated` are secured.
    """
    allocated = allocated or {}
    baseline = {c: Decimal(0) for c in CATEGORIES}
    proposed = {c: Decimal(0) for c in CATEGORIES}

    for parcel in parcels:
        bucket = baseline if parcel.phase == "baseline" else proposed
        bucket[parcel.category] += parcel.units

    categories = []
    for category in CATEGORIES:
        base = baseline[category]
        prop = proposed[category]
        change = prop - base
        taken = allocated.get(category, Decimal(0))

        entry = {
            "category": category,
            "baseline_units": _round(base),
            "proposed_units": _round(prop),
            "change_units": _round(change),
            # None when there is no baseline to compare against
            "change_percent": _round(change / base * 100) if base > 0 else None,
            "allocated_units": _round(taken),
        }

        if role == "habitat_bank":
            uplift = max(change, Decimal(0))
            entry["available_units"] = _round(max(uplift - taken, Decimal(0)))
        else:
            target = base * (1 + NET_GAIN_TARGET)
            shortfall = max(target - prop, Decimal(0))
            remaining = max(shortfall - taken, Decimal(0))
            entry["target_units"] = _round(target)
            entry["onsite_shortfall_units"] = _round(shortfall)
            entry["remaining_shortfall_units"] = _round(remaining)
            entry["meets_target"] = remaining == 0

        categories.append(entry)

    summary = {
        "role": role,
        "net_gain_target_percent": float(NET_GAIN_TARGET * 100),
        "categories": categories,
    }
    if role == "development":
        summary["meets_target"] = all(c["meets_target"] for c in categories)
        summary["onsite_meets_target"] = all(c["onsite_shortfall_units"] == 0 for c in categories)

    return summary
