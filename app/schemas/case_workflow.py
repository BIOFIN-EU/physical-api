from decimal import Decimal
from typing import Optional, Literal

from pydantic import BaseModel, Field


class LocationStepInput(BaseModel):
    polygon_wkt: str
    country: Optional[str] = None
    region: Optional[str] = None
    notes: Optional[str] = None


class FinancialStepInput(BaseModel):
    loan_amount: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    currency: str = "EUR"
    use_of_proceeds_id: int
    nature_positive_percentage: Optional[Decimal] = Field(default=None, max_digits=5, decimal_places=2)
    notes: Optional[str] = None


class IdentifiersStepInput(BaseModel):
    organic_farmer_number: Optional[str] = None
    environment_scheme_number: Optional[str] = None
    subsidy_reference: Optional[str] = None
    registry_notes: Optional[str] = None


class WorkflowStateResponse(BaseModel):
    case_id: int
    workflow_id: str
    current_step: Literal["location", "financial", "registration", "completed"]
    status: str
    screen: dict