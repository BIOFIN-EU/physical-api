"""
Pydantic schemas for the step-draft endpoints.

Deliberately kept in their own module, separate from app/schemas/case_workflow.py.
That module is imported by app/workflows/activities.py, which is reachable from
the Temporal workflow definition (ConfigDrivenCaseWorkflow -> activity_registry
-> activities -> schemas/case_workflow), and Temporal's workflow sandbox
re-imports that whole graph in a restricted environment at worker startup. A
pydantic.BaseModel with a `datetime` field builds its pydantic-core schema at
class-definition time (i.e. at import time, not lazily), and doing that against
the sandbox's own restricted `datetime` module (rather than the real one)
fails with "Unable to generate pydantic-core schema for <class
'datetime.datetime'>" and crashes worker startup - the same class of problem
as the shapely/pyproj import crash this codebase hit before. These schemas are
only ever used by the FastAPI router (app/routers/case_workflow.py), which is
never reachable from the workflow file, so keeping them here avoids the
sandboxed import graph entirely.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class CaseStepDraftRequest(BaseModel):
    """
    Arbitrary partial/in-progress data for a step a user is currently
    viewing. Intentionally not validated against the step's real Pydantic
    schema - a draft may be incomplete.
    """
    data: dict[str, Any]


class CaseStepDraftResponse(BaseModel):
    data: Optional[dict[str, Any]] = None
    updated_at: Optional[datetime] = None
