from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.exceptions import ApplicationError

from app.services.case_state import build_case_payload, get_case_workflow_config
from app.services.case_step_draft_service import delete_case_step_draft
from app.workflows.activity_registry import ACTIVITY_REGISTRY
from app.services.workflow_runtime_service import start_location_risk_workflow

logger = logging.getLogger(__name__)

# Mirrors ConfigDrivenCaseWorkflow._validate_required_fields /
# _extract_validation_errors (app/workflows/case_workflow.py). Duplicated
# here rather than imported, since that module is part of the Temporal
# workflow sandbox's import graph and this one isn't - keeping this service
# free of any import from app.workflows.case_workflow avoids ever having to
# reason about sandbox reachability for this file.


def _validate_required_fields(
    step_config: dict[str, Any], payload: dict[str, Any]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    fields = step_config.get("fields", [])

    if not isinstance(fields, list):
        return {}

    for field in fields:
        if not isinstance(field, dict) or not field.get("required", False):
            continue

        name = field.get("name")
        if not isinstance(name, str) or not name:
            continue

        value = payload.get(name)

        if value is None or (isinstance(value, str) and value.strip() == ""):
            errors[name] = "This field is required"

    return errors


def _extract_field_errors(exc: ApplicationError) -> dict[str, str]:
    details = list(exc.details)

    if details and isinstance(details[0], dict):
        first = details[0]

        if all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in first.items()
        ):
            return first

    return {"form": str(exc)}


async def update_case_step_data(
    db: AsyncSession,
    *,
    case_id: int,
    step_code: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workflow_config = await get_case_workflow_config(db, case_id)

    if workflow_config is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "workflow_not_found",
                "message": f"No workflow config found for case {case_id}.",
            },
        )

    steps = workflow_config.get("steps", {})
    step_config = steps.get(step_code)

    if step_config is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "step_not_found",
                "message": f"Step '{step_code}' not found in workflow config.",
            },
        )

    if step_config.get("submit_mode") == "multipart":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_step_type",
                "message": (
                    "This step must be edited via file upload, not this endpoint."
                ),
            },
        )

    activity_name = step_config.get("activity")
    if not activity_name:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "activity_missing",
                "message": f"No activity configured for step '{step_code}'.",
            },
        )

    activity_fn = ACTIVITY_REGISTRY.get(activity_name)
    if activity_fn is None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "activity_not_registered",
                "message": f"Activity '{activity_name}' is not registered.",
            },
        )

    required_field_errors = _validate_required_fields(step_config, payload)
    if required_field_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validation failed",
                "field_errors": required_field_errors,
            },
        )

    try:
        activity_fn(case_id, payload)
    except ApplicationError as exc:
        if exc.type == "ValidationError":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "field_errors": _extract_field_errors(exc),
                },
            ) from exc

        raise HTTPException(
            status_code=400,
            detail={
                "code": exc.type or "validation_error",
                "message": str(exc),
            },
        ) from exc

    # Committed data supersedes any in-progress draft for this step.
    await delete_case_step_draft(db, case_id=case_id, step_code=step_code)

    # Edited locations bypass the case workflow's completion-time risk fetch,
    # so fetch risk ids for new/changed polygons in the background. Best
    # effort: GET /api/risk/cases/{case_id} fills any still missing.
    if activity_name == "save_location_step":
        try:
            await start_location_risk_workflow(case_id)
        except Exception:
            logger.exception("Could not start location risk fetch for case %s", case_id)

    case_payload = await build_case_payload(db, case_id)
    if case_payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "case_not_found",
                "message": f"Case {case_id} not found.",
            },
        )

    return {
        "caseId": case_id,
        "step": step_code,
        "title": step_config.get("title"),
        "data": case_payload.get(step_code),
    }