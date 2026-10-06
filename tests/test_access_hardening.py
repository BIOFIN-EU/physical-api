"""
Who can call this API and change project access: the gateway secret,
owner protection, member errors, the access audit log, and closing an
account.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.settings import settings
from app.main import app
from app.models.bng import BngCaseRole
from app.models.case_data import Case, CaseAccessAuditLog, CaseUserAccess
from app.services.account_closure_service import release_closed_account
from app.services.bng_roles import set_user_roles
from app.services.case_user_access_service import (
    create_case_user_access,
    delete_case_user_access,
    update_case_user_access,
)
from app.workflows.activities import SessionLocal

from tests.test_bng import cases  # noqa: F401 (fixture)
from tests.test_case_soft_delete import _run


def _member(case_id: int, *, owner: bool = False, manager: bool = False) -> uuid.UUID:
    user_id = uuid.uuid4()
    with SessionLocal() as session:
        session.add(CaseUserAccess(
            case_id=case_id, user_id=user_id, case_role="borrower", is_owner=owner,
            can_view=True, can_update=owner or manager, can_delete=owner, can_assign_users=owner or manager,
        ))
        session.commit()
    return user_id


def _access(case_id: int, user_id: uuid.UUID) -> CaseUserAccess | None:
    with SessionLocal() as session:
        return session.scalar(
            select(CaseUserAccess).where(CaseUserAccess.case_id == case_id, CaseUserAccess.user_id == user_id)
        )


def _audit(case_id: int) -> list[tuple[str, str | None]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(CaseAccessAuditLog.action, CaseAccessAuditLog.details)
            .where(CaseAccessAuditLog.case_id == case_id)
            .order_by(CaseAccessAuditLog.id)
        ).all()
    return [tuple(row) for row in rows]


# ---------- only the gateway may call the API ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", "test-secret")
    return TestClient(app)


def test_requests_without_the_gateway_secret_are_refused(client):
    user = {"X-User-Id": str(uuid.uuid4())}
    assert client.get("/api/status/api_status", headers=user).status_code == 401
    assert client.get("/api/status/api_status", headers={**user, "X-Internal-Secret": "wrong"}).status_code == 401
    assert client.get("/api/status/api_status", headers={**user, "X-Internal-Secret": "test-secret"}).status_code == 200
    # The API's description stays readable.
    assert client.get("/openapi.json").status_code == 200


def test_everything_is_refused_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", None)
    assert client.get("/api/status/api_status", headers={"X-Internal-Secret": ""}).status_code == 401


# ---------- members ----------

def test_owner_access_cannot_be_changed(case_id):
    owner, manager = _member(case_id, owner=True), _member(case_id, manager=True)
    with pytest.raises(HTTPException) as exc:
        _run(lambda db: update_case_user_access(
            db, case_id=case_id, user_id=owner, actor_user_id=manager, can_assign_users=False
        ))
    assert exc.value.status_code == 409
    assert _access(case_id, owner).can_assign_users


def test_adding_an_existing_member_is_a_conflict(case_id):
    owner, member = _member(case_id, owner=True), _member(case_id)
    with pytest.raises(HTTPException) as exc:
        _run(lambda db: create_case_user_access(
            db, case_id=case_id, user_id=member, actor_user_id=owner, case_role="funder",
            can_view=True, can_update=False, can_delete=False, can_assign_users=False,
        ))
    assert exc.value.status_code == 409


def test_access_changes_record_what_changed(case_id):
    owner, member = _member(case_id, owner=True), _member(case_id)
    _run(lambda db: update_case_user_access(db, case_id=case_id, user_id=member, actor_user_id=owner, can_update=True))
    action, details = _audit(case_id)[-1]
    assert action == "user_access_updated"
    change = json.loads(details)
    assert change["before"]["can_update"] is False and change["after"]["can_update"] is True


def test_role_changes_are_audited_and_removed_with_the_member(cases):  # noqa: F811
    case_id = cases("bng_habitat_bank_v1")
    owner, member = _member(case_id, owner=True), _member(case_id)
    _run(lambda db: set_user_roles(db, case_id=case_id, user_id=member, roles=["ecologist", "lpa"], actor_user_id=owner))
    _run(lambda db: set_user_roles(db, case_id=case_id, user_id=member, roles=["lpa"], actor_user_id=owner))
    roles = [(a, d) for a, d in _audit(case_id) if a.startswith("role_")]
    assert roles == [("role_assigned", "ecologist"), ("role_assigned", "lpa"), ("role_removed", "ecologist")]

    _run(lambda db: delete_case_user_access(db, case_id=case_id, user_id=member, actor_user_id=owner))
    with SessionLocal() as session:
        left = session.scalars(select(BngCaseRole).where(BngCaseRole.case_id == case_id, BngCaseRole.user_id == member)).all()
    assert left == []


# ---------- closing an account ----------

def test_closing_an_account_hands_projects_over(cases):  # noqa: F811
    shared, solo, joined = cases("private_lending_v1"), cases("private_lending_v1"), cases("private_lending_v1")
    leaving = uuid.uuid4()
    with SessionLocal() as session:
        for case_id in (shared, solo):
            session.add(CaseUserAccess(
                case_id=case_id, user_id=leaving, case_role="borrower", is_owner=True,
                can_view=True, can_update=True, can_delete=True, can_assign_users=True,
            ))
        session.commit()
    viewer, manager = _member(shared), _member(shared, manager=True)
    _member(joined, owner=True)
    with SessionLocal() as session:
        session.add(CaseUserAccess(
            case_id=joined, user_id=leaving, case_role="funder", is_owner=False,
            can_view=True, can_update=False, can_delete=False, can_assign_users=False,
        ))
        session.commit()

    result = _run(lambda db: release_closed_account(db, user_id=leaving))

    # The manager (not the earlier viewer) becomes the owner, with full access.
    assert result["transferred"] == {shared: str(manager)}
    new_owner = _access(shared, manager)
    assert new_owner.is_owner and new_owner.can_delete
    assert not _access(shared, viewer).is_owner
    assert ("ownership_transferred" in [a for a, _ in _audit(shared)])
    # A project no one else could open is deleted (soft).
    assert result["deleted"] == [solo]
    with SessionLocal() as session:
        assert session.get(Case, solo).deleted_at is not None
        assert session.get(Case, joined).deleted_at is None
    # They are gone from every project.
    assert sorted(result["removed_from"]) == sorted([shared, solo, joined])
    assert all(_access(c, leaving) is None for c in (shared, solo, joined))

    # Repeating it is harmless.
    again = _run(lambda db: release_closed_account(db, user_id=leaving))
    assert again["removed_from"] == []
