from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------
# Shared base
# ---------------------------------------------------------

class ORMBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------

class UseOfProceedsBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class UseOfProceedsCreate(UseOfProceedsBase):
    pass


class UseOfProceedsUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class UseOfProceedsRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class OperatorSpecialtyBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class OperatorSpecialtyCreate(OperatorSpecialtyBase):
    pass


class OperatorSpecialtyUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class OperatorSpecialtyRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class CountryBase(BaseModel):
    code: str = Field(..., max_length=2)
    name: str = Field(..., max_length=100)


class CountryCreate(CountryBase):
    pass


class CountryUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=2)
    name: Optional[str] = Field(None, max_length=100)


class CountryRead(ORMBaseSchema):
    id: int
    code: str
    name: str


class FinancingTypeBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class FinancingTypeCreate(FinancingTypeBase):
    pass


class FinancingTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class FinancingTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class NBSTypeBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class NBSTypeCreate(NBSTypeBase):
    pass


class NBSTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class NBSTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class ImplementationStageBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class ImplementationStageCreate(ImplementationStageBase):
    pass


class ImplementationStageUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class ImplementationStageRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class NbSEnvironmentTypeBase(BaseModel):
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None


class NbSEnvironmentTypeCreate(NbSEnvironmentTypeBase):
    pass


class NbSEnvironmentTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class NbSEnvironmentTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class NbSApproachTypeBase(BaseModel):
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None


class NbSApproachTypeCreate(NbSApproachTypeBase):
    pass


class NbSApproachTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class NbSApproachTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


class NbSInterventionTypeBase(BaseModel):
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    intervention_type: str = Field(..., max_length=50)


class NbSInterventionTypeCreate(NbSInterventionTypeBase):
    pass


class NbSInterventionTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    intervention_type: Optional[str] = Field(None, max_length=50)


class NbSInterventionTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    intervention_type: str


class NbSSocietalChallengeTypeBase(BaseModel):
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None


class NbSSocietalChallengeTypeCreate(NbSSocietalChallengeTypeBase):
    pass


class NbSSocietalChallengeTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class NbSSocietalChallengeTypeRead(ORMBaseSchema):
    id: int
    code: str
    name: str
    description: Optional[str] = None


# ---------------------------------------------------------
# CaseBasicInfo
# ---------------------------------------------------------

class CaseBasicInfoBase(BaseModel):
    case_id: int
    name: str = Field(..., max_length=255)
    high_level_description: str


class CaseBasicInfoCreate(CaseBasicInfoBase):
    pass


class CaseBasicInfoUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    high_level_description: Optional[str] = None


class CaseBasicInfoRead(ORMBaseSchema):
    id: int
    case_id: int
    name: str
    high_level_description: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseLocation
# ---------------------------------------------------------

class CaseLocationBase(BaseModel):
    case_id: int
    polygon_wkt: str
    country_id: int
    region: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CaseLocationCreate(CaseLocationBase):
    pass


class CaseLocationUpdate(BaseModel):
    polygon_wkt: Optional[str] = None
    country_id: Optional[int] = None
    region: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CaseLocationRead(ORMBaseSchema):
    id: int
    case_id: int
    polygon_wkt: str
    country_id: int
    country_name: Optional[str] = None
    region: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseFinancial
# ---------------------------------------------------------

class CaseFinancialBase(BaseModel):
    case_id: int
    loan_amount: Optional[Decimal] = None
    currency: str = Field(default="EUR", max_length=3)
    use_of_proceeds_id: int
    nature_positive_percentage: Optional[Decimal] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None


class CaseFinancialCreate(CaseFinancialBase):
    pass


class CaseFinancialUpdate(BaseModel):
    loan_amount: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=3)
    use_of_proceeds_id: Optional[int] = None
    nature_positive_percentage: Optional[Decimal] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None


class CaseFinancialRead(ORMBaseSchema):
    id: int
    case_id: int
    loan_amount: Optional[Decimal] = None
    currency: str
    use_of_proceeds_id: int
    use_of_proceeds_name: Optional[str] = None
    nature_positive_percentage: Optional[Decimal] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseRegistration
# ---------------------------------------------------------

class CaseIdentifiersBase(BaseModel):
    case_id: int
    organic_farmer_number: Optional[str] = Field(None, max_length=100)
    environment_scheme_number: Optional[str] = Field(None, max_length=100)
    subsidy_reference: Optional[str] = Field(None, max_length=100)
    registry_notes: Optional[str] = None


class CaseIdentifiersCreate(CaseIdentifiersBase):
    pass


class CaseIdentifiersUpdate(BaseModel):
    organic_farmer_number: Optional[str] = Field(None, max_length=100)
    environment_scheme_number: Optional[str] = Field(None, max_length=100)
    subsidy_reference: Optional[str] = Field(None, max_length=100)
    registry_notes: Optional[str] = None


class CaseIdentifiersRead(ORMBaseSchema):
    id: int
    case_id: int
    organic_farmer_number: Optional[str] = None
    environment_scheme_number: Optional[str] = None
    subsidy_reference: Optional[str] = None
    registry_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Operator
# ---------------------------------------------------------

class OperatorBase(BaseModel):
    case_id: int
    name: str = Field(..., max_length=255)
    operator_specialty_id: int
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class OperatorCreate(OperatorBase):
    pass


class OperatorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    operator_specialty_id: Optional[int] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class OperatorRead(ORMBaseSchema):
    id: int
    case_id: int
    name: str
    operator_specialty_id: int
    operator_specialty_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseFinancingType
# ---------------------------------------------------------

class CaseFinancingTypeBase(BaseModel):
    case_id: int
    financing_type_id: int


class CaseFinancingTypeCreate(CaseFinancingTypeBase):
    pass


class CaseFinancingTypeUpdate(BaseModel):
    financing_type_id: Optional[int] = None


class CaseFinancingTypeRead(ORMBaseSchema):
    id: int
    case_id: int
    financing_type_id: int
    financing_type_name: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------
# CaseNatureBasedSolution
# ---------------------------------------------------------

class CaseNatureBasedSolutionBase(BaseModel):
    case_id: int
    nbs_type_id: int
    implementation_stage_id: Optional[int] = None
    nbs_environment_type_id: Optional[int] = None
    nbs_approach_type_id: Optional[int] = None
    nbs_intervention_type_id: Optional[int] = None
    nbs_societal_challenge_type_id: Optional[int] = None
    nbs_description: Optional[str] = None


class CaseNatureBasedSolutionCreate(CaseNatureBasedSolutionBase):
    pass


class CaseNatureBasedSolutionUpdate(BaseModel):
    nbs_type_id: Optional[int] = None
    implementation_stage_id: Optional[int] = None
    nbs_environment_type_id: Optional[int] = None
    nbs_approach_type_id: Optional[int] = None
    nbs_intervention_type_id: Optional[int] = None
    nbs_societal_challenge_type_id: Optional[int] = None
    nbs_description: Optional[str] = None


class CaseNatureBasedSolutionRead(ORMBaseSchema):
    id: int
    case_id: int
    nbs_type_id: int
    nbs_type_name: Optional[str] = None
    implementation_stage_id: Optional[int] = None
    implementation_stage_name: Optional[str] = None
    nbs_environment_type_id: Optional[int] = None
    nbs_environment_type_name: Optional[str] = None
    nbs_approach_type_id: Optional[int] = None
    nbs_approach_type_name: Optional[str] = None
    nbs_intervention_type_id: Optional[int] = None
    nbs_intervention_type_name: Optional[str] = None
    nbs_societal_challenge_type_id: Optional[int] = None
    nbs_societal_challenge_type_name: Optional[str] = None
    nbs_description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseFundingRequirement
# ---------------------------------------------------------

class CaseFundingRequirementBase(BaseModel):
    case_id: int
    funding_amount: Optional[Decimal] = None
    currency: str = Field(default="EUR", max_length=3)
    upfront_costs: Optional[Decimal] = None
    maintenance_costs: Optional[Decimal] = None
    direct_funding_amount: Optional[Decimal] = None
    indirect_funding_amount: Optional[Decimal] = None
    funding_notes: Optional[str] = None


class CaseFundingRequirementCreate(CaseFundingRequirementBase):
    pass


class CaseFundingRequirementUpdate(BaseModel):
    funding_amount: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=3)
    upfront_costs: Optional[Decimal] = None
    maintenance_costs: Optional[Decimal] = None
    direct_funding_amount: Optional[Decimal] = None
    indirect_funding_amount: Optional[Decimal] = None
    funding_notes: Optional[str] = None


class CaseFundingRequirementRead(ORMBaseSchema):
    id: int
    case_id: int
    funding_amount: Optional[Decimal] = None
    currency: str
    upfront_costs: Optional[Decimal] = None
    maintenance_costs: Optional[Decimal] = None
    direct_funding_amount: Optional[Decimal] = None
    indirect_funding_amount: Optional[Decimal] = None
    funding_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseInvestmentRationale
# ---------------------------------------------------------

class CaseInvestmentRationaleBase(BaseModel):
    case_id: int
    nature_positive_benefits: str
    legislation_compliance: Optional[str] = None
    additional_rationale: Optional[str] = None


class CaseInvestmentRationaleCreate(CaseInvestmentRationaleBase):
    pass


class CaseInvestmentRationaleUpdate(BaseModel):
    nature_positive_benefits: Optional[str] = None
    legislation_compliance: Optional[str] = None
    additional_rationale: Optional[str] = None


class CaseInvestmentRationaleRead(ORMBaseSchema):
    id: int
    case_id: int
    nature_positive_benefits: str
    legislation_compliance: Optional[str] = None
    additional_rationale: Optional[str] = None
    created_at: datetime
    updated_at: datetime