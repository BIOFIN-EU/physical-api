from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class HabitatParcelInput(BaseModel):
    parcel_name: Optional[str] = Field(default=None, max_length=255)
    habitat_type_id: int = Field(gt=0)
    condition_id: int = Field(gt=0)
    strategic_significance_id: int = Field(gt=0)
    # hectares for area habitats, km for hedgerows and watercourses
    size: Decimal = Field(gt=0, max_digits=12, decimal_places=4)


class HabitatParcelsStepInput(BaseModel):
    parcels: list[HabitatParcelInput] = Field(..., min_length=1)


class UnitAllocationInput(BaseModel):
    habitat_bank_case_id: int = Field(gt=0)
    habitat_units: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=4)
    hedgerow_units: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=4)
    watercourse_units: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=4)


class UnitAllocationStepInput(BaseModel):
    # Empty when the development meets its target on-site.
    allocations: list[UnitAllocationInput] = Field(default_factory=list)


class HabitatParcelsPreview(BaseModel):
    """Unsaved parcels for one phase, to preview the metric while editing."""

    phase: str = Field(pattern="^(baseline|proposed)$")
    parcels: list[HabitatParcelInput] = Field(default_factory=list)
