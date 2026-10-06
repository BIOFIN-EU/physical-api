"""bng roles, approvals and monitoring (phase 3)

Revision ID: a8d3e5f7c912
Revises: f2a7c4d91b36
Create Date: 2026-09-29 18:00:00.000000

Biodiversity Net Gain prototype, phase 3. Only bng_* objects change:
- bng_case_roles: BNG roles of users on a project (several per user).
  The owner of each existing BNG project gets its creator role
  (landowner for a habitat bank, developer for a development).
- bng_step_signoffs: who submitted / approved / rejected / edited a step,
  in which role, and whether on behalf of another role.
- bng_monitoring_reports and bng_remedial_actions: 30-year monitoring,
  verification and remedial actions of registered habitat banks.
- bng_transactions gets the bank's revenue split at the time of sale.

The app's startup create_all may already have created the new tables, so
they are only created here if missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.bng import BngMonitoringReport, BngRemedialAction

# The two tables as this revision created them (later renamed to
# case_workflow_roles and case_step_signoffs, revision c4e8a2f6b913), so
# this revision doesn't depend on today's models.
_metadata = sa.MetaData()
sa.Table("cases", _metadata, sa.Column("id", sa.Integer, primary_key=True), schema="case_data")
BngCaseRole = sa.Table(
    "bng_case_roles", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("case_id", sa.Integer, sa.ForeignKey("case_data.cases.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("user_id", PGUUID(as_uuid=True), nullable=False, index=True),
    sa.Column("role", sa.String(20), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("created_by", PGUUID(as_uuid=True), nullable=True),
    sa.Column("updated_by", PGUUID(as_uuid=True), nullable=True),
    sa.UniqueConstraint("case_id", "user_id", "role", name="uq_bng_case_roles_case_user_role"),
    sa.CheckConstraint(
        "role IN ('landowner', 'investor', 'developer', 'ecologist', 'lpa')", name="ck_bng_case_roles_role"
    ),
    schema="case_data",
)
BngStepSignoff = sa.Table(
    "bng_step_signoffs", _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("case_id", sa.Integer, sa.ForeignKey("case_data.cases.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("step_code", sa.String(100), nullable=False),
    sa.Column("user_id", PGUUID(as_uuid=True), nullable=False),
    sa.Column("role", sa.String(20), nullable=True),
    sa.Column("on_behalf", sa.Boolean, nullable=False),
    sa.Column("decision", sa.String(20), nullable=False),
    sa.Column("comment", sa.String(2000), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint(
        "decision IN ('submitted', 'approved', 'rejected', 'edited')", name="ck_bng_step_signoffs_decision"
    ),
    schema="case_data",
)

# revision identifiers, used by Alembic.
revision: str = 'a8d3e5f7c912'
down_revision: Union[str, Sequence[str], None] = 'f2a7c4d91b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "case_data"

# Created in this order, dropped in reverse (remedial actions reference reports).
NEW_TABLES = [BngCaseRole, BngStepSignoff, BngMonitoringReport, BngRemedialAction]

SHARE_COLUMNS = ("landowner_share_percent", "investor_share_percent", "manager_share_percent")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for model in NEW_TABLES:
        getattr(model, "__table__", model).create(bind, checkfirst=True)

    existing = {c["name"] for c in sa.inspect(bind).get_columns("bng_transactions", schema=S)}
    for name in SHARE_COLUMNS:
        if name not in existing:
            op.add_column("bng_transactions", sa.Column(name, sa.Numeric(5, 2), nullable=True), schema=S)

    # Existing BNG projects: their owner gets the project's creator role.
    op.execute(f"""
        INSERT INTO {S}.bng_case_roles (case_id, user_id, role, created_by, updated_by)
        SELECT a.case_id, a.user_id,
               CASE c.case_type WHEN 'bng_habitat_bank_v1' THEN 'landowner' ELSE 'developer' END,
               a.user_id, a.user_id
          FROM {S}.case_user_access a
          JOIN {S}.cases c ON c.id = a.case_id
         WHERE a.is_owner
           AND c.case_type IN ('bng_habitat_bank_v1', 'bng_development_v1')
        ON CONFLICT ON CONSTRAINT uq_bng_case_roles_case_user_role DO NOTHING
    """)


def downgrade() -> None:
    """Downgrade schema."""
    for name in SHARE_COLUMNS:
        op.drop_column("bng_transactions", name, schema=S)
    bind = op.get_bind()
    for model in reversed(NEW_TABLES):
        getattr(model, "__table__", model).drop(bind, checkfirst=True)
