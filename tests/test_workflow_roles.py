"""
Workflow roles for every pathway: the role config, the financing pathways'
step roles, members (levels, roles, emails), ownership transfer and the
administrators' support access.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.dependencies.case_access import require_case_permission
from app.dependencies.gateway_identity import RequestIdentity
from app.models.case_data import CaseAccessAuditLog, CaseUserAccess, CaseWorkflowRole
from app.services import project_members
from app.services.access_levels import level_of
from app.services.case_state import fetch_all_cases
from app.services.case_user_access_service import transfer_ownership
from app.services.project_members import add_member, change_member, mask_email, project_members as members_of
from app.services.workflow_config_service import WorkflowConfigService
from app.services.workflow_roles import (
    RoleConfigError,
    authorize_step,
    validate_role_config,
    workflow_roles,
)
from app.workflows.activities import SessionLocal

from tests.test_bng import cases  # noqa: F401 (fixture)
from tests.test_case_soft_delete import _run

FINANCING = ("private_lending_v1", "use_case_2_v1")


def _config(code: str) -> dict:
    return WorkflowConfigService().get_workflow(code)


def _member(case_id: int, *roles: str, level: str = "editor", owner: bool = False) -> uuid.UUID:
    user = uuid.uuid4()
    flags = {"viewer": (True, False, False, False), "editor": (True, True, False, False), "manager": (True, True, True, True)}
    view, update, delete, assign = flags["manager" if owner else level]
    with SessionLocal() as session:
        session.add(CaseUserAccess(
            case_id=case_id, user_id=user, is_owner=owner,
            can_view=view, can_update=update, can_delete=delete, can_assign_users=assign,
        ))
        for role in roles:
            session.add(CaseWorkflowRole(case_id=case_id, user_id=user, role=role))
        session.commit()
    return user


def _access(case_id: int, user: uuid.UUID) -> CaseUserAccess:
    with SessionLocal() as session:
        return session.scalar(
            select(CaseUserAccess).where(CaseUserAccess.case_id == case_id, CaseUserAccess.user_id == user)
        )


@pytest.fixture
def people(monkeypatch):
    """auth-api's details for users (no auth-api in tests)."""
    known: dict[str, dict] = {}

    async def lookup(user_ids):
        return {str(u): known[str(u)] for u in user_ids if str(u) in known}

    async def resolve(email):
        for user_id, user in known.items():
            if user["email"] == email:
                return uuid.UUID(user_id)
        raise HTTPException(status_code=404, detail="No account found for this email address.")

    monkeypatch.setattr(project_members, "lookup_users", lookup)
    monkeypatch.setattr(project_members, "resolve_user_id_by_email", resolve)

    def add(user_id, email, name=None):
        known[str(user_id)] = {"id": str(user_id), "email": email, "display_name": name}
        return user_id
    return add


# ---------- config ----------

def test_the_shipped_config_is_valid():
    validate_role_config(WorkflowConfigService().load_all())


def test_role_typos_are_caught():
    config = copy.deepcopy(WorkflowConfigService().load_all())
    config["workflows"]["private_lending_v1"]["steps"]["financial"]["roles"] = ["borower"]
    config["workflows"]["bng_development_v1"]["creator_role"] = "landowner"
    with pytest.raises(RoleConfigError) as exc:
        validate_role_config(config)
    assert "private_lending_v1.financial: role 'borower'" in str(exc.value)
    assert "bng_development_v1: creator_role 'landowner'" in str(exc.value)


def test_each_pathway_offers_its_own_roles():
    assert [r["code"] for r in workflow_roles(_config("bng_development_v1"))] == ["developer", "ecologist", "lpa"]
    financing = {r["code"]: r for r in workflow_roles(_config("private_lending_v1"))}
    assert list(financing) == ["borrower", "funder", "intermediary"]
    assert financing["funder"]["label"] == "Funder" and financing["funder"]["steps"] == []
    assert {s["code"] for s in financing["intermediary"]["steps"]} == {"basic_info", "financial"}


# ---------- financing pathways ----------

@pytest.mark.parametrize("workflow", FINANCING)
def test_financing_steps_follow_the_roles(cases, workflow):  # noqa: F811
    case_id = cases(workflow)
    steps = _config(workflow)["steps"]
    borrower, intermediary, funder = _member(case_id, "borrower"), _member(case_id, "intermediary"), _member(case_id, "funder")

    def may(user, step):
        try:
            _run(lambda db: authorize_step(db, access=_access(case_id, user), step_config=steps[step], payload={}))
            return True
        except HTTPException as exc:
            assert exc.status_code == 403
            return False

    shared = "financial" if workflow == "private_lending_v1" else "funding_requirements"
    assert may(borrower, "location") and may(borrower, shared)
    assert may(intermediary, shared) and not may(intermediary, "location")
    assert not may(funder, shared) and not may(funder, "location")


# ---------- members ----------

def test_adding_a_member_with_roles_makes_them_an_editor(cases, people):  # noqa: F811
    case_id = cases("private_lending_v1")
    owner = people(_member(case_id, "borrower", owner=True), "owner@bank.example", "Olga Owner")
    newcomer = people(uuid.uuid4(), "ian@advisers.example", "Ian Intermediary")
    _run(lambda db: add_member(
        db, case_id=case_id, actor=_access(case_id, owner), email="ian@advisers.example",
        level="viewer", roles=["intermediary"], workflow_config=_config("private_lending_v1"),
    ))
    assert level_of(_access(case_id, newcomer)) == "editor"

    with pytest.raises(HTTPException) as exc:  # not a role of this pathway
        _run(lambda db: change_member(
            db, case_id=case_id, actor=_access(case_id, owner), user_id=newcomer, level=None,
            roles=["ecologist"], workflow_config=_config("private_lending_v1"),
        ))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:  # roles need at least editor
        _run(lambda db: change_member(
            db, case_id=case_id, actor=_access(case_id, owner), user_id=newcomer, level="viewer",
            roles=None, workflow_config=_config("private_lending_v1"),
        ))
    assert exc.value.status_code == 422


def test_managers_see_emails_others_see_domains(cases, people):  # noqa: F811
    case_id = cases("use_case_2_v1")
    owner = people(_member(case_id, "borrower", owner=True), "olga@bank.example", "Olga Owner")
    viewer = people(_member(case_id, level="viewer"), "victor@funds.example")
    config = _config("use_case_2_v1")

    managed = _run(lambda db: members_of(db, case_id=case_id, viewer=_access(case_id, owner), workflow_config=config))
    assert {m["email"] for m in managed["members"]} == {"olga@bank.example", "victor@funds.example"}
    assert managed["members"][0]["level"] == "owner" and managed["members"][0]["roles"] == ["borrower"]
    assert managed["can_manage"] and [r["code"] for r in managed["roles"]] == ["borrower", "funder", "intermediary"]

    seen = _run(lambda db: members_of(db, case_id=case_id, viewer=_access(case_id, viewer), workflow_config=config))
    assert {m["email"] for m in seen["members"]} == {"o•••@bank.example", "v•••@funds.example"}
    assert not seen["can_manage"]
    assert mask_email(None) is None


def test_ownership_can_be_handed_over(cases):  # noqa: F811
    case_id = cases("private_lending_v1")
    owner, editor = _member(case_id, owner=True), _member(case_id)
    with pytest.raises(HTTPException):
        _run(lambda db: transfer_ownership(db, case_id=case_id, owner=_access(case_id, editor), new_owner_id=owner))
    _run(lambda db: transfer_ownership(db, case_id=case_id, owner=_access(case_id, owner), new_owner_id=editor))
    assert level_of(_access(case_id, editor)) == "owner"
    assert level_of(_access(case_id, owner)) == "manager"


# ---------- administrators ----------

def test_administrators_can_read_any_project(cases):  # noqa: F811
    case_id = cases("private_lending_v1")
    _member(case_id, owner=True)
    admin = RequestIdentity(user_id=uuid.uuid4(), roles=["user", "admin"], permissions=[])
    user = RequestIdentity(user_id=uuid.uuid4(), roles=["user"], permissions=[])

    view = require_case_permission("can_view")
    access = _run(lambda db: view(case_id=case_id, db=db, identity=admin))
    assert access.can_view and not access.can_update and access.id is None
    _run(lambda db: view(case_id=case_id, db=db, identity=admin))  # again: recorded once a day

    with SessionLocal() as session:
        visits = session.scalars(select(CaseAccessAuditLog.action).where(
            CaseAccessAuditLog.case_id == case_id, CaseAccessAuditLog.action == "admin_viewed"
        )).all()
    assert visits == ["admin_viewed"]

    with pytest.raises(HTTPException) as exc:  # read only
        _run(lambda db: require_case_permission("can_update")(case_id=case_id, db=db, identity=admin))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:  # not for other users
        _run(lambda db: view(case_id=case_id, db=db, identity=user))
    assert exc.value.status_code == 403

    listed = _run(lambda db: fetch_all_cases(db, admin.user_id))
    assert any(c["caseId"] == case_id and c["isMember"] is False for c in listed)
