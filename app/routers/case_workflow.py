import asyncio

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from pathlib import Path
from uuid import uuid4
from app.core.db import get_db
from app.core.settings import settings
from app.services.workflow_runtime_service import WorkflowRuntimeService
from app.services.workflow_config_service import WorkflowNotFoundError
from app.services.file_storage_service import store_upload
from sqlalchemy import select

from app.models.case_data import CaseDocument
from app.services.object_storage_service import get_presigned_download_url

router = APIRouter()


def _validate_fields(step_config: dict, payload: dict) -> dict:
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
) -> dict:
    service = WorkflowRuntimeService(db)

    try:
        workflow_id = await service.start_workflow(
            workflow_code=workflow_code,
        )
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_code}' not found",
        )

    case_id = int(workflow_id.replace("case-", ""))

    return {
        "case_id": case_id,
        "workflow_id": workflow_id,
        "workflow_code": workflow_code,
    }


@router.get("/cases/{case_id}/state")
async def get_case_state(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await Client.connect(settings.TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(f"case-{case_id}")
    workflow_state = await handle.query("get_state")

    result = await db.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id)
    )
    documents = result.scalars().all()

    workflow_state["documents"] = [
        {
            "case_document_id": doc.case_document_id,
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
async def submit_step(case_id: int, payload: dict) -> dict:
    client = await Client.connect(settings.TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(f"case-{case_id}")

    before_state = await handle.query("get_state")
    current_step = before_state.get("current_step")
    step_config = before_state.get("step", {})

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

    await handle.signal("submit_step", payload)

    for _ in range(10):
        await asyncio.sleep(0.2)
        state = await handle.query("get_state")

        if state.get("current_step") != current_step or state.get("validation_errors"):
            return {
                "message": "Step submitted successfully",
                "state": state,
            }

    return {
        "message": "Step submitted",
        "state": await handle.query("get_state"),
    }


@router.post("/cases/{case_id}/submit-file")
async def submit_file_step(
    case_id: int,
    field_name: str,
    file: UploadFile = File(...),
) -> dict:
    client = await Client.connect(settings.TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(f"case-{case_id}")

    before_state = await handle.query("get_state")
    current_step = before_state.get("current_step")
    step_config = before_state.get("step", {})

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

    await handle.signal("submit_step", signal_payload)

    for _ in range(10):
        await asyncio.sleep(0.2)
        state = await handle.query("get_state")

        if state.get("current_step") != current_step or state.get("validation_errors"):
            return {
                "message": "File step submitted successfully",
                "state": state,
            }

    return {
        "message": "File step submitted",
        "state": await handle.query("get_state"),
    }

@router.get("/cases/{case_id}/documents/{case_document_id}/download-url")
async def get_document_download_url(
    case_id: int,
    case_document_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(CaseDocument).where(
            CaseDocument.case_document_id == case_document_id,
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
        "case_document_id": document.case_document_id,
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
            "case_document_id": doc.case_document_id,
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