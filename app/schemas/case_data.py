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

class UseOfProceedsTypeBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class UseOfProceedsTypeCreate(UseOfProceedsTypeBase):
    pass


class UseOfProceedsTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class UseOfProceedsTypeRead(ORMBaseSchema):
    use_of_proceeds_type_id: int
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
    operator_specialty_id: int
    code: str
    name: str
    description: Optional[str] = None


# ---------------------------------------------------------
# CaseLocation
# ---------------------------------------------------------

class CaseLocationBase(BaseModel):
    case_id: int
    polygon_wkt: str
    country: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CaseLocationCreate(CaseLocationBase):
    pass


class CaseLocationUpdate(BaseModel):
    polygon_wkt: Optional[str] = None
    country: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CaseLocationRead(ORMBaseSchema):
    case_location_id: int
    case_id: int
    polygon_wkt: str
    country: Optional[str] = None
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
    case_financial_id: int
    case_id: int
    loan_amount: Optional[Decimal] = None
    currency: str
    use_of_proceeds_id: int
    nature_positive_percentage: Optional[Decimal] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# CaseRegistration
# ---------------------------------------------------------

class CaseRegistrationBase(BaseModel):
    case_id: int
    organic_farmer_number: Optional[str] = Field(None, max_length=100)
    environment_scheme_number: Optional[str] = Field(None, max_length=100)
    subsidy_reference: Optional[str] = Field(None, max_length=100)
    registry_notes: Optional[str] = None


class CaseRegistrationCreate(CaseRegistrationBase):
    pass


class CaseRegistrationUpdate(BaseModel):
    organic_farmer_number: Optional[str] = Field(None, max_length=100)
    environment_scheme_number: Optional[str] = Field(None, max_length=100)
    subsidy_reference: Optional[str] = Field(None, max_length=100)
    registry_notes: Optional[str] = None


class CaseRegistrationRead(ORMBaseSchema):
    case_registration_id: int
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
    operator_id: int
    case_id: int
    name: str
    operator_specialty_id: int
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime