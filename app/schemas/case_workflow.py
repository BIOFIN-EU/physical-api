from decimal import Decimal
from typing import Optional, Literal, Any

from pydantic import BaseModel, Field, model_validator


class ConsentStepInput(BaseModel):
    disclaimer_acknowledged: bool
    allow_data_sharing: bool


class BasicInfoStepInput(BaseModel):
    name: str
    high_level_description: str

class DetectCountryRequest(BaseModel):
    location_type: Literal["polygon", "point"]
    geometry_wkt: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _validate_geometry_shape(self) -> "DetectCountryRequest":
        if self.location_type == "polygon":
            if not self.geometry_wkt or not self.geometry_wkt.strip():
                raise ValueError(
                    "geometry_wkt is required for a polygon location."
                )
            if self.latitude is not None or self.longitude is not None:
                raise ValueError(
                    "latitude/longitude must not be provided for a polygon location."
                )
        elif self.location_type == "point":
            if self.latitude is None or self.longitude is None:
                raise ValueError(
                    "latitude and longitude are both required for a point location."
                )
            if self.geometry_wkt is not None:
                raise ValueError(
                    "geometry_wkt must not be provided for a point location."
                )

        return self


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
    # Unknown fields are ignored, so a case still on the old step config
    # (which sent nbs_type_id) can be saved.
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

class IntermediaryAssignmentInput(BaseModel):
    intermediary_id: int = Field(..., gt=0)
    intermediary_function_id: int = Field(..., gt=0)


class IntermediaryStepInput(BaseModel):
    # Empty when no intermediary is involved (the step is optional).
    assignments: list[IntermediaryAssignmentInput] = Field(default_factory=list)


class LocationEntryInput(BaseModel):
    friendly_name: Optional[str] = None
    location_type: Literal["polygon", "point"]
    geometry_wkt: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    # Only meaningful for location_type == "point" (manual entry); ignored for polygon.
    area_sqm: Optional[float] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_geometry_shape(self) -> "LocationEntryInput":
        if self.location_type == "polygon":
            if not self.geometry_wkt or not self.geometry_wkt.strip():
                raise ValueError(
                    "geometry_wkt is required for a polygon location."
                )
            if self.latitude is not None or self.longitude is not None:
                raise ValueError(
                    "latitude/longitude must not be provided for a polygon location."
                )
        elif self.location_type == "point":
            if self.latitude is None or self.longitude is None:
                raise ValueError(
                    "latitude and longitude are both required for a point location."
                )
            if self.geometry_wkt is not None:
                raise ValueError(
                    "geometry_wkt must not be provided for a point location."
                )

        return self

class LocationStepInput(BaseModel):
    locations: list[LocationEntryInput] = Field(..., min_length=1)