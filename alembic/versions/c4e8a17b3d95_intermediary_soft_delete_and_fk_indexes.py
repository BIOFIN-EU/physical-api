"""intermediary soft delete and foreign key indexes

Revision ID: c4e8a17b3d95
Revises: b7d2e94c1f60
Create Date: 2026-09-28 18:00:00.000000

- case_data.intermediaries.deleted_at / deleted_by: deleting an intermediary
  hides it instead of removing the row (which cascaded away its case links).
- Indexes on foreign keys used to look rows up by case (and country), which
  Postgres does not create by itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4e8a17b3d95'
down_revision: Union[str, Sequence[str], None] = 'b7d2e94c1f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"

FK_INDEXES = [
    ("case_locations", "case_id"),
    ("case_locations", "country_id"),
    ("case_documents", "case_id"),
    ("operators", "case_id"),
    ("intermediaries", "deleted_at"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "intermediaries",
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        schema=CASE_DATA_SCHEMA,
    )
    op.add_column(
        "intermediaries",
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        schema=CASE_DATA_SCHEMA,
    )

    for table, column in FK_INDEXES:
        op.create_index(
            op.f(f'ix_{CASE_DATA_SCHEMA}_{table}_{column}'),
            table,
            [column],
            schema=CASE_DATA_SCHEMA,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in reversed(FK_INDEXES):
        op.drop_index(
            op.f(f'ix_{CASE_DATA_SCHEMA}_{table}_{column}'),
            table_name=table,
            schema=CASE_DATA_SCHEMA,
        )

    op.drop_column("intermediaries", 'deleted_by', schema=CASE_DATA_SCHEMA)
    op.drop_column("intermediaries", 'deleted_at', schema=CASE_DATA_SCHEMA)
