"""
Uploaded files: which uploads are accepted (type from content, size,
filename), and serving them back through the API with the project's access
rules, safe headers, and a record in the access history.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_db
from app.core.settings import settings
from app.main import app
from app.models.case_data import CaseAccessAuditLog, CaseDocument, CaseUserAccess
from app.services.document_files import (
    CSV,
    DOCX,
    JPEG,
    MAX_UPLOAD_BYTES,
    PDF,
    PNG,
    XLSX,
    UploadRejected,
    check_upload,
    content_disposition,
    safe_filename,
)
from app.services.object_storage_service import ensure_bucket_exists, get_minio_client, upload_bytes
from app.services.project_members import access_history
from app.workflows.activities import SessionLocal

from tests.test_bng import cases  # noqa: F401 (fixture)
from tests.test_case_soft_delete import _run

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _office(part: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(f"{part}/document.xml", "<x/>")
    return buffer.getvalue()


# ---------- what may be uploaded ----------

@pytest.mark.parametrize("name,content,expected", [
    ("report.pdf", PDF_BYTES, PDF),
    ("Site Photo.PNG", PNG_BYTES, PNG),
    ("photo.jpg", JPEG_BYTES, JPEG),
    ("photo.jpeg", JPEG_BYTES, JPEG),
    ("plan.docx", _office("word"), DOCX),
    ("budget.xlsx", _office("xl"), XLSX),
    ("parcels.csv", "name;ha\nNoordveld;2,5\n".encode("utf-8"), CSV),
    ("légende.csv", "naam;waarde\nhéé;1\n".encode("cp1252"), CSV),
])
def test_allowed_uploads(name, content, expected):
    checked = check_upload(name, content)
    assert checked.content_type == expected
    assert checked.filename == name


@pytest.mark.parametrize("name,content,message", [
    ("page.html", b"<html><script>alert(1)</script></html>", "Upload a PDF"),
    ("drawing.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "Upload a PDF"),
    ("no-extension", PDF_BYTES, "Upload a PDF"),
    ("fake.pdf", b"<html><script>alert(1)</script></html>", "doesn't match"),
    ("fake.png", PDF_BYTES, "doesn't match"),
    ("fake.docx", b"PK\x03\x04not really a zip", "doesn't match"),
    ("workbook.docx", _office("xl"), "doesn't match"),
    ("binary.csv", b"\x00\x01\x02", "doesn't match"),
    ("empty.pdf", b"", "empty"),
    ("huge.pdf", PDF_BYTES + b"0" * MAX_UPLOAD_BYTES, "larger than 20 MB"),
])
def test_refused_uploads(name, content, message):
    with pytest.raises(UploadRejected) as exc:
        check_upload(name, content)
    assert message in str(exc.value)


def test_safe_filenames():
    assert safe_filename("C:\\Users\\me\\report.pdf") == "report.pdf"
    assert safe_filename("../../etc/passwd.csv") == "passwd.csv"
    assert safe_filename('a"b<c>|d\r\n.pdf') == "a_b_c__d.pdf"
    assert safe_filename("") == safe_filename(None) == "upload"
    long = safe_filename("x" * 300 + ".pdf")
    assert len(long) == 150 and long.endswith(".pdf")


def test_content_disposition_keeps_the_name_safely():
    header = content_disposition("attachment", 'Plan "final" – Noordveld.pdf')
    assert header.startswith('attachment; filename="Plan _final_  Noordveld.pdf"')
    assert "filename*=UTF-8''Plan%20%22final%22%20%E2%80%93%20Noordveld.pdf" in header


# ---------- serving files back ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", "test-secret")

    # Each TestClient runs the app in a new event loop: give it connections
    # that aren't pooled across loops.
    async def fresh_db():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = fresh_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _as(user: uuid.UUID, *roles: str) -> dict:
    headers = {"X-User-Id": str(user), "X-Internal-Secret": "test-secret"}
    if roles:
        headers["X-User-Roles"] = ",".join(roles)
    return headers


def _member(case_id: int) -> uuid.UUID:
    user = uuid.uuid4()
    with SessionLocal() as session:
        session.add(CaseUserAccess(
            case_id=case_id, user_id=user, can_view=True, can_update=False, can_delete=False, can_assign_users=False,
        ))
        session.commit()
    return user


_UPLOADED: list[str] = []


@pytest.fixture(autouse=True)
def _remove_test_files():
    """MinIO isn't a throwaway copy like the test database: delete what the tests stored."""
    yield
    client = get_minio_client()
    while _UPLOADED:
        client.remove_object(settings.MINIO_BUCKET, _UPLOADED.pop())


def _document(case_id: int, name: str, content: bytes, content_type: str) -> int:
    ensure_bucket_exists()
    stored = upload_bytes(content=content, object_key=f"tests/{uuid.uuid4().hex}/{name}", content_type=content_type)
    _UPLOADED.append(stored["object_key"])
    with SessionLocal() as session:
        row = CaseDocument(
            case_id=case_id, step_code="supporting_document", field_name="supporting_document",
            original_filename=name, stored_filename=name, upload_token=uuid.uuid4().hex[:32],
            content_type=content_type, size_bytes=len(content), storage_provider="minio",
            bucket_name=stored["bucket_name"], object_key=stored["object_key"],
        )
        session.add(row)
        session.commit()
        return row.id


def _document_entries(case_id: int) -> list[tuple[str, dict]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(CaseAccessAuditLog.action, CaseAccessAuditLog.details)
            .where(CaseAccessAuditLog.case_id == case_id, CaseAccessAuditLog.action.like("document_%"))
            .order_by(CaseAccessAuditLog.id)
        ).all()
    return [(action, json.loads(details)) for action, details in rows]


def test_a_member_views_a_pdf_in_the_browser(cases, client):  # noqa: F811
    case_id = cases("use_case_2_v1")
    document = _document(case_id, "Survey – May.pdf", PDF_BYTES, PDF)
    member = _member(case_id)

    response = client.get(f"/api/case_workflow/cases/{case_id}/documents/{document}/content?disposition=inline", headers=_as(member))
    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == PDF
    assert response.headers["content-disposition"].startswith('inline; filename="Survey  May.pdf"')
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("sandbox")
    assert response.headers["cache-control"] == "private, no-store"

    assert _document_entries(case_id) == [("document_viewed", {"file": "Survey – May.pdf", "document_id": document})]
    history = _run(lambda db: access_history(db, case_id=case_id))
    assert history[0]["action_label"] == "Viewed a document" and history[0]["detail"] == "Survey – May.pdf"


def test_other_types_are_always_downloaded(cases, client):  # noqa: F811
    case_id = cases("use_case_2_v1")
    # Uploaded before the type checks: whatever the browser claimed.
    document = _document(case_id, "page.html", b"<script>alert(1)</script>", "text/html")
    member = _member(case_id)

    response = client.get(f"/api/case_workflow/cases/{case_id}/documents/{document}/content?disposition=inline", headers=_as(member))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert _document_entries(case_id) == [("document_downloaded", {"file": "page.html", "document_id": document})]


def test_repeat_opens_are_recorded_once(cases, client):  # noqa: F811
    case_id = cases("use_case_2_v1")
    document = _document(case_id, "map.png", PNG_BYTES, PNG)
    member = _member(case_id)
    url = f"/api/case_workflow/cases/{case_id}/documents/{document}/content"

    for _ in range(3):
        assert client.get(f"{url}?disposition=inline", headers=_as(member)).status_code == 200
    assert client.get(url, headers=_as(member)).status_code == 200
    assert [action for action, _ in _document_entries(case_id)] == ["document_viewed", "document_downloaded"]


def test_only_people_with_access_get_the_file(cases, client):  # noqa: F811
    case_id = cases("use_case_2_v1")
    other_case = cases("use_case_2_v1")
    document = _document(case_id, "report.pdf", PDF_BYTES, PDF)
    url = f"/api/case_workflow/cases/{case_id}/documents/{document}/content"

    outsider = uuid.uuid4()
    assert client.get(url, headers=_as(outsider)).status_code in (403, 404)

    # A member of another project can't reach it through their own project.
    other_member = _member(other_case)
    response = client.get(f"/api/case_workflow/cases/{other_case}/documents/{document}/content", headers=_as(other_member))
    assert response.status_code == 404

    # An administrator can, for support, and it's recorded.
    admin = uuid.uuid4()
    assert client.get(url, headers=_as(admin, "admin")).status_code == 200
    assert _document_entries(case_id) == [("document_downloaded", {"file": "report.pdf", "document_id": document})]
    assert _document_entries(other_case) == []


def test_a_missing_document_is_not_found(cases, client):  # noqa: F811
    case_id = cases("use_case_2_v1")
    member = _member(case_id)
    response = client.get(f"/api/case_workflow/cases/{case_id}/documents/999999999/content", headers=_as(member))
    assert response.status_code == 404
