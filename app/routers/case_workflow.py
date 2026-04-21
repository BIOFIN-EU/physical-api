import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from app.core.db import get_db
from app.core.settings import settings
from app.dependencies.gateway_identity import get_request_user_id
from app.models.case_data import CaseDocument
from app.models.workflow import CaseWorkflowRun
from app.services.case_state import build_case_payload, get_case_workflow_config, fetch_cases
from app.services.file_storage_service import store_upload
from app.services.object_storage_service import get_presigned_download_url
from app.services.workflow_config_service import WorkflowNotFoundError
from app.services.workflow_runtime_service import WorkflowRuntimeService, WorkflowNotActiveError
from app.services.case_step_edit_service import update_case_step_data


logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_run_or_404(db: AsyncSession, case_id: int) -> CaseWorkflowRun:
    result = await db.execute(
        select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == case_id)
    )
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    return run


def _raise_if_workflow_closed(run: CaseWorkflowRun) -> None:
    if run.status in {"failed", "completed"}:
        raise WorkflowNotActiveError(
            f"Workflow is {run.status} and cannot accept new submissions."
        )


def _raise_for_temporal_rpc_error(exc: RPCError) -> None:
    message = str(exc).lower()

    if exc.status == RPCStatusCode.NOT_FOUND or "already completed" in message:
        raise WorkflowNotActiveError(
            "This workflow is no longer active. Refresh the case state."
        )

    raise HTTPException(
        status_code=502,
        detail={
            "code": "workflow_signal_failed",
            "message": "Could not submit the step to the workflow engine.",
        },
    )


def _map_workflow_not_active_error(
    exc: WorkflowNotActiveError,
    run: CaseWorkflowRun | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "workflow_not_active",
            "message": str(exc),
            "current_step": run.current_step if run else None,
        },
    )


def _validate_fields(step_config: dict, payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}

    for field in step_config.get("fields", []):
        name = field["name"]
        field_type = field.get("type")
        required = field.get("required", False)
        value = payload.get(name)

        if required:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                errors[name] = "This field is required"
                continue

        if value is None:
            continue

        if field_type == "number":
            if not isinstance(value, (int, float)):
                errors[name] = "Must be a number"

        elif field_type in {"text", "textarea"}:
            if not isinstance(value, str):
                errors[name] = "Must be text"

    return errors


@router.post("/cases/start")
async def start_case(
    workflow_code: str,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict:
    service = WorkflowRuntimeService(db)

    try:
        temporal_workflow_id = await service.start_workflow(
            workflow_code=workflow_code,
            user_id=user_id,
        )
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_code}' not found",
        )
    except WorkflowNotActiveError as exc:
        raise _map_workflow_not_active_error(exc)

    case_id = int(temporal_workflow_id.replace("case-", ""))

    return {
        "case_id": case_id,
        "temporal_workflow_id": temporal_workflow_id,
        "workflow_code": workflow_code,
    }


@router.get("/cases/{case_id}/state")
async def get_case_state(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await _get_run_or_404(db, case_id)

    workflow_state: dict[str, Any] = {
        "case_id": case_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "current_step": run.current_step,
        "status": run.status,
        "validation_errors": {},
        "step": None,
    }

    try:
        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(run.temporal_workflow_id)
        workflow_state = await handle.query("get_state")
    except RPCError:
        # Fall back to DB-backed state if Temporal workflow is already closed/unqueryable
        pass

    result = await db.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id)
    )
    documents = result.scalars().all()

    workflow_state["documents"] = [
        {
            "case_document_id": doc.id,
            "case_id": doc.case_id,
            "step_code": doc.step_code,
            "field_name": doc.field_name,
            "original_filename": doc.original_filename,
            "upload_token": doc.upload_token,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "created_at": doc.created_at,
        }
        for doc in documents
    ]

    return workflow_state


@router.post("/cases/{case_id}/submit-json")
async def submit_step(
    case_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    logger.info("Received payload for case %s: %s", case_id, payload)

    run = await _get_run_or_404(db, case_id)

    try:
        _raise_if_workflow_closed(run)

        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(run.temporal_workflow_id)

        try:
            before_state = await handle.query("get_state")
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        current_step = before_state.get("current_step")
        step_config = before_state.get("step", {})
        before_status = before_state.get("status")

        if not current_step:
            raise HTTPException(status_code=400, detail="No current step available")

        errors = _validate_fields(step_config, payload)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Validation failed",
                    "current_step": current_step,
                    "field_errors": errors,
                },
            )

        try:
            await handle.signal("submit_step", payload)
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        for _ in range(15):
            await asyncio.sleep(0.2)

            await db.refresh(run)

            if run.status in {"failed", "completed"}:
                try:
                    state = await handle.query("get_state")
                except RPCError:
                    state = {
                        "case_id": case_id,
                        "temporal_workflow_id": run.temporal_workflow_id,
                        "current_step": run.current_step,
                        "status": run.status,
                        "validation_errors": {},
                        "step": None,
                    }

                if run.status == "failed":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "workflow_failed",
                            "message": "Workflow failed while processing the submitted step.",
                            "state": state,
                        },
                    )

                return {
                    "message": "Step submitted successfully",
                    "state": state,
                }

            try:
                state = await handle.query("get_state")
            except RPCError as exc:
                _raise_for_temporal_rpc_error(exc)

            validation_errors = state.get("validation_errors") or {}
            new_step = state.get("current_step")
            new_status = state.get("status")

            if validation_errors:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Validation failed",
                        "current_step": new_step,
                        "field_errors": validation_errors,
                    },
                )

            if new_step != current_step or new_status != before_status:
                return {
                    "message": "Step submitted successfully",
                    "state": state,
                }

        try:
            final_state = await handle.query("get_state")
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        raise HTTPException(
            status_code=202,
            detail={
                "message": "Submission accepted and is still processing",
                "state": final_state,
            },
        )

    except WorkflowNotActiveError as exc:
        raise _map_workflow_not_active_error(exc, run)


@router.post("/cases/{case_id}/submit-file")
async def submit_file_step(
    case_id: int,
    field_name: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await _get_run_or_404(db, case_id)

    try:
        _raise_if_workflow_closed(run)

        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(run.temporal_workflow_id)

        try:
            before_state = await handle.query("get_state")
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        current_step = before_state.get("current_step")
        step_config = before_state.get("step", {})
        before_status = before_state.get("status")

        if not current_step:
            raise HTTPException(status_code=400, detail="No current step available")

        step_fields = step_config.get("fields", [])
        matching_field = next((f for f in step_fields if f["name"] == field_name), None)

        if matching_field is None:
            raise HTTPException(
                status_code=422,
                detail=f"Field '{field_name}' does not exist on current step '{current_step}'",
            )

        if matching_field.get("type") != "file":
            raise HTTPException(
                status_code=422,
                detail=f"Field '{field_name}' is not a file field",
            )

        file_payload = await store_upload(
            case_id=case_id,
            current_step=current_step,
            field_name=field_name,
            upload=file,
        )

        signal_payload = {
            "_step_code": current_step,
            "_field_name": field_name,
            field_name: file_payload,
        }

        try:
            await handle.signal("submit_step", signal_payload)
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        for _ in range(15):
            await asyncio.sleep(0.2)

            await db.refresh(run)

            if run.status in {"failed", "completed"}:
                try:
                    state = await handle.query("get_state")
                except RPCError:
                    state = {
                        "case_id": case_id,
                        "temporal_workflow_id": run.temporal_workflow_id,
                        "current_step": run.current_step,
                        "status": run.status,
                        "validation_errors": {},
                        "step": None,
                    }

                if run.status == "failed":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "workflow_failed",
                            "message": "Workflow failed while processing the uploaded file.",
                            "state": state,
                        },
                    )

                return {
                    "message": "File step submitted successfully",
                    "state": state,
                }

            try:
                state = await handle.query("get_state")
            except RPCError as exc:
                _raise_for_temporal_rpc_error(exc)

            validation_errors = state.get("validation_errors") or {}
            new_step = state.get("current_step")
            new_status = state.get("status")

            if validation_errors:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Validation failed",
                        "current_step": new_step,
                        "field_errors": validation_errors,
                    },
                )

            if new_step != current_step or new_status != before_status:
                return {
                    "message": "File step submitted successfully",
                    "state": state,
                }

        try:
            final_state = await handle.query("get_state")
        except RPCError as exc:
            _raise_for_temporal_rpc_error(exc)

        raise HTTPException(
            status_code=202,
            detail={
                "message": "File submission accepted and is still processing",
                "state": final_state,
            },
        )

    except WorkflowNotActiveError as exc:
        raise _map_workflow_not_active_error(exc, run)

@router.patch("/cases/{case_id}/steps/{step_code}")
async def edit_case_step(
    case_id: int,
    step_code: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    return await update_case_step_data(
        db,
        case_id=case_id,
        step_code=step_code,
        payload=payload,
    )

@router.get("/cases/{case_id}/documents/{case_document_id}/download-url")
async def get_document_download_url(
    case_id: int,
    case_document_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(CaseDocument).where(
            CaseDocument.id == case_document_id,
            CaseDocument.case_id == case_id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    download_url = get_presigned_download_url(
        bucket_name=document.bucket_name,
        object_key=document.object_key,
        expires_seconds=3600,
    )

    return {
        "case_document_id": document.id,
        "case_id": document.case_id,
        "original_filename": document.original_filename,
        "upload_token": document.upload_token,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "download_url": download_url,
        "expires_in_seconds": 3600,
    }


@router.get("/cases/{case_id}/documents")
async def list_case_documents(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id)
    )
    documents = result.scalars().all()

    return [
        {
            "case_document_id": doc.id,
            "case_id": doc.case_id,
            "step_code": doc.step_code,
            "field_name": doc.field_name,
            "original_filename": doc.original_filename,
            "upload_token": doc.upload_token,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "created_at": doc.created_at,
        }
        for doc in documents
    ]


@router.get("/cases/{case_id}/data", response_model=dict[str, Any])
async def get_case_data(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = await build_case_payload(db=db, case_id=case_id)

    if payload is None:
        raise HTTPException(status_code=404, detail="Case payload not found")

    workflow_config = await get_case_workflow_config(db=db, case_id=case_id)

    if workflow_config is None:
        raise HTTPException(status_code=404, detail="Case Workflow Config not found")

    payload["workflow_config"] = workflow_config

    return payload


@router.get("/cases")
async def get_cases(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    cases = await fetch_cases(db=db)
    return cases