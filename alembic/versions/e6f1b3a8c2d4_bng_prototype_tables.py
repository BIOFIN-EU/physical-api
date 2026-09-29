"""bng prototype tables

Revision ID: e6f1b3a8c2d4
Revises: d9a3f6b82e17
Create Date: 2026-09-29 09:00:00.000000

Biodiversity Net Gain prototype (app.models.bng). Only new bng_* tables in
case_data; no existing table is changed. The reference data is seeded on app
startup (app.core.seed_bng).

The app's startup create_all also creates missing tables, so each table is
only created here if it is not there yet; the allocation trigger is always
(re)created. downgrade() drops exactly these objects.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.bng import (
    ALLOCATION_CAPACITY_FUNCTION_SQL,
    ALLOCATION_CAPACITY_TRIGGER_DROP_SQL,
    ALLOCATION_CAPACITY_TRIGGER_SQL,
)

# revision identifiers, used by Alembic.
revision: str = 'e6f1b3a8c2d4'
down_revision: Union[str, Sequence[str], None] = 'd9a3f6b82e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "case_data"
CATEGORY_CHECK = "category IN ('area', 'hedgerow', 'watercourse')"

TABLES = [
    # created in this order, dropped in reverse
    "bng_habitat_types",
    "bng_conditions",
    "bng_strategic_significance",
    "bng_habitat_parcels",
    "bng_step_data",
    "bng_unit_allocations",
]


def _actor_columns():
    return [
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
    ]


def _timestamps():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _create(name: str) -> None:
    if name == "bng_habitat_types":
        op.create_table(
            name,
            sa.Column('id', sa.SmallInteger(), autoincrement=True, nullable=False),
            sa.Column('code', sa.String(100), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('category', sa.String(20), nullable=False),
            sa.Column('distinctiveness', sa.String(20), nullable=False),
            sa.Column('distinctiveness_score', sa.Numeric(6, 3), nullable=False),
            sa.Column('description', sa.String(500), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code'),
            sa.CheckConstraint(CATEGORY_CHECK, name='ck_bng_habitat_types_category'),
            schema=S,
        )
    elif name in ("bng_conditions", "bng_strategic_significance"):
        op.create_table(
            name,
            sa.Column('id', sa.SmallInteger(), autoincrement=True, nullable=False),
            sa.Column('code', sa.String(50), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('multiplier', sa.Numeric(6, 3), nullable=False),
            sa.Column('description', sa.String(500), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code'),
            schema=S,
        )
    elif name == "bng_habitat_parcels":
        op.create_table(
            name,
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('phase', sa.String(20), nullable=False),
            sa.Column('category', sa.String(20), nullable=False),
            sa.Column('parcel_name', sa.String(255), nullable=True),
            sa.Column('habitat_type_id', sa.SmallInteger(), sa.ForeignKey(f'{S}.bng_habitat_types.id'), nullable=False),
            sa.Column('condition_id', sa.SmallInteger(), sa.ForeignKey(f'{S}.bng_conditions.id'), nullable=False),
            sa.Column('strategic_significance_id', sa.SmallInteger(), sa.ForeignKey(f'{S}.bng_strategic_significance.id'), nullable=False),
            sa.Column('size', sa.Numeric(12, 4), nullable=False),
            sa.Column('units', sa.Numeric(14, 4), nullable=False),
            *_timestamps(),
            *_actor_columns(),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint("phase IN ('baseline', 'proposed')", name='ck_bng_habitat_parcels_phase'),
            sa.CheckConstraint(CATEGORY_CHECK, name='ck_bng_habitat_parcels_category'),
            sa.CheckConstraint('size > 0', name='ck_bng_habitat_parcels_size_positive'),
            sa.CheckConstraint('units >= 0', name='ck_bng_habitat_parcels_units_non_negative'),
            schema=S,
        )
        op.create_index(op.f(f'ix_{S}_bng_habitat_parcels_case_id'), name, ['case_id'], schema=S)
    elif name == "bng_step_data":
        op.create_table(
            name,
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('step_code', sa.String(100), nullable=False),
            sa.Column('data', postgresql.JSONB(), nullable=False),
            *_timestamps(),
            *_actor_columns(),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('case_id', 'step_code', name='uq_bng_step_data_case_step'),
            schema=S,
        )
        op.create_index(op.f(f'ix_{S}_bng_step_data_case_id'), name, ['case_id'], schema=S)
    elif name == "bng_unit_allocations":
        op.create_table(
            name,
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('development_case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('habitat_bank_case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('habitat_units', sa.Numeric(14, 4), nullable=False),
            sa.Column('hedgerow_units', sa.Numeric(14, 4), nullable=False),
            sa.Column('watercourse_units', sa.Numeric(14, 4), nullable=False),
            *_timestamps(),
            *_actor_columns(),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('development_case_id', 'habitat_bank_case_id', name='uq_bng_unit_allocations_development_bank'),
            sa.CheckConstraint('habitat_units >= 0 AND hedgerow_units >= 0 AND watercourse_units >= 0', name='ck_bng_unit_allocations_non_negative'),
            sa.CheckConstraint('habitat_units + hedgerow_units + watercourse_units > 0', name='ck_bng_unit_allocations_not_empty'),
            sa.CheckConstraint('development_case_id <> habitat_bank_case_id', name='ck_bng_unit_allocations_different_cases'),
            schema=S,
        )
        op.create_index(op.f(f'ix_{S}_bng_unit_allocations_development_case_id'), name, ['development_case_id'], schema=S)
        op.create_index(op.f(f'ix_{S}_bng_unit_allocations_habitat_bank_case_id'), name, ['habitat_bank_case_id'], schema=S)


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    for name in TABLES:
        if not inspector.has_table(name, schema=S):
            _create(name)

    op.execute(ALLOCATION_CAPACITY_FUNCTION_SQL)
    op.execute(ALLOCATION_CAPACITY_TRIGGER_DROP_SQL)
    op.execute(ALLOCATION_CAPACITY_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema: drops the BNG prototype tables and their data."""
    op.execute(ALLOCATION_CAPACITY_TRIGGER_DROP_SQL)
    op.execute(f"DROP FUNCTION IF EXISTS {S}.bng_check_allocation_capacity()")
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {S}.{name}")
