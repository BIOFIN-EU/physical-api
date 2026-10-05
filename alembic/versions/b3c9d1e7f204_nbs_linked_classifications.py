"""nbs linked classifications; nbs type removed

Revision ID: b3c9d1e7f204
Revises: a8d3e5f7c912
Create Date: 2026-10-05 12:00:00.000000

The NbS step's classifications become linked, so each list only offers what
fits the choice above it:

    Environment -> Intervention -> Approach
                                -> Societal challenge

- nbs_environment_interventions, nbs_intervention_approaches and
  nbs_intervention_societal_challenges: the links (many-to-many, with
  foreign keys to both lookups). Their rows are seeded on startup
  (app/core/seed_case_data_lookups.py).
- Flags for options that fit everything: nbs_environment_types.
  matches_all_interventions ("Multiple"), nbs_intervention_types.matches_all
  ("Monitoring"), nbs_societal_challenge_types.cross_cutting.
- The placeholder "NbS Type" is removed: case_nature_based_solutions.
  nbs_type_id and the nbs_types table are dropped (their values are lost).

Run this before starting the new code: its startup seed sets the new flags.
The app's startup create_all may already have created the link tables, so
they are only created here if missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.case_data import (
    NbSEnvironmentIntervention,
    NbSInterventionApproach,
    NbSInterventionSocietalChallenge,
)

# revision identifiers, used by Alembic.
revision: str = 'b3c9d1e7f204'
down_revision: Union[str, Sequence[str], None] = 'a8d3e5f7c912'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "case_data"

LINK_TABLES = [NbSEnvironmentIntervention, NbSInterventionApproach, NbSInterventionSocietalChallenge]

FLAGS = [
    ("nbs_environment_types", "matches_all_interventions"),
    ("nbs_intervention_types", "matches_all"),
    ("nbs_societal_challenge_types", "cross_cutting"),
]


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table, schema=S)}


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in FLAGS:
        if column not in _columns(table):
            op.add_column(table, sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()), schema=S)

    bind = op.get_bind()
    for model in LINK_TABLES:
        model.__table__.create(bind, checkfirst=True)

    if "nbs_type_id" in _columns("case_nature_based_solutions"):
        op.drop_column("case_nature_based_solutions", "nbs_type_id", schema=S)
    op.execute(f"DROP TABLE IF EXISTS {S}.nbs_types")


def downgrade() -> None:
    """Downgrade schema. NbS types come back empty, and the NbS step's type unset."""
    op.create_table(
        "nbs_types",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        schema=S,
    )
    op.add_column(
        "case_nature_based_solutions",
        sa.Column("nbs_type_id", sa.SmallInteger(), sa.ForeignKey(f"{S}.nbs_types.id"), nullable=True),
        schema=S,
    )
    bind = op.get_bind()
    for model in reversed(LINK_TABLES):
        model.__table__.drop(bind, checkfirst=True)
    for table, column in FLAGS:
        op.drop_column(table, column, schema=S)
