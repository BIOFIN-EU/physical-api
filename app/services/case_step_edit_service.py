from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.exceptions import ApplicationError

from app.services.case_state import build_case_payload, get_case_workflow_config
from app.workflows.activity_registry import ACTIVITY_REGISTRY


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

    try:
        activity_fn(case_id, payload)
    except ApplicationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": exc.type or "validation_error",
                "message": str(exc),
            },
        ) from exc

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