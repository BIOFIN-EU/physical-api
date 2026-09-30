"""
JSON-LD export of a project (BIOFIN-EU ontology), mounted at /api/semantic.
See app/semantic/README.md.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.dependencies.case_access import require_case_permission
from app.models.case_data import CaseUserAccess
from app.semantic.service import context, extension_ontology, project_jsonld

router = APIRouter()


@router.get("/projects/{case_id}")
async def export_project(
    case_id: int,
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> Response:
    """The project as one JSON-LD document, downloaded as biofin-project-<id>.jsonld."""
    document: dict[str, Any] = await run_in_threadpool(project_jsonld, case_id)
    if "@type" not in document:
        raise HTTPException(status_code=404, detail="Project not found")
    return JSONResponse(
        document,
        media_type="application/ld+json",
        headers={"Content-Disposition": f'attachment; filename="biofin-project-{case_id}.jsonld"'},
    )


@router.get("/ontology/ext")
async def get_extension_ontology() -> Response:
    """The dashboard's extensions to the BIOFIN-EU ontology (Turtle)."""
    return Response(extension_ontology(), media_type="text/turtle")


@router.get("/context")
async def get_context() -> Response:
    """The JSON-LD context the export uses."""
    return JSONResponse({"@context": context()}, media_type="application/ld+json")
