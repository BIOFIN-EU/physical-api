from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class ActorStampMixin:
    """
    Who created / last changed a row. Step activities fill these on flush
    from session.info["actor_user_id"] (app.workflows.activities); the API
    sets them directly elsewhere. Rows written before these columns existed,
    or by system jobs, leave them empty.
    """

    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class CreatedByMixin:
    """created_by only, for link rows that are added or removed, never edited."""

    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class SoftDeleteMixin:
    """
    Soft delete: a row with deleted_at set is hidden from the API but kept,
    so records that reference it stay intact. Restoring is clearing both.
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
