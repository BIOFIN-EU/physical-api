"""
Biodiversity Net Gain (BNG) prototype endpoints, mounted at /api/bng.
"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.case_access import require_case_permission
from app.dependencies.gateway_identity import get_request_user_id
from app.models.bng import (
    BNG_DEVELOPMENT_WORKFLOW,
    BNG_HABITAT_BANK_WORKFLOW,
    BNG_ROLE_LABELS,
    BNG_ROLES,
    BNG_WORKFLOWS,
)
from app.models.case_data import Case, CaseUserAccess
from app.schemas.bng import HabitatParcelsPreview
from app.schemas.bng_requests import (
    AllocationSuggestionsRequest,
    BngRolesUpdate,
    MonitoringReportSubmit,
    MonitoringReportVerify,
    OnBehalfRequest,
    RemedialActionComplete,
)
from app.services.bng_marketplace import apply_allocation_action
from app.services.bng_matching import (
    allocation_options,
    allocation_suggestions,
    marketplace,
    user_developments,
)
from app.services.case_user_access_service import get_case_user_access
from app.services.bng_monitoring import (
    bank_reports,
    complete_remedial_action,
    monitoring_summary,
    submit_report,
    verify_report,
)
from app.services.workflow_config_service import WorkflowConfigService
from app.services.bng_roles import (
    case_roles,
    case_signoffs,
    my_capacities,
    set_user_roles,
    user_roles,
    waiting_for_user,
)
from app.services.bng_payload import (
    available_habitat_banks,
    bank_finances,
    case_allocations,
    case_metric,
    case_transactions,
    _role,
    case_name,
    reference_data,
)

router = APIRouter()


async def _bng_case_or_404(db: AsyncSession, case_id: int) -> Case:
    case = await db.get(Case, case_id)
    if case is None or case.case_type not in BNG_WORKFLOWS:
        raise HTTPException(status_code=404, detail="Not a Biodiversity Net Gain project")
    return case


@router.get("/reference-data")
async def get_reference_data(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """Habitat types, conditions and strategic significance for the metric."""
    return await reference_data(db)


@router.get("/habitat-banks")
async def list_habitat_banks(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> list[dict[str, Any]]:
    """
    Marketplace inventory: registered habitat banks with units still
    available, their prices and sites.
    """
    return await available_habitat_banks(db)


async def _development_or_404(db: AsyncSession, case_id: int) -> Case:
    case = await _bng_case_or_404(db, case_id)
    if case.case_type != BNG_DEVELOPMENT_WORKFLOW:
        raise HTTPException(status_code=404, detail="Not a BNG development")
    return case


@router.get("/marketplace")
async def get_marketplace(
    development_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """
    The inventory, the user's developments (to choose from) and, for the
    chosen development, its remaining need and how well each bank covers it.
    A development_id that isn't one of the user's developments is ignored
    (development is null), as for an old or shared link.
    """
    development = None
    if development_id is not None:
        access = await get_case_user_access(db, case_id=development_id, user_id=user_id)
        case = await db.get(Case, development_id) if access is not None and access.can_view else None
        if case is not None and case.case_type == BNG_DEVELOPMENT_WORKFLOW and case.deleted_at is None:
            development = case
    result = await marketplace(db, development)
    result["developments"] = await user_developments(db, user_id)
    return result


@router.get("/cases/{case_id}/allocation-options")
async def get_allocation_options(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """For the reservation step: the units needed and the banks to reserve from."""
    return await allocation_options(db, await _development_or_404(db, case_id))


@router.post("/cases/{case_id}/allocation-suggestions")
async def post_allocation_suggestions(
    case_id: int,
    body: AllocationSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    """Banks ranked by how much of the still-needed units they cover (best first)."""
    return await allocation_suggestions(
        db, await _development_or_404(db, case_id), body.need, body.exclude_bank_ids
    )


@router.get("/cases/{case_id}/metric")
async def get_case_metric(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    return await case_metric(db, await _bng_case_or_404(db, case_id))


@router.post("/cases/{case_id}/metric/preview")
async def preview_case_metric(
    case_id: int,
    payload: HabitatParcelsPreview,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """The metric with one phase's parcels replaced by unsaved ones (live preview)."""
    return await case_metric(
        db,
        await _bng_case_or_404(db, case_id),
        preview_phase=payload.phase,
        preview_parcels=payload.parcels,
    )


@router.get("/cases/{case_id}/allocations")
async def get_case_allocations(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    """A development's allocations, or the requests and allocations to a habitat bank."""
    return await case_allocations(db, await _bng_case_or_404(db, case_id))


@router.get("/cases/{case_id}/transactions")
async def get_case_transactions(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    return await case_transactions(db, await _bng_case_or_404(db, case_id))


@router.get("/cases/{case_id}/financials")
async def get_case_financials(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    case = await _bng_case_or_404(db, case_id)
    if case.case_type != BNG_HABITAT_BANK_WORKFLOW:
        raise HTTPException(status_code=404, detail="Financials are only kept for habitat banks")
    return await bank_finances(db, case)


async def _allocation_action(
    allocation_id: int, action: str, db: AsyncSession, user_id: UUID, body: OnBehalfRequest | None
) -> dict[str, Any]:
    allocation = await apply_allocation_action(
        db, allocation_id=allocation_id, action=action, user_id=user_id,
        on_behalf=bool(body and body.on_behalf),
    )
    return {"id": allocation.id, "status": allocation.status}


@router.post("/allocations/{allocation_id}/accept")
async def accept_allocation(
    allocation_id: int,
    body: OnBehalfRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The habitat bank accepts a request: its units become reserved."""
    return await _allocation_action(allocation_id, "accept", db, user_id, body)


@router.post("/allocations/{allocation_id}/decline")
async def decline_allocation(
    allocation_id: int,
    body: OnBehalfRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The habitat bank declines a request: its units are freed."""
    return await _allocation_action(allocation_id, "decline", db, user_id, body)


@router.post("/allocations/{allocation_id}/release")
async def release_allocation(
    allocation_id: int,
    body: OnBehalfRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    """The development gives back requested or reserved units."""
    return await _allocation_action(allocation_id, "release", db, user_id, body)


# ---------------------------------------------------------
# Phase 3: roles and sign-offs
# ---------------------------------------------------------

@router.get("/roles")
async def list_roles(user_id: UUID = Depends(get_request_user_id)) -> list[dict[str, str]]:
    return [{"code": role, "label": BNG_ROLE_LABELS[role]} for role in BNG_ROLES]


@router.get("/cases/{case_id}/my-access")
async def get_my_access(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """
    The current user's BNG roles, whether they can act on behalf of others,
    and what that lets them do on this project (capacities).
    """
    case = await _bng_case_or_404(db, case_id)
    return {
        "roles": sorted(await user_roles(db, case_id, access.user_id)),
        "can_update": access.can_update,
        "can_record_on_behalf": access.can_assign_users,
        "capacities": await my_capacities(db, case, access),
    }


@router.get("/cases/{case_id}/roles")
async def get_case_roles(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, list[str]]:
    """{user_id: [roles]} of the project's members."""
    await _bng_case_or_404(db, case_id)
    return await case_roles(db, case_id)


@router.put("/cases/{case_id}/roles/{member_id}")
async def put_case_roles(
    case_id: int,
    member_id: UUID,
    body: BngRolesUpdate,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_assign_users")),
) -> dict[str, Any]:
    await _bng_case_or_404(db, case_id)
    roles = await set_user_roles(
        db, case_id=case_id, user_id=member_id, roles=body.roles, actor_user_id=access.user_id
    )
    return {"user_id": str(member_id), "roles": roles}


@router.get("/cases/{case_id}/signoffs")
async def get_case_signoffs(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> list[dict[str, Any]]:
    await _bng_case_or_404(db, case_id)
    return await case_signoffs(db, case_id)


@router.get("/waiting")
async def get_waiting_for_me(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> list[dict[str, Any]]:
    """BNG projects whose current step is for one of the user's roles."""
    return await waiting_for_user(db, user_id)


# ---------------------------------------------------------
# Phase 3: monitoring, verification and remedial actions
# ---------------------------------------------------------

async def _bank_or_404(db: AsyncSession, case_id: int) -> Case:
    case = await _bng_case_or_404(db, case_id)
    if case.case_type != BNG_HABITAT_BANK_WORKFLOW:
        raise HTTPException(status_code=404, detail="Monitoring is only kept for habitat banks")
    return case


@router.get("/cases/{case_id}/monitoring")
async def get_case_monitoring(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """The habitat bank's monitoring schedule and reports (empty until it is registered)."""
    reports = await bank_reports(db, await _bank_or_404(db, case_id))
    return {"summary": monitoring_summary(reports), "reports": reports}


@router.post("/monitoring-reports/{report_id}/submit")
async def post_monitoring_report(
    report_id: int,
    body: MonitoringReportSubmit,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    await submit_report(db, report_id=report_id, user_id=user_id, body=body)
    return {"id": report_id, "status": "submitted"}


@router.post("/monitoring-reports/{report_id}/verify")
async def post_monitoring_verification(
    report_id: int,
    body: MonitoringReportVerify,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    await verify_report(db, report_id=report_id, user_id=user_id, body=body)
    return {"id": report_id, "status": body.outcome}


@router.post("/remedial-actions/{action_id}/complete")
async def post_remedial_action_complete(
    action_id: int,
    body: RemedialActionComplete,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_request_user_id),
) -> dict[str, Any]:
    await complete_remedial_action(db, action_id=action_id, user_id=user_id, body=body)
    return {"id": action_id, "status": "completed"}


# ---------------------------------------------------------
# Phase 3: reporting (diagram step 32)
# ---------------------------------------------------------

@router.get("/cases/{case_id}/report")
async def get_case_report(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    access: CaseUserAccess = Depends(require_case_permission("can_view")),
) -> dict[str, Any]:
    """Everything about a BNG project in one summary, for the printable report."""
    case = await _bng_case_or_404(db, case_id)
    report: dict[str, Any] = {
        "case_id": case.id,
        "case_type": case.case_type,
        "role": _role(case.case_type),
        "name": await case_name(db, case.id),
        "metric": await case_metric(db, case),
        "allocations": await case_allocations(db, case),
        "transactions": await case_transactions(db, case),
        "signoffs": await case_signoffs(db, case.id),
        "roles": await case_roles(db, case.id),
        "step_titles": {
            code: step.get("title")
            for code, step in (WorkflowConfigService().get_workflow(case.case_type).get("steps") or {}).items()
        },
    }
    if case.case_type == BNG_HABITAT_BANK_WORKFLOW:
        reports = await bank_reports(db, case)
        report["financials"] = await bank_finances(db, case)
        report["monitoring"] = {"summary": monitoring_summary(reports), "reports": reports}
    return report
