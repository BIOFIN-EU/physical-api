"""add case_step_drafts table

Revision ID: 1455c94cf3d1
Revises: 9a94f582d8d8
Create Date: 2026-09-22 12:00:00.000000

Adds workflow.case_step_drafts, storing one row per (case, step) of
unsaved/partial progress data (see app.models.workflow.CaseStepDraft). The
`data` column is arbitrary JSONB with no schema constraints - drafts may be
incomplete.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1455c94cf3d1'
down_revision: Union[str, Sequence[str], None] = '9a94f582d8d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOW_SCHEMA = "workflow"
CASE_DATA_SCHEMA = "case_data"
TABLE = "case_step_drafts"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('step_code', sa.String(length=100), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.UniqueConstraint(
            'case_id', 'step_code', name='uq_case_step_drafts_case_step'
        ),
        schema=WORKFLOW_SCHEMA,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE, schema=WORKFLOW_SCHEMA)
