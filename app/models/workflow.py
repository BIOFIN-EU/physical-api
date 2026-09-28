# app/models/workflow.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import ActorStampMixin
from app.core.settings import settings

WORKFLOW_SCHEMA = settings.WORKFLOW_DB_SCHEMA
CASE_DATA_SCHEMA = settings.CASE_DATA_DB_SCHEMA

class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_workflow_definitions_code_version"),
        {"schema": WORKFLOW_SCHEMA},
    )

    workflow_definition_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. "nature_financing"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CaseWorkflowRun(Base):
    __tablename__ = "case_workflow_runs"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_workflow_runs_case_id"),
        CheckConstraint("status IN ('draft', 'in_progress', 'completed', 'failed')", name="ck_case_workflow_runs_status"),
        {"schema": WORKFLOW_SCHEMA},
    )

    case_workflow_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_definition_id: Mapped[int] = mapped_column(
        ForeignKey(f"{WORKFLOW_SCHEMA}.workflow_definitions.workflow_definition_id"),
        nullable=False,
    )

    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    temporal_run_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    current_step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CaseStepDraft(ActorStampMixin, Base):
    """
    One row per (case, step): the most recent unsaved/partial progress a user
    made on a step they have not submitted yet.

    `data` is stored as-is with no schema validation ever applied to it - it
    may be incomplete or partially invalid, unlike the committed data saved
    by a step's activity. Saving a new draft for the same (case_id, step_code)
    overwrites the previous one.
    """

    __tablename__ = "case_step_drafts"
    __table_args__ = (
        UniqueConstraint("case_id", "step_code", name="uq_case_step_drafts_case_step"),
        {"schema": WORKFLOW_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CASE_DATA_SCHEMA}.cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_code: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )