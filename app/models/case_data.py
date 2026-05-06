from __future__ import annotations
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.core.settings import settings

CASE_DATA_SCHEMA = settings.CASE_DATA_DB_SCHEMA


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CaseUserAccess(Base):
    __tablename__ = "case_user_access"
    __table_args__ = (
        UniqueConstraint("case_id", "user_id", name="uq_case_user_access_case_user"),
        CheckConstraint(
            "case_role IN ('borrower', 'funder', 'intermediary')",
            name="ck_case_user_access_case_role",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    case_role: Mapped[str] = mapped_column(String(50), nullable=False)

    can_view: Mapped[bool] = mapped_column(nullable=False, default=True)
    can_update: Mapped[bool] = mapped_column(nullable=False, default=False)
    can_delete: Mapped[bool] = mapped_column(nullable=False, default=False)
    can_assign_users: Mapped[bool] = mapped_column(nullable=False, default=False)

    is_owner: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class CaseAccessAuditLog(Base):
    __tablename__ = "case_access_audit_logs"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    actor_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    target_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

# ---------------------------------------------------------
# Basic Info
# ---------------------------------------------------------

class CaseBasicInfo(Base):
    __tablename__ = "case_basic_info"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_basic_info_case_id"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    high_level_description: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 1. Location table
# ---------------------------------------------------------

class CaseLocation(Base):
    __tablename__ = "case_locations"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_locations_case_id"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    polygon_wkt: Mapped[str] = mapped_column(Text, nullable=False)

    country_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.countries.id"),
        nullable=False,
    )
    country: Mapped["Country"] = relationship()

    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
# ---------------------------------------------------------
# 2. Financial table
# ---------------------------------------------------------

class CaseFinancial(Base):
    __tablename__ = "case_financials"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_financials_case_id"),
        CheckConstraint(
            "nature_positive_percentage >= 0 AND nature_positive_percentage <= 100",
            name="ck_case_financials_nature_positive_percentage",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    loan_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    use_of_proceeds_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.use_of_proceeds.id"),
        nullable=False,
    )
    use_of_proceeds: Mapped["UseOfProceeds"] = relationship()

    # % of financing that supports nature-positive action
    nature_positive_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 3. identifiers / scheme numbers table
# ---------------------------------------------------------

class CaseIdentifiers(Base):
    __tablename__ = "case_identifiers"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_identifiers_case_id"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    organic_farmer_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    environment_scheme_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subsidy_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    registry_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 4. Operators table
# ---------------------------------------------------------

class Operator(Base):
    __tablename__ = "operators"
    __table_args__ = (
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    operator_specialty_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.operator_specialties.id"), nullable=False
    )
    operator_specialty: Mapped["OperatorSpecialty"] = relationship()
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# Use of proceeds lookup
# ---------------------------------------------------------

class UseOfProceeds(Base):
    __tablename__ = "use_of_proceeds"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=True
    )

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# Operator specialties lookup
# ---------------------------------------------------------

class OperatorSpecialty(Base):
    __tablename__ = "operator_specialties"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=True
    )

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# Documents
# ---------------------------------------------------------


class CaseDocument(Base):
    __tablename__ = "case_documents"
    __table_args__ = (
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    step_code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    upload_token: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="minio")
    bucket_name: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

# ---------------------------------------------------------
# Country
# ---------------------------------------------------------

class Country(Base):
    __tablename__ = "countries"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=True
    )

    code: Mapped[str] = mapped_column(
        String(2), unique=True, nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )



# ---------------------------------------------------------
# 2. Financing Type lookup
# ---------------------------------------------------------

class FinancingType(Base):
    __tablename__ = "financing_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# 3. Financing Type join table (multiselect)
# ---------------------------------------------------------

class CaseFinancingType(Base):
    __tablename__ = "case_financing_types"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "financing_type_id",
            name="uq_case_financing_types_case_financing_type",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    financing_type_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.financing_types.id"),
        nullable=False,
    )
    financing_type: Mapped["FinancingType"] = relationship()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 4. NBS Type lookup
# ---------------------------------------------------------

class NBSType(Base):
    __tablename__ = "nbs_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# 5. Implementation Stage lookup
# ---------------------------------------------------------

class ImplementationStage(Base):
    __tablename__ = "implementation_stages"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# 6. Nature-Based Solution Info
# ---------------------------------------------------------

class CaseNatureBasedSolution(Base):
    __tablename__ = "case_nature_based_solutions"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_nature_based_solutions_case_id"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    nbs_type_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.nbs_types.id"),
        nullable=False,
    )
    nbs_type: Mapped["NBSType"] = relationship()

    implementation_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.implementation_stages.id"),
        nullable=True,
    )
    implementation_stage: Mapped[Optional["ImplementationStage"]] = relationship()

    nbs_environment_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.nbs_environment_types.id"),
        nullable=True,
    )
    nbs_environment_type: Mapped[Optional["NbSEnvironmentType"]] = relationship()

    nbs_approach_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.nbs_approach_types.id"),
        nullable=True,
    )
    nbs_approach_type: Mapped[Optional["NbSApproachType"]] = relationship()

    nbs_intervention_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.nbs_intervention_types.id"),
        nullable=True,
    )
    nbs_intervention_type: Mapped[Optional["NbSInterventionType"]] = relationship()

    nbs_societal_challenge_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.nbs_societal_challenge_types.id"),
        nullable=True,
    )
    nbs_societal_challenge_type: Mapped[Optional["NbSSocietalChallengeType"]] = relationship()

    nbs_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 7. Funding Requirements
# ---------------------------------------------------------

class CaseFundingRequirement(Base):
    __tablename__ = "case_funding_requirements"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_funding_requirements_case_id"),
        CheckConstraint(
            """
            funding_amount IS NULL
            OR direct_funding_amount IS NULL
            OR indirect_funding_amount IS NULL
            OR funding_amount = direct_funding_amount + indirect_funding_amount
            """,
            name="ck_case_funding_requirements_total_matches_breakdown",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    funding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    upfront_costs: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    maintenance_costs: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    direct_funding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    indirect_funding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    funding_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------
# 8. Investment Rationale
# ---------------------------------------------------------

class CaseInvestmentRationale(Base):
    __tablename__ = "case_investment_rationales"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_investment_rationales_case_id"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    nature_positive_benefits: Mapped[str] = mapped_column(Text, nullable=False)
    legislation_compliance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    additional_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

# ---------------------------------------------------------
# 6. NbS Environment Type lookup
# ---------------------------------------------------------

class NbSEnvironmentType(Base):
    __tablename__ = "nbs_environment_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# 7. NbS Approach Type lookup
# ---------------------------------------------------------

class NbSApproachType(Base):
    __tablename__ = "nbs_approach_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# 8. NbS Intervention Type lookup
# ---------------------------------------------------------

class NbSInterventionType(Base):
    __tablename__ = "nbs_intervention_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intervention_type: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------
# 9. NbS Societal Challenge Type lookup
# ---------------------------------------------------------

class NbSSocietalChallengeType(Base):
    __tablename__ = "nbs_societal_challenge_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------
# Intermediaries
# ---------------------------------------------------------
class IntermediaryFunction(Base):
    __tablename__ = "intermediary_functions"
    __table_args__ = (
        CheckConstraint(
            "function_category IN ('financial', 'biodiversity')",
            name="ck_intermediary_functions_function_category",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    function_category: Mapped[str] = mapped_column(String(50), nullable=False)


class Intermediary(Base):
    __tablename__ = "intermediaries"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    functions: Mapped[list["IntermediaryFunctionAssignment"]] = relationship(
        cascade="all, delete-orphan",
        back_populates="intermediary",
    )

    case_intermediaries: Mapped[list["CaseIntermediary"]] = relationship(
        cascade="all, delete-orphan",
        back_populates="intermediary",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CaseIntermediary(Base):
    __tablename__ = "case_intermediaries"

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "intermediary_id",
            "intermediary_function_id",
            name="uq_case_intermediary_function",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    intermediary_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.intermediaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    intermediary_function_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{CASE_DATA_SCHEMA}.intermediary_functions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    intermediary: Mapped["Intermediary"] = relationship()

    intermediary_function: Mapped["IntermediaryFunction"] = relationship()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class IntermediaryFunctionAssignment(Base):
    __tablename__ = "intermediary_function_assignments"
    __table_args__ = (
        UniqueConstraint(
            "intermediary_id",
            "intermediary_function_id",
            name="uq_intermediary_function_assignment",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    intermediary_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.intermediaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    intermediary_function_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.intermediary_functions.id"),
        nullable=False,
    )

    intermediary: Mapped["Intermediary"] = relationship(back_populates="functions")
    intermediary_function: Mapped["IntermediaryFunction"] = relationship()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )