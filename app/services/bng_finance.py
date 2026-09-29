"""
Simple financial model for a habitat bank (diagram step 12): what its units
are worth at its own prices, and how that compares with its delivery cost.
Prices and the delivery cost come from the bank's unit_pricing step.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

CATEGORIES = ("area", "hedgerow", "watercourse")

# unit_pricing step fields
PRICE_FIELDS = {
    "area": "price_per_habitat_unit",
    "hedgerow": "price_per_hedgerow_unit",
    "watercourse": "price_per_watercourse_unit",
}
DELIVERY_COST_FIELD = "delivery_cost"


def _money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def prices_from_step(data: Mapping[str, Any] | None) -> dict[str, Decimal | None]:
    data = data or {}
    return {category: _money(data.get(field)) for category, field in PRICE_FIELDS.items()}


def delivery_cost_from_step(data: Mapping[str, Any] | None) -> Decimal | None:
    return _money((data or {}).get(DELIVERY_COST_FIELD))


def total_price(units: Mapping[str, Decimal], prices: Mapping[str, Decimal | None]) -> Decimal | None:
    """Units x price per category; None when a needed price is missing."""
    total = Decimal(0)
    for category in CATEGORIES:
        amount = units.get(category, Decimal(0))
        if amount <= 0:
            continue
        price = prices.get(category)
        if price is None:
            return None
        total += amount * price
    return total.quantize(Decimal("0.01"))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.01")))


def bank_financials(
    *,
    prices: Mapping[str, Decimal | None],
    delivery_cost: Decimal | None,
    uplift: Mapping[str, Decimal],
    by_status: Mapping[str, Mapping[str, Decimal]],
) -> dict[str, Any]:
    """
    by_status: units per category for each allocation status. Revenue is
    committed once units are allocated or retired, in the pipeline while
    requested or reserved.
    """
    def units(*statuses: str) -> dict[str, Decimal]:
        return {
            category: sum((by_status.get(status, {}).get(category, Decimal(0)) for status in statuses), Decimal(0))
            for category in CATEGORIES
        }

    sellable = {category: max(uplift.get(category, Decimal(0)), Decimal(0)) for category in CATEGORIES}
    potential = total_price(sellable, prices)
    committed = total_price(units("allocated", "retired"), prices)
    pipeline = total_price(units("requested", "reserved"), prices)

    return {
        "prices": {category: _float(price) for category, price in prices.items()},
        "prices_set": all(prices.get(c) is not None for c in CATEGORIES if sellable[c] > 0),
        "delivery_cost": _float(delivery_cost),
        "potential_revenue": _float(potential),
        "committed_revenue": _float(committed),
        "pipeline_revenue": _float(pipeline),
        "potential_margin": _float(potential - delivery_cost) if potential is not None and delivery_cost is not None else None,
    }
