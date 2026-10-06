"""
Request bodies of the BNG Phase 3 endpoints (roles, monitoring, remedial
actions). Kept apart from app.schemas.bng, which the workflow worker imports:
its sandbox can't build models with date fields.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OnBehalfRequest(BaseModel):
    # A project manager confirming they act for the role that owns the action.
    on_behalf: bool = False


class MonitoringReportSubmit(OnBehalfRequest):
    habitats_on_track: bool
    condition_summary: str = Field(min_length=1, max_length=4000)
    management_carried_out: Optional[str] = Field(default=None, max_length=4000)


class RemedialActionInput(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    due_date: Optional[date] = None


class MonitoringReportVerify(OnBehalfRequest):
    outcome: Literal["passed", "failed"]
    verification_notes: Optional[str] = Field(default=None, max_length=4000)
    # Required when the outcome is failed.
    remedial_actions: list[RemedialActionInput] = Field(default_factory=list, max_length=20)


class RemedialActionComplete(OnBehalfRequest):
    completion_notes: str = Field(min_length=1, max_length=4000)


class AllocationSuggestionsRequest(BaseModel):
    # The units still needed after the rows in the form, per category.
    need: dict[Literal["area", "hedgerow", "watercourse"], float] = Field(default_factory=dict)
    # Banks already in the form, which are not suggested again.
    exclude_bank_ids: list[int] = Field(default_factory=list, max_length=200)
