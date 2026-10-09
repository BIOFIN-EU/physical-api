"""
Uploaded documents in the workflow state: a step submit returns the next
step's state with the case's documents (the page renders it directly, and a
file step lists what's already uploaded), and a file step's notes are kept.
"""
from __future__ import annotations

from app.routers.case_workflow import case_documents, with_documents
from app.services.case_state import serialize_document
from app.models.case_data import CaseDocument
from app.workflows.activities import SessionLocal, save_supporting_document_step
from sqlalchemy import select

from tests.test_bng import cases  # noqa: F401 (fixture)
from tests.test_case_soft_delete import _run


def _upload(case_id: int, notes: str | None = None) -> None:
    save_supporting_document_step(case_id, {
        "_step_code": "supporting_document",
        "_field_name": "supporting_document",
        "supporting_document": {
            "original_filename": "survey.pdf",
            "stored_filename": "abc.pdf",
            "upload_token": "tok123",
            "content_type": "application/pdf",
            "size_bytes": 1024,
            "storage_provider": "minio",
            "bucket_name": "case-documents",
            "object_key": f"cases/{case_id}/abc.pdf",
        },
        "document_notes": notes,
    })


def test_a_state_without_documents_gets_an_empty_list(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    state = {"case_id": case_id, "current_step": "supporting_document", "status": "in_progress"}
    result = _run(lambda db: with_documents(db, case_id, state))
    assert result == {**state, "documents": []}
    assert "documents" not in state  # the given state isn't changed


def test_submit_state_lists_uploads_with_their_notes(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    _upload(case_id, notes="Habitat survey, May 2026")

    result = _run(lambda db: with_documents(db, case_id, {"current_step": None, "status": "completed"}))
    [document] = result["documents"]
    assert document["step_code"] == "supporting_document" and document["field_name"] == "supporting_document"
    assert document["original_filename"] == "survey.pdf"
    assert document["notes"] == "Habitat survey, May 2026"
    assert _run(lambda db: case_documents(db, case_id)) == result["documents"]

    # The project page's data has the notes too.
    with SessionLocal() as session:
        row = session.execute(select(CaseDocument).where(CaseDocument.case_id == case_id)).scalar_one()
        assert serialize_document(row)["notes"] == "Habitat survey, May 2026"


def test_replacing_a_file_replaces_its_notes(cases):  # noqa: F811
    case_id = cases("use_case_2_v1")
    _upload(case_id, notes="First version")
    _upload(case_id, notes=None)
    [document] = _run(lambda db: case_documents(db, case_id))
    assert document["notes"] is None
