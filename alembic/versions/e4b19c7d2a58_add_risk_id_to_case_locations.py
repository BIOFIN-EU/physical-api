"""add risk_id to case_locations

Revision ID: e4b19c7d2a58
Revises: 7c1e6a2f9b03
Create Date: 2026-09-24 10:00:00.000000

Adds case_data.case_locations.risk_id, the Biodiversity Risk Index record id
returned (via the Management Actions priority endpoint) by the Risk Score
Framework. Nullable: point locations never get one, and polygon locations
only get one once fetch_location_risk_ids (or GET /cases/{case_id}/risk)
has run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4b19c7d2a58'
down_revision: Union[str, Sequence[str], None] = '7c1e6a2f9b03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
TABLE = "case_locations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column('risk_id', sa.String(length=64), nullable=True),
        schema=CASE_DATA_SCHEMA,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE, 'risk_id', schema=CASE_DATA_SCHEMA)
