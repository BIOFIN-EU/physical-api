"""workflow roles for every pathway; case_role retired

Revision ID: c4e8a2f6b913
Revises: b3c9d1e7f204
Create Date: 2026-10-06 18:00:00.000000

Roles become part of every workflow's config (workflows.json "roles"), not
just BNG's, so their tables lose the "bng_" prefix:

- bng_case_roles -> case_workflow_roles (the list of allowed roles moves
  from a CHECK constraint to the config, checked when the config loads).
- bng_step_signoffs -> case_step_signoffs.
- case_user_access.case_role (borrower / funder / intermediary, never
  used) becomes a workflow role on the two financing pathways, whose steps
  now have roles, and is dropped.

Stop the API and worker, run this, then start the new code.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f6b913"
down_revision: Union[str, Sequence[str], None] = "b3c9d1e7f204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "case_data"
FINANCING_WORKFLOWS = ("private_lending_v1", "use_case_2_v1")

# old table -> (new table, {old object name: new object name})
RENAMES = {
    "bng_case_roles": ("case_workflow_roles", {
        "constraint": {
            "bng_case_roles_pkey": "case_workflow_roles_pkey",
            "uq_bng_case_roles_case_user_role": "uq_case_workflow_roles_case_user_role",
            "bng_case_roles_case_id_fkey": "case_workflow_roles_case_id_fkey",
        },
        "index": {
            "ix_case_data_bng_case_roles_case_id": "ix_case_data_case_workflow_roles_case_id",
            "ix_case_data_bng_case_roles_user_id": "ix_case_data_case_workflow_roles_user_id",
        },
        "sequence": {"bng_case_roles_id_seq": "case_workflow_roles_id_seq"},
    }),
    "bng_step_signoffs": ("case_step_signoffs", {
        "constraint": {
            "bng_step_signoffs_pkey": "case_step_signoffs_pkey",
            "ck_bng_step_signoffs_decision": "ck_case_step_signoffs_decision",
            "bng_step_signoffs_case_id_fkey": "case_step_signoffs_case_id_fkey",
        },
        "index": {"ix_case_data_bng_step_signoffs_case_id": "ix_case_data_case_step_signoffs_case_id"},
        "sequence": {"bng_step_signoffs_id_seq": "case_step_signoffs_id_seq"},
    }),
}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names(schema=S))


def _rename_table(old: str, new: str, objects: dict, *, reverse: bool = False) -> None:
    tables = _tables()
    if old not in tables:
        return
    if new in tables:
        # The new code's startup created the new table first: move the rows.
        columns = ", ".join(c["name"] for c in sa.inspect(op.get_bind()).get_columns(old, schema=S) if c["name"] != "id")
        op.execute(f"INSERT INTO {S}.{new} ({columns}) SELECT {columns} FROM {S}.{old} ON CONFLICT DO NOTHING")
        op.execute(f"DROP TABLE {S}.{old}")
        return
    op.execute(f"ALTER TABLE {S}.{old} RENAME TO {new}")
    for kind, names in objects.items():
        for before, after in names.items():
            if reverse:
                before, after = after, before
            if kind == "constraint":
                op.execute(f"ALTER TABLE {S}.{new} RENAME CONSTRAINT {before} TO {after}")
            elif kind == "index":
                op.execute(f"ALTER INDEX IF EXISTS {S}.{before} RENAME TO {after}")
            else:
                op.execute(f"ALTER SEQUENCE IF EXISTS {S}.{before} RENAME TO {after}")


def upgrade() -> None:
    """Upgrade schema."""
    if "bng_case_roles" in _tables():
        op.execute(f"ALTER TABLE {S}.bng_case_roles DROP CONSTRAINT IF EXISTS ck_bng_case_roles_role")
    for old, (new, objects) in RENAMES.items():
        _rename_table(old, new, objects)
    op.execute(f"ALTER TABLE {S}.case_workflow_roles ALTER COLUMN role TYPE varchar(50)")
    op.execute(f"ALTER TABLE {S}.case_step_signoffs ALTER COLUMN role TYPE varchar(50)")

    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("case_user_access", schema=S)}
    if "case_role" in columns:
        # borrower / funder / intermediary are the financing pathways' roles.
        op.execute(f"""
            INSERT INTO {S}.case_workflow_roles (case_id, user_id, role, created_by, updated_by)
            SELECT a.case_id, a.user_id, a.case_role, a.user_id, a.user_id
              FROM {S}.case_user_access a
              JOIN {S}.cases c ON c.id = a.case_id
             WHERE c.case_type IN ('{"', '".join(FINANCING_WORKFLOWS)}')
               AND a.case_role IN ('borrower', 'funder', 'intermediary')
            ON CONFLICT ON CONSTRAINT uq_case_workflow_roles_case_user_role DO NOTHING
        """)
        op.execute(f"ALTER TABLE {S}.case_user_access DROP CONSTRAINT IF EXISTS ck_case_user_access_case_role")
        op.drop_column("case_user_access", "case_role", schema=S)


def downgrade() -> None:
    """
    Downgrade schema. case_role comes back from the financing roles (else
    'borrower'); roles the old CHECK constraint doesn't allow are dropped.
    """
    op.add_column(
        "case_user_access",
        sa.Column("case_role", sa.String(50), nullable=False, server_default="borrower"),
        schema=S,
    )
    op.execute(f"""
        UPDATE {S}.case_user_access a SET case_role = r.role
          FROM {S}.case_workflow_roles r
         WHERE r.case_id = a.case_id AND r.user_id = a.user_id
           AND r.role IN ('borrower', 'funder', 'intermediary')
    """)
    op.alter_column("case_user_access", "case_role", server_default=None, schema=S)
    op.create_check_constraint(
        "ck_case_user_access_case_role", "case_user_access",
        "case_role IN ('borrower', 'funder', 'intermediary')", schema=S,
    )
    op.execute(f"""
        DELETE FROM {S}.case_workflow_roles
         WHERE role NOT IN ('landowner', 'investor', 'developer', 'ecologist', 'lpa')
    """)
    for old, (new, objects) in RENAMES.items():
        _rename_table(new, old, objects, reverse=True)
    op.execute(f"ALTER TABLE {S}.bng_case_roles ALTER COLUMN role TYPE varchar(20)")
    op.execute(f"ALTER TABLE {S}.bng_step_signoffs ALTER COLUMN role TYPE varchar(20)")
    op.create_check_constraint(
        "ck_bng_case_roles_role", "bng_case_roles",
        "role IN ('landowner', 'investor', 'developer', 'ecologist', 'lpa')", schema=S,
    )
