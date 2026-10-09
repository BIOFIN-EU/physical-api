import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from app.core.db import get_db
from app.core.settings import settings
from app.dependencies.gateway_identity import get_request_user_id
from app.models.case_data import CaseDocument, CaseUserAccess, Country
from app.models.workflow import CaseWorkflowRun
from app.schemas.case_workflow import DetectCountryRequest
from app.services.case_state import build_case_payload, get_case_workflow_config, fetch_cases
from app.services.country_detection import build_geometry, detect_country_for_geometry
from app.services.document_files import FILE_RESPONSE_HEADERS, UploadRejected, content_disposition, is_viewable
from app.services.file_storage_service import store_upload
from app.services.object_storage_service import stream_object
from app.services.project_members import record_document_access
from app.services.workflow_config_service import WorkflowNotFoundError
from app.services.workflow_runtime_service import WorkflowRuntimeService, WorkflowNotActiveError
from app.services.case_step_edit_service import update_case_step_data
from app.services.case_step_draft_service import get_case_step_draft, upsert_case_step_draft
from app.schemas.case_step_draft import CaseStepDraftRequest, CaseStepDraftResponse
from app.dependencies.case_access import require_case_permission
from app.services.access_levels import apply_level
from app.services.workflow_config_service import WorkflowConfigService
from app.services.case_delete_service import soft_delete_case, stop_deleted_case_workflow
from app.workflows.actor import ACTOR_KEY
from app.services.workflow_roles import add_creator_role, authorize_step, is_rejection, record_signoff

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

    owner = CaseUserAccess(case_id=case_id, user_id=user_id, is_owner=True)
    apply_level(owner, "manager")
    db.add(owner)
    # The workflow's creator role (e.g. Borrower, Landowner, Developer).
    add_creator_role(
        db, case_id=case_id, workflow_config=WorkflowConfigService().get_workflow(workflow_code), user_id=user_id
    )

    await db.commit()

    return {
        "case_id": case_id,
        "temporal_workflow_id": temporal_workflow_id,
        "workflow_code": workflow_code,
    }


async def case_documents(db: AsyncSession, case_id: int) -> list[dict[str, Any]]:
    """The case's uploaded documents, as the state and documents endpoints return them."""
    result = await db.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id)
    )
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
            "viewable": is_viewable(doc.content_type),
            "notes": doc.notes,
            "created_at": doc.created_at,
        }
        for doc in result.scalars().all()
    ]


async def with_documents(db: AsyncSession, case_id: int, state: dict[str, Any]) -> dict[str, Any]:
    """
    A workflow state with the case's documents, like GET /state. A submit
    returns the next step's state and the page renders it directly, so it
    must carry the documents too (a file step lists what's uploaded).
    """
    return {**state, "documents": await case_documents(db, case_id)}


@router.get("/cases/{case_id}/state")
async def get_case_state(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
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

    return await with_documents(db, case_id, workflow_state)


@router.post("/cases/{case_id}/submit-json")
async def submit_step(
    case_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
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

        # BNG steps with "roles" only (None, and no change, for all others).
        capacity = await authorize_step(db, access=access, step_config=step_config, payload=payload)

        errors = {} if is_rejection(step_config, payload) else _validate_fields(step_config, payload)
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
            # Who is saving, for created_by / updated_by. Set last so a
            # client-supplied value can never override it.
            await handle.signal(
                "submit_step",
                {**payload, ACTOR_KEY: str(access.user_id)},
            )
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

                await record_signoff(db, case_id=case_id, step_code=current_step, user_id=access.user_id, capacity=capacity)
                return {
                    "message": "Step submitted successfully",
                    "state": await with_documents(db, case_id, state),
                }

            try:
                state = await handle.query("get_state")
            except RPCError as exc:
                _raise_for_temporal_rpc_error(exc)

            validation_errors = state.get("validation_errors") or {}
            new_step = state.get("current_step")
            new_status = state.get("status")

            if validation_errors:
                logger.info("Validation errors for case %s: %s", case_id, validation_errors)
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Validation failed",
                        "current_step": new_step,
                        "field_errors": validation_errors,
                    },
                )

            if new_step != current_step or new_status != before_status:
                logger.info(
                    "Step or status changed for case %s: new_step=%s, new_status=%s",
                    case_id,
                    new_step,
                    new_status,
                )
                await record_signoff(db, case_id=case_id, step_code=current_step, user_id=access.user_id, capacity=capacity)
                return {
                    "message": "Step submitted successfully",
                    "state": await with_documents(db, case_id, state),
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
    # The step's other answers (the file steps' document_notes).
    document_notes: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
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

        try:
            file_payload = await store_upload(
                case_id=case_id,
                current_step=current_step,
                field_name=field_name,
                upload=file,
            )
        except UploadRejected as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Validation failed",
                    "current_step": current_step,
                    "field_errors": {field_name: str(exc)},
                },
            )

        signal_payload = {
            "_step_code": current_step,
            "_field_name": field_name,
            field_name: file_payload,
            "document_notes": (document_notes or "").strip() or None,
            ACTOR_KEY: str(access.user_id),
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
                    "state": await with_documents(db, case_id, state),
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
                    "state": await with_documents(db, case_id, state),
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

@router.post("/locations/detect-country")
async def detect_country_for_location(
    payload: DetectCountryRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Stateless helper: detect which seeded country a polygon or point geometry
    falls within, without touching any case. Used by the location editor UI to
    preview the auto-detected country before the step is submitted.
    """
    try:
        geom = build_geometry(
            geometry_wkt=payload.geometry_wkt,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    except Exception:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_geometry",
                "message": "The submitted geometry is not valid WKT.",
            },
        )

    try:
        iso_a2_code, is_multiple = detect_country_for_geometry(geom)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_country_match",
                "message": str(exc),
            },
        )

    result = await db.execute(select(Country).where(Country.code == iso_a2_code))
    country = result.scalar_one_or_none()

    if country is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_country_match",
                "message": f"No seeded country found for detected code '{iso_a2_code}'.",
            },
        )

    return {
        "country_id": country.id,
        "country_code": country.code,
        "country_name": country.name,
        "is_multiple": is_multiple,
    }


@router.patch("/cases/{case_id}/steps/{step_code}")
async def edit_case_step(
    case_id: int,
    step_code: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
):
    # BNG steps with "roles" only (None, and no change, for all others).
    workflow_config = await get_case_workflow_config(db=db, case_id=case_id) or {}
    capacity = await authorize_step(
        db,
        access=access,
        step_config=(workflow_config.get("steps") or {}).get(step_code),
        payload=payload,
    )
    if capacity is not None and capacity.get("decision") == "rejected":
        raise HTTPException(status_code=400, detail="A saved step can't be rejected; edit it instead.")

    result = await update_case_step_data(
        db,
        case_id=case_id,
        step_code=step_code,
        payload=payload,
        actor_user_id=access.user_id,
    )
    await record_signoff(
        db, case_id=case_id, step_code=step_code, user_id=access.user_id, capacity=capacity, decision="edited"
    )
    return result


@router.put("/cases/{case_id}/steps/{step_code}/draft", response_model=CaseStepDraftResponse)
async def save_case_step_draft(
    case_id: int,
    step_code: str,
    payload: CaseStepDraftRequest,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_update")),
) -> dict[str, Any]:
    return await upsert_case_step_draft(
        db,
        case_id=case_id,
        step_code=step_code,
        data=payload.data,
        actor_user_id=access.user_id,
    )


@router.get("/cases/{case_id}/steps/{step_code}/draft", response_model=CaseStepDraftResponse)
async def get_case_step_draft_endpoint(
    case_id: int,
    step_code: str,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    return await get_case_step_draft(
        db,
        case_id=case_id,
        step_code=step_code,
    )


@router.get("/cases/{case_id}/documents/{case_document_id}/content")
async def get_document_content(
    case_id: int,
    case_document_id: int,
    disposition: Literal["inline", "attachment"] = "attachment",
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> StreamingResponse:
    """
    One of the project's files, for anyone who can view the project (checked
    on every request; MinIO itself is never exposed). "inline" shows a PDF or
    image in the browser; any other type is always a download of an opaque
    type, so it can't run in the dashboard. Each view or download goes in the
    project's access history.
    """
    document = await db.scalar(
        select(CaseDocument).where(
            CaseDocument.id == case_document_id,
            CaseDocument.case_id == case_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    inline = disposition == "inline" and is_viewable(document.content_type)
    try:
        chunks = stream_object(bucket_name=document.bucket_name, object_key=document.object_key)
    except S3Error:
        logger.exception("Stored file missing for document %s of case %s", document.id, case_id)
        raise HTTPException(status_code=404, detail="The file is no longer available")

    await record_document_access(
        db, case_id=case_id, user_id=access.user_id, document_id=document.id,
        filename=document.original_filename, how="view" if inline else "download",
    )

    headers = {
        **FILE_RESPONSE_HEADERS,
        "Content-Disposition": content_disposition("inline" if inline else "attachment", document.original_filename),
    }
    if document.size_bytes is not None:
        headers["Content-Length"] = str(document.size_bytes)
    return StreamingResponse(
        chunks,
        media_type=document.content_type if inline else "application/octet-stream",
        headers=headers,
    )


@router.get("/cases/{case_id}/documents")
async def list_case_documents(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict]:
    return await case_documents(db, case_id)


@router.get("/cases/{case_id}/data", response_model=dict[str, Any])
async def get_case_data(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    payload = await build_case_payload(db=db, case_id=case_id)

    if payload is None:
        raise HTTPException(status_code=404, detail="Case payload not found")

    workflow_config = await get_case_workflow_config(db=db, case_id=case_id)

    if workflow_config is None:
        raise HTTPException(status_code=404, detail="Case Workflow Config not found")

    payload["workflow_config"] = workflow_config
    logger.info("Built payload for case %s: %s", case_id, payload)

    return payload


@router.get("/cases")
async def get_cases(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> list[dict[str, Any]]:
    cases = await fetch_cases(db=db, user_id=user_id)
    return cases


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> None:
    """
    Soft-delete a project (requires can_delete). Its data stays in the
    database, but it disappears from the project list and every case endpoint
    returns 404 for it. Deleting it again is a no-op.
    """
    temporal_workflow_id = await soft_delete_case(db, case_id=case_id, user_id=user_id)
    if temporal_workflow_id:
        await stop_deleted_case_workflow(temporal_workflow_id, case_id=case_id)
