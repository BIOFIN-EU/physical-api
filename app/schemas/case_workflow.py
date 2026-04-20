from decimal import Decimal
from typing import Optional, Literal, Dict, Any

from pydantic import BaseModel, Field


class LocationStepInput(BaseModel):
    polygon_wkt: str
    country_id: int
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
    temporal_workflow_id: str
    workflow_code: str
    current_step: Optional[str]
    status: Literal["draft", "in_progress", "completed", "failed"]
    screen: dict[str, Any]