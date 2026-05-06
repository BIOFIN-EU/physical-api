from decimal import Decimal
from typing import Optional, Literal, Any

from pydantic import BaseModel, Field


class BasicInfoStepInput(BaseModel):
    name: str
    high_level_description: str


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


class FinancingTypeStepInput(BaseModel):
    financing_type_id: int


class NatureBasedSolutionStepInput(BaseModel):
    nbs_type_id: int
    implementation_stage_id: Optional[int] = None
    nbs_environment_type_id: Optional[int] = None
    nbs_approach_type_id: Optional[int] = None
    nbs_intervention_type_id: Optional[int] = None
    nbs_societal_challenge_type_id: Optional[int] = None
    nbs_description: Optional[str] = None


class FundingRequirementsStepInput(BaseModel):
    funding_amount: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    currency: str = "EUR"
    upfront_costs: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    maintenance_costs: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    direct_funding_amount: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    indirect_funding_amount: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    funding_notes: Optional[str] = None


class InvestmentRationaleStepInput(BaseModel):
    nature_positive_benefits: str
    legislation_compliance: Optional[str] = None
    additional_rationale: Optional[str] = None


class WorkflowStateResponse(BaseModel):
    case_id: int
    temporal_workflow_id: str
    workflow_code: str
    current_step: Optional[str]
    status: Literal["draft", "in_progress", "completed", "failed"]
    screen: dict[str, Any]

class IntermediaryStepInput(BaseModel):
    intermediary_id: int = Field(..., gt=0)