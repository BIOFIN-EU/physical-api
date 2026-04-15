from __future__ import annotations

from datetime import datetime
from typing import Optional

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
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.core.settings import settings

CASE_DATA_SCHEMA = settings.CASE_DATA_DB_SCHEMA


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    case_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "nature_financing"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

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

    case_location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Cross-schema link to workflow case
    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )

    # Store polygon as WKT for now, simple and easy to test
    polygon_wkt: Mapped[str] = mapped_column(Text, nullable=False)

    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
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

    case_financial_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )

    loan_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    use_of_proceeds_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.use_of_proceeds_types.use_of_proceeds_type_id"), nullable=False
    )

    # % of financing that supports nature-positive action
    nature_positive_percentage: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)

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

    case_identifiers_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.case_id", ondelete="CASCADE"),
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

    operator_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    operator_specialty_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.operator_specialties.operator_specialty_id"), nullable=False
    )
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

class UseOfProceedsType(Base):
    __tablename__ = "use_of_proceeds_types"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    use_of_proceeds_type_id: Mapped[int] = mapped_column(
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

    operator_specialty_id: Mapped[int] = mapped_column(
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

    case_document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.case_id", ondelete="CASCADE"),
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