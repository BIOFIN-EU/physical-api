"""soft delete cases

Revision ID: a3f5c8e21d74
Revises: e4b19c7d2a58
Create Date: 2026-09-28 16:00:00.000000

Adds case_data.cases.deleted_at / deleted_by. Deleting a project from the UI
sets these instead of removing rows; every case endpoint and the project list
treat a case with deleted_at set as gone. Restoring one is clearing both
columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3f5c8e21d74'
down_revision: Union[str, Sequence[str], None] = 'e4b19c7d2a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
TABLE = "cases"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        schema=CASE_DATA_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        schema=CASE_DATA_SCHEMA,
    )
    op.create_index(
        op.f('ix_case_data_cases_deleted_at'), TABLE, ['deleted_at'], schema=CASE_DATA_SCHEMA
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_case_data_cases_deleted_at'), table_name=TABLE, schema=CASE_DATA_SCHEMA)
    op.drop_column(TABLE, 'deleted_by', schema=CASE_DATA_SCHEMA)
    op.drop_column(TABLE, 'deleted_at', schema=CASE_DATA_SCHEMA)
