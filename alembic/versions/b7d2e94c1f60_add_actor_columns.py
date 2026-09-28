"""add created_by / updated_by to case data tables

Revision ID: b7d2e94c1f60
Revises: a3f5c8e21d74
Create Date: 2026-09-28 17:00:00.000000

Records which user created and last changed each row of the step tables,
intermediaries and step drafts (ActorStampMixin / CreatedByMixin in
app.models.mixins). Nullable: existing rows have no known author, and system
jobs write none. Also adds case_financing_types.updated_at (it is edited in
place) and case_step_drafts.created_at; existing rows get now().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7d2e94c1f60'
down_revision: Union[str, Sequence[str], None] = 'a3f5c8e21d74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
WORKFLOW_SCHEMA = "workflow"

# Tables that are edited in place: who created them and who last changed them.
CREATED_AND_UPDATED = [
    "case_consents",
    "case_basic_info",
    "case_locations",
    "case_financials",
    "case_identifiers",
    "operators",
    "case_documents",
    "case_nature_based_solutions",
    "case_funding_requirements",
    "case_investment_rationales",
    "case_financing_types",
    "intermediaries",
]

# Link rows that are replaced rather than edited.
CREATED_ONLY = [
    "case_intermediaries",
]


def upgrade() -> None:
    """Upgrade schema."""
    for table in CREATED_AND_UPDATED + CREATED_ONLY:
        op.add_column(
            table,
            sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
            schema=CASE_DATA_SCHEMA,
        )
    for table in CREATED_AND_UPDATED:
        op.add_column(
            table,
            sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
            schema=CASE_DATA_SCHEMA,
        )

    # case_financing_types is edited in place, so it also needs updated_at.
    op.add_column(
        "case_financing_types",
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=CASE_DATA_SCHEMA,
    )

    # Drafts: when first saved, and by whom.
    op.add_column(
        "case_step_drafts",
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=WORKFLOW_SCHEMA,
    )
    for column in ("created_by", "updated_by"):
        op.add_column(
            "case_step_drafts",
            sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True),
            schema=WORKFLOW_SCHEMA,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("updated_by", "created_by", "created_at"):
        op.drop_column("case_step_drafts", column, schema=WORKFLOW_SCHEMA)
    op.drop_column("case_financing_types", 'updated_at', schema=CASE_DATA_SCHEMA)
    for table in CREATED_AND_UPDATED:
        op.drop_column(table, 'updated_by', schema=CASE_DATA_SCHEMA)
    for table in CREATED_AND_UPDATED + CREATED_ONLY:
        op.drop_column(table, 'created_by', schema=CASE_DATA_SCHEMA)
