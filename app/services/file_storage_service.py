from __future__ import annotations

from uuid import uuid4

from fastapi import UploadFile

from app.services.object_storage_service import upload_bytes


async def store_upload(
    case_id: int,
    current_step: str,
    field_name: str,
    upload: UploadFile,
) -> dict:
    content = await upload.read()

    safe_original_name = upload.filename or "upload.bin"
    upload_token = uuid4().hex
    stored_filename = f"{upload_token}_{safe_original_name}"

    object_key = (
        f"cases/{case_id}/{current_step}/{field_name}/"
        f"{stored_filename}"
    )

    result = upload_bytes(
        content=content,
        object_key=object_key,
        content_type=upload.content_type,
    )

    return {
        "original_filename": safe_original_name,
        "stored_filename": stored_filename,
        "upload_token": upload_token,
        "content_type": result["content_type"],
        "size_bytes": result["size_bytes"],
        "storage_provider": result["storage_provider"],
        "bucket_name": result["bucket_name"],
        "object_key": result["object_key"],
    }