"""add currencies table

Revision ID: 7c1e6a2f9b03
Revises: 2b7fa891d4e6
Create Date: 2026-09-22 14:00:00.000000

Adds case_data.currencies, a lookup table of European currencies used to
populate the "Currency" dropdown on the financial/funding_requirements
steps. The referencing columns (CaseFinancial.currency,
CaseFundingRequirement.currency) are left as-is (plain String(3) code
columns, not a foreign key to this table) - this table exists purely to
drive the dropdown's options and validate against a known set of codes,
not to normalize a relationship. Seeded automatically on every app
startup via seed_case_data_lookups().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c1e6a2f9b03'
down_revision: Union[str, Sequence[str], None] = '2b7fa891d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
TABLE = "currencies"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column('id', sa.SmallInteger(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=3), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_currencies_code'),
        schema=CASE_DATA_SCHEMA,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE, schema=CASE_DATA_SCHEMA)
