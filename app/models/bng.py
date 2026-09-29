"""
Biodiversity Net Gain (BNG) prototype tables. All prefixed bng_ and used only
by the bng_* workflows; no existing table references them.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DDL,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.case_data import CASE_DATA_SCHEMA
from app.models.mixins import ActorStampMixin

BNG_CATEGORIES = ("area", "hedgerow", "watercourse")
BNG_PHASES = ("baseline", "proposed")

# Workflow codes (app/workflow_configs/workflows.json)
BNG_HABITAT_BANK_WORKFLOW = "bng_habitat_bank_v1"
BNG_DEVELOPMENT_WORKFLOW = "bng_development_v1"
BNG_WORKFLOWS = (BNG_HABITAT_BANK_WORKFLOW, BNG_DEVELOPMENT_WORKFLOW)

# Step whose submission records the off-site allocation (see bng_activities).
BNG_ALLOCATION_STEP = "offsite_allocation"

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
    workflows). The bng_unit_allocations_capacity trigger rejects any
    allocation that would take more of a category than the bank's uplift.
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


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
         WHERE habitat_bank_case_id = NEW.habitat_bank_case_id;

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
