"""bng marketplace (phase 2)

Revision ID: f2a7c4d91b36
Revises: e6f1b3a8c2d4
Create Date: 2026-09-29 12:00:00.000000

Biodiversity Net Gain prototype, phase 2. Only bng_* objects change:
- bng_unit_allocations gets a lifecycle status (requested / reserved /
  allocated / retired / declined / released), request-time unit prices and
  timestamps. Existing rows (phase 1 allocations) become 'allocated'.
- The capacity trigger counts only active statuses.
- New bng_transactions table (permanent records, cannot be updated).

The app's startup create_all may already have created bng_transactions, so
it is only created here if missing. downgrade() restores the phase 1 state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.bng import (
    ALLOCATION_CAPACITY_FUNCTION_SQL,
    TRANSACTION_IMMUTABLE_FUNCTION_SQL,
    TRANSACTION_IMMUTABLE_TRIGGER_DROP_SQL,
    TRANSACTION_IMMUTABLE_TRIGGER_SQL,
)

# revision identifiers, used by Alembic.
revision: str = 'f2a7c4d91b36'
down_revision: Union[str, Sequence[str], None] = 'e6f1b3a8c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "case_data"
TABLE = "bng_unit_allocations"

NEW_COLUMNS = [
    ("price_per_habitat_unit", sa.Numeric(14, 2)),
    ("price_per_hedgerow_unit", sa.Numeric(14, 2)),
    ("price_per_watercourse_unit", sa.Numeric(14, 2)),
    ("total_price", sa.Numeric(16, 2)),
    ("decided_at", sa.DateTime(timezone=True)),
    ("allocated_at", sa.DateTime(timezone=True)),
    ("retired_at", sa.DateTime(timezone=True)),
    ("released_at", sa.DateTime(timezone=True)),
]

# The phase 1 capacity function (counted every allocation row), for downgrade.
PHASE_1_CAPACITY_FUNCTION_SQL = ALLOCATION_CAPACITY_FUNCTION_SQL.replace(
    "\n           AND status IN ('requested', 'reserved', 'allocated', 'retired');", ";"
)
assert PHASE_1_CAPACITY_FUNCTION_SQL != ALLOCATION_CAPACITY_FUNCTION_SQL


def upgrade() -> None:
    """Upgrade schema."""
    # status: existing rows were confirmed allocations; new ones start requested
    op.add_column(TABLE, sa.Column('status', sa.String(20), nullable=True), schema=S)
    op.execute(f"UPDATE {S}.{TABLE} SET status = 'allocated'")
    op.alter_column(TABLE, 'status', nullable=False, server_default='requested', schema=S)
    op.create_check_constraint(
        "ck_bng_unit_allocations_status",
        TABLE,
        "status IN ('requested', 'reserved', 'allocated', 'retired', 'declined', 'released')",
        schema=S,
    )
    for name, type_ in NEW_COLUMNS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True), schema=S)
    op.execute(f"UPDATE {S}.{TABLE} SET allocated_at = updated_at")

    op.execute(ALLOCATION_CAPACITY_FUNCTION_SQL)

    if not sa.inspect(op.get_bind()).has_table("bng_transactions", schema=S):
        op.create_table(
            "bng_transactions",
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('reference', sa.String(40), nullable=False),
            sa.Column('allocation_id', sa.Integer(), sa.ForeignKey(f'{S}.{TABLE}.id', ondelete='CASCADE'), nullable=False),
            sa.Column('development_case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('habitat_bank_case_id', sa.Integer(), sa.ForeignKey(f'{S}.cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('habitat_units', sa.Numeric(14, 4), nullable=False),
            sa.Column('hedgerow_units', sa.Numeric(14, 4), nullable=False),
            sa.Column('watercourse_units', sa.Numeric(14, 4), nullable=False),
            sa.Column('total_price', sa.Numeric(16, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('reference'),
            sa.UniqueConstraint('allocation_id'),
            schema=S,
        )
        op.create_index(op.f(f'ix_{S}_bng_transactions_development_case_id'), 'bng_transactions', ['development_case_id'], schema=S)
        op.create_index(op.f(f'ix_{S}_bng_transactions_habitat_bank_case_id'), 'bng_transactions', ['habitat_bank_case_id'], schema=S)

    op.execute(TRANSACTION_IMMUTABLE_FUNCTION_SQL)
    op.execute(TRANSACTION_IMMUTABLE_TRIGGER_DROP_SQL)
    op.execute(TRANSACTION_IMMUTABLE_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema: back to phase 1 (drops transaction records and statuses)."""
    op.execute(TRANSACTION_IMMUTABLE_TRIGGER_DROP_SQL)
    op.execute(f"DROP FUNCTION IF EXISTS {S}.bng_transactions_immutable()")
    op.execute(f"DROP TABLE IF EXISTS {S}.bng_transactions")

    # Phase 1 had no statuses: keep only the allocations that still hold units.
    op.execute(f"DELETE FROM {S}.{TABLE} WHERE status IN ('declined', 'released')")
    op.execute(PHASE_1_CAPACITY_FUNCTION_SQL)

    for name, _ in reversed(NEW_COLUMNS):
        op.drop_column(TABLE, name, schema=S)
    op.drop_constraint("ck_bng_unit_allocations_status", TABLE, type_="check", schema=S)
    op.drop_column(TABLE, 'status', schema=S)
