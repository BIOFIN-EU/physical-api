"""data integrity constraints

Revision ID: d9a3f6b82e17
Revises: c4e8a17b3d95
Create Date: 2026-09-28 19:00:00.000000

Moves rules the code already relies on into the database:
- case_documents: one row per (case_id, step_code, field_name)
- case_locations.location_type in ('polygon', 'point')
- cases.status / case_workflow_runs.status in the workflow's four statuses
- intermediaries: one active intermediary per email (case-insensitive)

Existing rows that break a rule stop the migration with a list of them,
before anything changes (the whole migration is one transaction), so they can
be fixed and the migration re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9a3f6b82e17'
down_revision: Union[str, Sequence[str], None] = 'c4e8a17b3d95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASE_DATA_SCHEMA = "case_data"
WORKFLOW_SCHEMA = "workflow"

STATUSES = "('draft', 'in_progress', 'completed', 'failed')"

# (what is wrong, query returning the offending rows)
PRECHECKS = [
    (
        "case_documents with more than one row per (case_id, step_code, field_name)",
        "SELECT case_id, step_code, field_name, count(*) FROM case_data.case_documents "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1",
    ),
    (
        "case_locations with a location_type other than polygon/point",
        "SELECT id, case_id, location_type FROM case_data.case_locations "
        "WHERE location_type NOT IN ('polygon', 'point')",
    ),
    (
        "cases with an unknown status",
        f"SELECT id, status FROM case_data.cases WHERE status NOT IN {STATUSES}",
    ),
    (
        "case_workflow_runs with an unknown status",
        f"SELECT case_id, status FROM workflow.case_workflow_runs WHERE status NOT IN {STATUSES}",
    ),
    (
        "active intermediaries sharing an email (case-insensitive)",
        "SELECT lower(email), array_agg(id ORDER BY id) FROM case_data.intermediaries "
        "WHERE email IS NOT NULL AND deleted_at IS NULL GROUP BY 1 HAVING count(*) > 1",
    ),
]


def _check_existing_data() -> None:
    conn = op.get_bind()
    problems = []

    for description, query in PRECHECKS:
        rows = conn.execute(sa.text(query)).fetchall()
        if rows:
            listed = "\n".join(f"    {tuple(row)}" for row in rows[:20])
            more = f"\n    ... and {len(rows) - 20} more" if len(rows) > 20 else ""
            problems.append(f"  {description}:\n{listed}{more}")

    if problems:
        raise RuntimeError(
            "Existing data breaks the new constraints; fix these rows and re-run "
            "the migration (nothing was changed):\n" + "\n".join(problems)
        )


def upgrade() -> None:
    """Upgrade schema."""
    _check_existing_data()

    op.create_unique_constraint(
        "uq_case_documents_case_step_field",
        "case_documents",
        ["case_id", "step_code", "field_name"],
        schema=CASE_DATA_SCHEMA,
    )
    op.create_check_constraint(
        "ck_case_locations_location_type",
        "case_locations",
        "location_type IN ('polygon', 'point')",
        schema=CASE_DATA_SCHEMA,
    )
    op.create_check_constraint(
        "ck_cases_status",
        "cases",
        f"status IN {STATUSES}",
        schema=CASE_DATA_SCHEMA,
    )
    op.create_check_constraint(
        "ck_case_workflow_runs_status",
        "case_workflow_runs",
        f"status IN {STATUSES}",
        schema=WORKFLOW_SCHEMA,
    )
    op.create_index(
        "uq_intermediaries_active_email",
        "intermediaries",
        [sa.text("lower(email)")],
        unique=True,
        schema=CASE_DATA_SCHEMA,
        postgresql_where=sa.text("email IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_intermediaries_active_email", table_name="intermediaries", schema=CASE_DATA_SCHEMA)
    op.drop_constraint("ck_case_workflow_runs_status", "case_workflow_runs", type_="check", schema=WORKFLOW_SCHEMA)
    op.drop_constraint("ck_cases_status", "cases", type_="check", schema=CASE_DATA_SCHEMA)
    op.drop_constraint("ck_case_locations_location_type", "case_locations", type_="check", schema=CASE_DATA_SCHEMA)
    op.drop_constraint("uq_case_documents_case_step_field", "case_documents", type_="unique", schema=CASE_DATA_SCHEMA)
