"""
Biodiversity Net Gain (BNG) prototype tables. All prefixed bng_ and used only
by the bng_* workflows; no existing table references them.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.case_data import CASE_DATA_SCHEMA
from app.models.mixins import ActorStampMixin

BNG_CATEGORIES = ("area", "hedgerow", "watercourse")
# How each category is shown: its name, the unit its size is measured in
# (area habitats in hectares, hedgerows and watercourses in km) and the name
# of its biodiversity units.
BNG_CATEGORY_LABELS = {"area": "Area habitats", "hedgerow": "Hedgerows", "watercourse": "Watercourses"}
BNG_SIZE_UNITS = {"area": "ha", "hedgerow": "km", "watercourse": "km"}
BNG_UNIT_NAMES = {"area": "habitat units", "hedgerow": "hedgerow units", "watercourse": "watercourse units"}
BNG_PHASES = ("baseline", "proposed")

# Workflow codes (app/workflow_configs/workflows.json)
BNG_HABITAT_BANK_WORKFLOW = "bng_habitat_bank_v1"
BNG_DEVELOPMENT_WORKFLOW = "bng_development_v1"
BNG_WORKFLOWS = (BNG_HABITAT_BANK_WORKFLOW, BNG_DEVELOPMENT_WORKFLOW)

# Step whose submission records the off-site allocation (see bng_activities).
BNG_ALLOCATION_STEP = "offsite_allocation"
# Habitat bank step holding its unit prices and delivery cost.
BNG_PRICING_STEP = "unit_pricing"

# Unit lifecycle of an allocation (Phase 2 marketplace):
#   requested -> reserved (bank accepts) -> allocated (planning permission)
#   -> retired (gain plan approved; a transaction record is created).
#   declined (bank) and released (developer) free the units again.
ALLOCATION_STATUSES = ("requested", "reserved", "allocated", "retired", "declined", "released")
ALLOCATION_STATUS_LABELS = {status: status.capitalize() for status in ALLOCATION_STATUSES}
# Statuses that hold a habitat bank's units.
ACTIVE_ALLOCATION_STATUSES = ("requested", "reserved", "allocated", "retired")
# Accepted by the habitat bank: counted as secured for the development.
ACCEPTED_ALLOCATION_STATUSES = ("reserved", "allocated", "retired")
# Can no longer be changed or released.
LOCKED_ALLOCATION_STATUSES = ("allocated", "retired")

# A development's reserved units become allocated once its planning
# permission is granted (step 14): when that step is saved, or when a bank
# accepts a request after it was saved.
PLANNING_PERMISSION_STEP = "planning_permission"
PERMISSION_GRANTED = ("Granted", "Granted with conditions")

# How a step was signed off (case_step_signoffs.decision).
SIGNOFF_DECISIONS = ("submitted", "approved", "rejected", "edited")
SIGNOFF_DECISION_LABELS = {"submitted": "Completed", "approved": "Approved", "rejected": "Rejected", "edited": "Edited"}

# Monitoring (diagram steps 27-32): reports due this many years after the
# habitat bank is registered.
MONITORING_YEARS = (1, 2, 5, 10, 15, 20, 25, 30)
MONITORING_STATUSES = ("due", "submitted", "passed", "failed", "remediated")
MONITORING_STATUS_LABELS = {
    "due": "Due",
    "submitted": "Awaiting verification",
    "passed": "Passed",
    "failed": "Failed",
    "remediated": "Remediated",
}
REMEDIAL_STATUSES = ("open", "completed")
# Roles that verify monitoring reports, and that submit them (and complete
# remedial actions) for the habitat bank.
VERIFIER_ROLES = ("ecologist", "lpa")
MONITORING_BANK_ROLES = ("landowner",)

# BNG roles that decide on a unit allocation request, per side: the habitat
# bank accepts or declines it, the development releases it.
ALLOCATION_DECIDING_ROLES = {
    "habitat_bank": ("landowner", "investor"),
    "development": ("developer",),
}

# Revenue split (unit_pricing step): share of each transaction per party.
REVENUE_SHARE_FIELDS = {
    "landowner": "landowner_share_percent",
    "investor": "investor_share_percent",
    "manager": "manager_share_percent",
}
REVENUE_PARTY_LABELS = {"landowner": "Landowner", "investor": "Investor", "manager": "Habitat manager"}

_CATEGORY_CHECK = "category IN ('area', 'hedgerow', 'watercourse')"


# ---------------------------------------------------------
# Reference data (seeded by app.core.seed_bng)
# ---------------------------------------------------------

class BngHabitatType(Base):
    """A habitat that can be recorded on a parcel, with its distinctiveness."""

    __tablename__ = "bng_habitat_types"
    __table_args__ = (
        CheckConstraint(_CATEGORY_CHECK, name="ck_bng_habitat_types_category"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # area habitats are measured in hectares, hedgerows and watercourses in km
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    distinctiveness: Mapped[str] = mapped_column(String(20), nullable=False)
    distinctiveness_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class BngCondition(Base):
    __tablename__ = "bng_conditions"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class BngStrategicSignificance(Base):
    __tablename__ = "bng_strategic_significance"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


# ---------------------------------------------------------
# Case data
# ---------------------------------------------------------

class BngHabitatParcel(ActorStampMixin, Base):
    """
    One habitat parcel of a BNG case, either before (baseline) or after
    (proposed) the works. `units` is the simplified metric result, computed
    when the parcel is saved (app.services.bng_metric).
    """

    __tablename__ = "bng_habitat_parcels"
    __table_args__ = (
        CheckConstraint("phase IN ('baseline', 'proposed')", name="ck_bng_habitat_parcels_phase"),
        CheckConstraint(_CATEGORY_CHECK, name="ck_bng_habitat_parcels_category"),
        CheckConstraint("size > 0", name="ck_bng_habitat_parcels_size_positive"),
        CheckConstraint("units >= 0", name="ck_bng_habitat_parcels_units_non_negative"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    # Copied from the habitat type so totals per category need no join.
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    parcel_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    habitat_type_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.bng_habitat_types.id"), nullable=False
    )
    condition_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.bng_conditions.id"), nullable=False
    )
    strategic_significance_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.bng_strategic_significance.id"), nullable=False
    )
    # hectares for area habitats, kilometres for hedgerows and watercourses
    size: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    habitat_type: Mapped[BngHabitatType] = relationship()
    condition: Mapped[BngCondition] = relationship()
    strategic_significance: Mapped[BngStrategicSignificance] = relationship()


class BngStepData(ActorStampMixin, Base):
    """Answers of a BNG form step, stored as submitted (one row per step)."""

    __tablename__ = "bng_step_data"
    __table_args__ = (
        UniqueConstraint("case_id", "step_code", name="uq_bng_step_data_case_step"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_code: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BngUnitAllocation(ActorStampMixin, Base):
    """
    Units a development takes from a habitat bank (the link between the two
    workflows), with their lifecycle status (ALLOCATION_STATUSES) and the
    unit prices at the time of the request. Rows are never deleted, so the
    history stays. The bng_unit_allocations_capacity trigger rejects any
    active allocation that would take more of a category than the bank's
    uplift.
    """

    __tablename__ = "bng_unit_allocations"
    __table_args__ = (
        UniqueConstraint(
            "development_case_id", "habitat_bank_case_id",
            name="uq_bng_unit_allocations_development_bank",
        ),
        CheckConstraint(
            "habitat_units >= 0 AND hedgerow_units >= 0 AND watercourse_units >= 0",
            name="ck_bng_unit_allocations_non_negative",
        ),
        CheckConstraint(
            "habitat_units + hedgerow_units + watercourse_units > 0",
            name="ck_bng_unit_allocations_not_empty",
        ),
        CheckConstraint(
            "development_case_id <> habitat_bank_case_id",
            name="ck_bng_unit_allocations_different_cases",
        ),
        CheckConstraint(
            "status IN ('requested', 'reserved', 'allocated', 'retired', 'declined', 'released')",
            name="ck_bng_unit_allocations_status",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    development_case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    habitat_bank_case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    habitat_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    hedgerow_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    watercourse_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    # Price per unit when requested (from the bank's unit_pricing step).
    price_per_habitat_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    price_per_hedgerow_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    price_per_watercourse_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)

    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    allocated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BngTransaction(ActorStampMixin, Base):
    """
    Permanent record of units retired for a development's biodiversity gain
    plan (diagram step 17), one per retired allocation. Its reference goes on
    the gain plan. The bng_transactions_immutable trigger stops changes.
    """

    __tablename__ = "bng_transactions"
    __table_args__ = {"schema": CASE_DATA_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    allocation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.bng_unit_allocations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    development_case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    habitat_bank_case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    habitat_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    hedgerow_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    watercourse_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)
    # Revenue split of the bank when the transaction was made (percent).
    landowner_share_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    investor_share_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    manager_share_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Roles and sign-offs: app.models.case_data (CaseWorkflowRole,
# CaseStepSignoff), shared by every workflow.

# ---------------------------------------------------------
# Monitoring, verification and remedial actions (Phase 3)
# ---------------------------------------------------------

class BngMonitoringReport(ActorStampMixin, Base):
    """
    A monitoring report of a registered habitat bank (diagram steps 27-28),
    due in one of MONITORING_YEARS, submitted by the bank and verified by an
    ecologist or the LPA (step 29).
    """

    __tablename__ = "bng_monitoring_reports"
    __table_args__ = (
        UniqueConstraint("habitat_bank_case_id", "year", name="uq_bng_monitoring_reports_bank_year"),
        CheckConstraint(
            "status IN ('due', 'submitted', 'passed', 'failed', 'remediated')",
            name="ck_bng_monitoring_reports_status",
        ),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    habitat_bank_case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="due")

    # Submitted by the habitat bank
    habitats_on_track: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    condition_summary: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    management_carried_out: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    submitted_on_behalf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Verified by an ecologist or the LPA
    verification_notes: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    verified_as: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    verified_on_behalf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    remedial_actions: Mapped[list["BngRemedialAction"]] = relationship(
        back_populates="report", order_by="BngRemedialAction.id", cascade="all, delete-orphan"
    )


class BngRemedialAction(ActorStampMixin, Base):
    """Work required after a failed monitoring report (diagram step 30)."""

    __tablename__ = "bng_remedial_actions"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'completed')", name="ck_bng_remedial_actions_status"),
        {"schema": CASE_DATA_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.bng_monitoring_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(4000), nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    completion_notes: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    report: Mapped[BngMonitoringReport] = relationship(back_populates="remedial_actions")


# ---------------------------------------------------------
# Allocation capacity trigger
# ---------------------------------------------------------

# Shared with the migration, so databases built from the models (tests) and
# from Alembic get the same trigger.
ALLOCATION_CAPACITY_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {CASE_DATA_SCHEMA}.bng_check_allocation_capacity()
RETURNS trigger AS $$
DECLARE
    category_name text;
    allocated numeric;
    available numeric;
BEGIN
    -- Serialise allocations against the same habitat bank.
    PERFORM 1 FROM {CASE_DATA_SCHEMA}.cases WHERE id = NEW.habitat_bank_case_id FOR UPDATE;

    FOREACH category_name IN ARRAY ARRAY['area', 'hedgerow', 'watercourse'] LOOP
        SELECT COALESCE(SUM(CASE category_name
                    WHEN 'area' THEN habitat_units
                    WHEN 'hedgerow' THEN hedgerow_units
                    ELSE watercourse_units END), 0)
          INTO allocated
          FROM {CASE_DATA_SCHEMA}.bng_unit_allocations
         WHERE habitat_bank_case_id = NEW.habitat_bank_case_id
           AND status IN ('requested', 'reserved', 'allocated', 'retired');

        SELECT GREATEST(COALESCE(SUM(CASE phase WHEN 'proposed' THEN units ELSE -units END), 0), 0)
          INTO available
          FROM {CASE_DATA_SCHEMA}.bng_habitat_parcels
         WHERE case_id = NEW.habitat_bank_case_id AND category = category_name;

        IF allocated > available THEN
            RAISE EXCEPTION 'bng_allocation_exceeds_capacity: % % units requested from habitat bank %, only % available',
                round(allocated, 2), category_name, NEW.habitat_bank_case_id, round(available, 2)
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# One statement each: asyncpg (app startup) runs a single command at a time.
ALLOCATION_CAPACITY_TRIGGER_DROP_SQL = (
    f"DROP TRIGGER IF EXISTS bng_unit_allocations_capacity "
    f"ON {CASE_DATA_SCHEMA}.bng_unit_allocations"
)
ALLOCATION_CAPACITY_TRIGGER_SQL = f"""
CREATE TRIGGER bng_unit_allocations_capacity
    AFTER INSERT OR UPDATE ON {CASE_DATA_SCHEMA}.bng_unit_allocations
    FOR EACH ROW EXECUTE FUNCTION {CASE_DATA_SCHEMA}.bng_check_allocation_capacity()
"""

# DDL() applies Python %-formatting to its statement, so the function's own
# % placeholders (RAISE EXCEPTION) are escaped here.
event.listen(
    BngUnitAllocation.__table__,
    "after_create",
    DDL(ALLOCATION_CAPACITY_FUNCTION_SQL.replace("%", "%%")),
)
event.listen(BngUnitAllocation.__table__, "after_create", DDL(ALLOCATION_CAPACITY_TRIGGER_DROP_SQL))
event.listen(BngUnitAllocation.__table__, "after_create", DDL(ALLOCATION_CAPACITY_TRIGGER_SQL))


# ---------------------------------------------------------
# Transaction records cannot be changed
# ---------------------------------------------------------

TRANSACTION_IMMUTABLE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {CASE_DATA_SCHEMA}.bng_transactions_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'bng_transaction_immutable: transaction records cannot be changed'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRANSACTION_IMMUTABLE_TRIGGER_DROP_SQL = (
    f"DROP TRIGGER IF EXISTS bng_transactions_immutable ON {CASE_DATA_SCHEMA}.bng_transactions"
)
TRANSACTION_IMMUTABLE_TRIGGER_SQL = f"""
CREATE TRIGGER bng_transactions_immutable
    BEFORE UPDATE ON {CASE_DATA_SCHEMA}.bng_transactions
    FOR EACH ROW EXECUTE FUNCTION {CASE_DATA_SCHEMA}.bng_transactions_immutable()
"""

event.listen(BngTransaction.__table__, "after_create", DDL(TRANSACTION_IMMUTABLE_FUNCTION_SQL))
event.listen(BngTransaction.__table__, "after_create", DDL(TRANSACTION_IMMUTABLE_TRIGGER_DROP_SQL))
event.listen(BngTransaction.__table__, "after_create", DDL(TRANSACTION_IMMUTABLE_TRIGGER_SQL))
