"""add case_consents table

Revision ID: 2b7fa891d4e6
Revises: 1455c94cf3d1
Create Date: 2026-09-22 13:00:00.000000

Adds case_data.case_consents. The consent step's activity was previously a
no-op stub (save_consent_step just did `pass`), so nothing was ever
persisted for it and it couldn't be shown as "done" or edited like other
steps. This gives it a real, singleton-per-case row, same pattern as
CaseBasicInfo.

There is no data migration for pre-existing cases: the old no-op activity
never recorded what a case's consent answers actually were, so there is
nothing accurate to backfill. Cases that already passed through the
consent step under the old behavior will simply show it as not-yet-done
until it's resubmitted or edited.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2b7fa891d4e6'
down_revision: Union[str, Sequence[str], None] = '1455c94cf3d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
TABLE = "case_consents"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('disclaimer_acknowledged', sa.Boolean(), nullable=False),
        sa.Column('allow_data_sharing', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['case_id'],
            [f'{CASE_DATA_SCHEMA}.cases.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', name='uq_case_consents_case_id'),
        schema=CASE_DATA_SCHEMA,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE, schema=CASE_DATA_SCHEMA)
