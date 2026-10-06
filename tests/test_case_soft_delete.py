"""
Soft delete of cases: deleted cases keep their rows but are hidden from the
project list and from every endpoint guarded by require_case_permission.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.settings import settings
from app.dependencies.case_access import require_case_permission
from app.dependencies.gateway_identity import RequestIdentity
from app.models.case_data import Case, CaseUserAccess
from app.services.case_delete_service import soft_delete_case
from app.services.case_state import fetch_cases
from app.services.case_user_access_service import get_case_user_access
from app.workflows.activities import SessionLocal


def _run(coro_fn):
    """Run an async test body with a fresh async session (NullPool: no
    connections shared across the event loops asyncio.run creates)."""

    async def main():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await coro_fn(db)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def _grant(case_id: int, user_id: uuid.UUID, can_delete: bool) -> None:
    with SessionLocal() as session:
        session.add(
            CaseUserAccess(
                case_id=case_id,
                user_id=user_id,
                is_owner=can_delete,
                can_view=True,
                can_update=True,
                can_delete=can_delete,
                can_assign_users=False,
            )
        )
        session.commit()


def _deleted_fields(case_id: int):
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        return case.deleted_at, case.deleted_by


def test_owner_can_soft_delete_and_case_disappears(case_id):
    owner = uuid.uuid4()
    _grant(case_id, owner, can_delete=True)

    async def body(db):
        before = [c["caseId"] for c in await fetch_cases(db, owner)]
        await soft_delete_case(db, case_id=case_id, user_id=owner)
        after = [c["caseId"] for c in await fetch_cases(db, owner)]
        access = await get_case_user_access(db, case_id=case_id, user_id=owner)
        return before, after, access

    before, after, access = _run(body)

    assert case_id in before
    assert case_id not in after
    assert access is None

    deleted_at, deleted_by = _deleted_fields(case_id)
    assert deleted_at is not None
    assert deleted_by == owner


def test_deleted_case_endpoints_return_404(case_id):
    owner = uuid.uuid4()
    _grant(case_id, owner, can_delete=True)
    check = require_case_permission("can_view")

    async def body(db):
        await soft_delete_case(db, case_id=case_id, user_id=owner)
        with pytest.raises(HTTPException) as exc:
            await check(case_id=case_id, db=db, identity=RequestIdentity(owner, [], []))
        return exc.value.status_code

    assert _run(body) == 404


def test_delete_requires_can_delete(case_id):
    editor = uuid.uuid4()
    _grant(case_id, editor, can_delete=False)

    async def body(db):
        with pytest.raises(HTTPException) as exc:
            await soft_delete_case(db, case_id=case_id, user_id=editor)
        return exc.value.status_code

    assert _run(body) == 403
    assert _deleted_fields(case_id) == (None, None)


def test_delete_without_access_is_not_found(case_id):
    async def body(db):
        with pytest.raises(HTTPException) as exc:
            await soft_delete_case(db, case_id=case_id, user_id=uuid.uuid4())
        return exc.value.status_code

    assert _run(body) == 404


def test_deleting_twice_is_a_noop(case_id):
    owner = uuid.uuid4()
    _grant(case_id, owner, can_delete=True)

    async def body(db):
        await soft_delete_case(db, case_id=case_id, user_id=owner)
        first = _deleted_fields(case_id)
        again = await soft_delete_case(db, case_id=case_id, user_id=owner)
        return first, again

    first, again = _run(body)
    assert again is None
    assert _deleted_fields(case_id) == first


def test_list_reports_can_delete(case_id):
    viewer = uuid.uuid4()
    _grant(case_id, viewer, can_delete=False)

    async def body(db):
        return {c["caseId"]: c["canDelete"] for c in await fetch_cases(db, viewer)}

    assert _run(body) == {case_id: False}
