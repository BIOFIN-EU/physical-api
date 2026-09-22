"""location rework multi location country auto detect

Revision ID: 9a94f582d8d8
Revises: cb0df3527613
Create Date: 2026-09-22 10:59:41.034449

Reworks case_locations to support multiple locations per case (polygon or
point geometry), with country now always auto-detected server-side from the
geometry rather than user-selected.

Notes:
- area_sqm is left NULL for pre-existing rows. Backfilling it by recomputing
  geodesic area from the existing polygon_wkt is out of scope for this
  migration; treat it as a follow-up if historical area values are needed.
- The "XX" / "Multiple Countries" sentinel Country row is NOT seeded here.
  `seed_case_data_lookups()` runs automatically on every app startup (see
  app/main.py's lifespan handler) and already upserts it, so it will exist
  before this migration's new code path can ever be exercised.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a94f582d8d8'
down_revision: Union[str, Sequence[str], None] = 'cb0df3527613'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "case_data"
TABLE = "case_locations"


def upgrade() -> None:
    """Upgrade schema."""

    # A case can now have many locations, so the one-row-per-case constraint
    # must go.
    op.drop_constraint(
        "uq_case_locations_case_id", TABLE, schema=SCHEMA, type_="unique"
    )

    # "region" is replaced by the (differently-scoped) "friendly_name".
    op.drop_column(TABLE, "region", schema=SCHEMA)

    op.add_column(
        TABLE,
        sa.Column("friendly_name", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )

    # location_type: add nullable, backfill every existing row (all of which
    # are polygons today) as 'polygon', then tighten to NOT NULL.
    op.add_column(
        TABLE,
        sa.Column("location_type", sa.String(length=20), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.{TABLE} SET location_type = 'polygon' "
        f"WHERE location_type IS NULL"
    )
    op.alter_column(
        TABLE,
        "location_type",
        existing_type=sa.String(length=20),
        nullable=False,
        schema=SCHEMA,
    )

    # polygon_wkt -> geometry_wkt, and now nullable (a point-type row stores
    # its geometry as WKT too, but some future row shapes may omit it).
    op.alter_column(
        TABLE,
        "polygon_wkt",
        new_column_name="geometry_wkt",
        existing_type=sa.Text(),
        nullable=True,
        schema=SCHEMA,
    )

    op.add_column(
        TABLE,
        sa.Column("latitude", sa.Float(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("longitude", sa.Float(), nullable=True),
        schema=SCHEMA,
    )

    op.add_column(
        TABLE,
        sa.Column("area_sqm", sa.Float(), nullable=True),
        schema=SCHEMA,
    )

    op.add_column(
        TABLE,
        sa.Column(
            "area_is_manual",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column(TABLE, "area_is_manual", schema=SCHEMA)
    op.drop_column(TABLE, "area_sqm", schema=SCHEMA)
    op.drop_column(TABLE, "longitude", schema=SCHEMA)
    op.drop_column(TABLE, "latitude", schema=SCHEMA)

    op.alter_column(
        TABLE,
        "geometry_wkt",
        new_column_name="polygon_wkt",
        existing_type=sa.Text(),
        nullable=False,
        schema=SCHEMA,
    )

    op.drop_column(TABLE, "location_type", schema=SCHEMA)
    op.drop_column(TABLE, "friendly_name", schema=SCHEMA)

    op.add_column(
        TABLE,
        sa.Column("region", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )

    op.create_unique_constraint(
        "uq_case_locations_case_id", TABLE, ["case_id"], schema=SCHEMA
    )
