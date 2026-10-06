"""
Long-term management of a registered habitat bank (diagram steps 27-30):
monitoring reports due over 30 years, verified by an ecologist or the LPA,
with remedial actions when a report fails.

    due -> submitted (bank) -> passed | failed (verifier)
    failed -> remediated once every remedial action is completed

The schedule (MONITORING_YEARS after registration) is created the first time
the monitoring of a completed habitat bank is read.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bng import (
    BNG_HABITAT_BANK_WORKFLOW,
    MONITORING_BANK_ROLES,
    MONITORING_YEARS,
    VERIFIER_ROLES,
    BngMonitoringReport,
    BngRemedialAction,
    BngStepData,
)
from app.models.case_data import Case, CaseUserAccess
from app.models.workflow import CaseWorkflowRun
from app.schemas.bng_requests import MonitoringReportSubmit, MonitoringReportVerify, RemedialActionComplete
from app.services.workflow_roles import act_as, role_label
from app.services.case_user_access_service import get_case_user_access

REGISTER_STEP = "gain_site_register"
BANK_ROLES = MONITORING_BANK_ROLES


def _add_years(start: date, years: int) -> date:
    try:
        return start.replace(year=start.year + years)
    except ValueError:  # 29 February
        return start.replace(year=start.year + years, day=28)


async def _registration_date(db: AsyncSession, bank: Case) -> date | None:
    """The register step's date, else when the bank's workflow completed."""
    data = await db.scalar(
        select(BngStepData.data).where(BngStepData.case_id == bank.id, BngStepData.step_code == REGISTER_STEP)
    )
    raw = (data or {}).get("registration_date")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            pass
    run = await db.scalar(select(CaseWorkflowRun).where(CaseWorkflowRun.case_id == bank.id))
    if run is None or run.status != "completed":
        return None
    return (run.updated_at or datetime.now(timezone.utc)).date()


async def ensure_schedule(db: AsyncSession, bank: Case) -> None:
    """Create the monitoring reports of a registered habitat bank once."""
    if bank.case_type != BNG_HABITAT_BANK_WORKFLOW:
        return
    exists = await db.scalar(
        select(BngMonitoringReport.id).where(BngMonitoringReport.habitat_bank_case_id == bank.id).limit(1)
    )
    if exists is not None:
        return
    start = await _registration_date(db, bank)
    if start is None:
        return
    await db.execute(
        insert(BngMonitoringReport)
        .values([
            {"habitat_bank_case_id": bank.id, "year": year, "due_date": _add_years(start, year), "status": "due"}
            for year in MONITORING_YEARS
        ])
        .on_conflict_do_nothing(constraint="uq_bng_monitoring_reports_bank_year")
    )
    await db.commit()


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def serialize_report(report: BngMonitoringReport, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    return {
        "id": report.id,
        "habitat_bank_case_id": report.habitat_bank_case_id,
        "year": report.year,
        "due_date": _iso(report.due_date),
        "status": report.status,
        "overdue": report.status == "due" and report.due_date < today,
        "habitats_on_track": report.habitats_on_track,
        "condition_summary": report.condition_summary,
        "management_carried_out": report.management_carried_out,
        "submitted_at": _iso(report.submitted_at),
        "submitted_by": str(report.submitted_by) if report.submitted_by else None,
        "submitted_on_behalf": report.submitted_on_behalf,
        "verification_notes": report.verification_notes,
        "verified_at": _iso(report.verified_at),
        "verified_by": str(report.verified_by) if report.verified_by else None,
        "verified_as": report.verified_as,
        "verified_as_label": role_label(report.verified_as),
        "verified_on_behalf": report.verified_on_behalf,
        "remedial_actions": [
            {
                "id": action.id,
                "description": action.description,
                "due_date": _iso(action.due_date),
                "status": action.status,
                "completion_notes": action.completion_notes,
                "completed_at": _iso(action.completed_at),
            }
            for action in report.remedial_actions
        ],
    }


async def bank_reports(db: AsyncSession, bank: Case) -> list[dict[str, Any]]:
    await ensure_schedule(db, bank)
    rows = (await db.execute(
        select(BngMonitoringReport)
        .where(BngMonitoringReport.habitat_bank_case_id == bank.id)
        .options(selectinload(BngMonitoringReport.remedial_actions))
        .order_by(BngMonitoringReport.year)
    )).scalars().all()
    return [serialize_report(row) for row in rows]


def monitoring_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"due": 0, "overdue": 0, "submitted": 0, "passed": 0, "failed": 0, "remediated": 0}
    for report in reports:
        counts[report["status"]] += 1
        if report["overdue"]:
            counts["overdue"] += 1
    next_due = next((r for r in reports if r["status"] == "due"), None)
    open_actions = sum(1 for r in reports for a in r["remedial_actions"] if a["status"] == "open")
    return {
        "scheduled": bool(reports),
        "counts": counts,
        "next_due": {"year": next_due["year"], "due_date": next_due["due_date"]} if next_due else None,
        "open_remedial_actions": open_actions,
    }


# ---------------------------------------------------------
# Actions
# ---------------------------------------------------------

async def _report_for_update(db: AsyncSession, report_id: int, user_id: UUID, permission: str):
    report = await db.scalar(
        select(BngMonitoringReport)
        .where(BngMonitoringReport.id == report_id)
        .options(selectinload(BngMonitoringReport.remedial_actions))
        .with_for_update()
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring report not found")
    access: CaseUserAccess | None = await get_case_user_access(
        db, case_id=report.habitat_bank_case_id, user_id=user_id
    )
    if access is None or not getattr(access, permission, False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring report not found")
    return report, access


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


async def submit_report(db: AsyncSession, *, report_id: int, user_id: UUID, body: MonitoringReportSubmit):
    """The habitat bank reports on its habitats (step 28)."""
    report, access = await _report_for_update(db, report_id, user_id, "can_update")
    capacity = await act_as(
        db, access=access, roles=BANK_ROLES, on_behalf_requested=body.on_behalf,
        action="submit monitoring reports",
    )
    if report.status not in ("due", "submitted"):
        raise _conflict(f"This report is {report.status} and can no longer be changed.")

    report.habitats_on_track = body.habitats_on_track
    report.condition_summary = body.condition_summary.strip()
    report.management_carried_out = (body.management_carried_out or "").strip() or None
    report.status = "submitted"
    report.submitted_at = datetime.now(timezone.utc)
    report.submitted_by = user_id
    report.submitted_on_behalf = capacity["on_behalf"]
    report.updated_by = user_id
    await db.commit()


async def verify_report(db: AsyncSession, *, report_id: int, user_id: UUID, body: MonitoringReportVerify):
    """An ecologist or the LPA checks a submitted report (step 29)."""
    report, access = await _report_for_update(db, report_id, user_id, "can_view")
    capacity = await act_as(
        db, access=access, roles=VERIFIER_ROLES, on_behalf_requested=body.on_behalf,
        action="verify monitoring reports",
    )
    if report.status != "submitted":
        raise _conflict(f"Only a submitted report can be verified; this one is {report.status}.")
    if body.outcome == "failed" and not body.remedial_actions:
        raise HTTPException(
            status_code=422,
            detail={"message": "Validation failed", "field_errors": {
                "remedial_actions": "Add at least one remedial action for a failed report.",
            }},
        )

    report.status = body.outcome
    report.verification_notes = (body.verification_notes or "").strip() or None
    report.verified_at = datetime.now(timezone.utc)
    report.verified_by = user_id
    report.verified_as = capacity["role"]
    report.verified_on_behalf = capacity["on_behalf"]
    report.updated_by = user_id
    if body.outcome == "failed":
        for action in body.remedial_actions:
            report.remedial_actions.append(BngRemedialAction(
                description=action.description.strip(),
                due_date=action.due_date,
                status="open",
                created_by=user_id,
                updated_by=user_id,
            ))
    await db.commit()


async def complete_remedial_action(
    db: AsyncSession, *, action_id: int, user_id: UUID, body: RemedialActionComplete
):
    """The habitat bank completes a remedial action (step 30)."""
    action = await db.get(BngRemedialAction, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remedial action not found")
    report, access = await _report_for_update(db, action.report_id, user_id, "can_update")
    await act_as(
        db, access=access, roles=BANK_ROLES, on_behalf_requested=body.on_behalf,
        action="complete remedial actions",
    )
    action = next(a for a in report.remedial_actions if a.id == action_id)
    if action.status != "open":
        raise _conflict("This remedial action is already completed.")

    action.status = "completed"
    action.completion_notes = body.completion_notes.strip()
    action.completed_at = datetime.now(timezone.utc)
    action.updated_by = user_id
    if report.status == "failed" and all(a.status == "completed" for a in report.remedial_actions):
        report.status = "remediated"
        report.updated_by = user_id
    await db.commit()
