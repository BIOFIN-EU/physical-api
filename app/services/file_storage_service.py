from __future__ import annotations

from uuid import uuid4

from fastapi import UploadFile

from app.services.document_files import MAX_UPLOAD_BYTES, UploadRejected, check_upload
from app.services.object_storage_service import upload_bytes


async def store_upload(
    case_id: int,
    current_step: str,
    field_name: str,
    upload: UploadFile,
) -> dict:
    """
    Check and store an uploaded file. Raises UploadRejected (with a message
    for the user) for a file of the wrong type or over the size limit.
    """
    # One byte over the limit is enough to know it's too large.
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    checked = check_upload(upload.filename, content)

    upload_token = uuid4().hex
    stored_filename = f"{upload_token}_{checked.filename}"

    object_key = (
        f"cases/{case_id}/{current_step}/{field_name}/"
        f"{stored_filename}"
    )

    result = upload_bytes(
        content=content,
        object_key=object_key,
        content_type=checked.content_type,
    )

    return {
        "original_filename": checked.filename,
        "stored_filename": stored_filename,
        "upload_token": upload_token,
        "content_type": result["content_type"],
        "size_bytes": result["size_bytes"],
        "storage_provider": result["storage_provider"],
        "bucket_name": result["bucket_name"],
        "object_key": result["object_key"],
    }


__all__ = ["UploadRejected", "store_upload"]
