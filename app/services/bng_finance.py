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


# ---------------------------------------------------------
# Revenue split (Phase 3, diagram step 31)
# ---------------------------------------------------------

# unit_pricing step fields: each party's percentage of every sale.
SHARE_FIELDS = {
    "landowner": "landowner_share_percent",
    "investor": "investor_share_percent",
    "manager": "manager_share_percent",
}


def shares_from_step(data: Mapping[str, Any] | None) -> dict[str, Decimal] | None:
    """The bank's revenue split, or None when it hasn't been set."""
    data = data or {}
    shares = {party: _money(data.get(field)) for party, field in SHARE_FIELDS.items()}
    if any(share is None for share in shares.values()):
        return None
    return shares


def shares_error(data: Mapping[str, Any] | None) -> str | None:
    """Why the submitted split is invalid, or None."""
    data = data or {}
    values = [data.get(field) for field in SHARE_FIELDS.values()]
    if all(value in (None, "") for value in values):
        return None
    shares = shares_from_step(data)
    if shares is None or any(share > 100 for share in shares.values()):
        return "Enter a percentage from 0 to 100 for each party."
    if sum(shares.values()) != Decimal(100):
        return f"The shares add up to {sum(shares.values()):g}%; they must add up to 100%."
    return None


def split(total: Decimal | None, shares: Mapping[str, Decimal] | None) -> dict[str, float] | None:
    if total is None or shares is None:
        return None
    return {party: _float(total * share / 100) for party, share in shares.items()}


def revenue_distribution(
    transactions: list[tuple[Decimal | None, Mapping[str, Decimal] | None]],
) -> dict[str, Any]:
    """
    (total_price, shares at the time of sale) per transaction: what each
    party has earned from retired units.
    """
    earned = {party: Decimal(0) for party in SHARE_FIELDS}
    revenue = Decimal(0)
    unsplit = Decimal(0)
    for total, shares in transactions:
        if total is None:
            continue
        revenue += total
        if shares is None:
            unsplit += total
            continue
        for party, share in shares.items():
            earned[party] += total * share / 100
    return {
        "retired_revenue": _float(revenue),
        "distributed": {party: _float(amount) for party, amount in earned.items()},
        "not_split": _float(unsplit),
    }
