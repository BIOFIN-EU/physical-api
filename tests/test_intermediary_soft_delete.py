"""
Soft delete of intermediaries, and the case-assignment endpoints.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request
from temporalio.exceptions import ApplicationError

from app.core.settings import settings
from app.models.case_data import (
    CaseIntermediary,
    Intermediary,
    IntermediaryFunction,
    IntermediaryFunctionAssignment,
)
from app.routers import intermediaries as api
from app.routers.lookups import get_lookup
from app.schemas.case_data import CaseIntermediaryAssign
from app.workflows.activities import SessionLocal, save_intermediary_step


def _run(coro_fn):
    async def main():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await coro_fn(db)
        finally:
            await engine.dispose()

    return asyncio.run(main())


@pytest.fixture()
def intermediary_and_functions():
    """One intermediary providing two functions, plus a third function it
    doesn't provide; all removed again afterwards."""
    with SessionLocal() as session:
        functions = [
            IntermediaryFunction(
                code=f"fn_{uuid.uuid4().hex[:8]}",
                name=f"Function {i}",
                function_category="financial",
            )
            for i in range(3)
        ]
        intermediary = Intermediary(name=f"Test {uuid.uuid4().hex[:6]}")
        session.add_all([intermediary, *functions])
        session.flush()
        session.add_all(
            IntermediaryFunctionAssignment(
                intermediary_id=intermediary.id, intermediary_function_id=f.id
            )
            for f in functions[:2]
        )
        session.commit()
        ids = (intermediary.id, [f.id for f in functions])

    yield ids

    with SessionLocal() as session:
        session.execute(
            CaseIntermediary.__table__.delete().where(CaseIntermediary.intermediary_id == ids[0])
        )
        session.execute(
            IntermediaryFunctionAssignment.__table__.delete().where(
                IntermediaryFunctionAssignment.intermediary_id == ids[0]
            )
        )
        session.execute(Intermediary.__table__.delete().where(Intermediary.id == ids[0]))
        session.execute(
            IntermediaryFunction.__table__.delete().where(IntermediaryFunction.id.in_(ids[1]))
        )
        session.commit()


def _assignments(case_id: int) -> set[tuple[int, int]]:
    with SessionLocal() as session:
        return {
            (row.intermediary_id, row.intermediary_function_id)
            for row in session.execute(
                select(CaseIntermediary).where(CaseIntermediary.case_id == case_id)
            ).scalars()
        }


def test_soft_delete_hides_intermediary_but_keeps_row(intermediary_and_functions):
    intermediary_id, _ = intermediary_and_functions
    user = uuid.uuid4()

    async def body(db):
        await api.delete_intermediary(intermediary_id, db=db, user_id=user)
        await api.delete_intermediary(intermediary_id, db=db, user_id=user)  # no-op
        listed = [i.id for i in await api.list_intermediaries(db=db)]
        lookup = [int(o["value"]) for o in await get_lookup("intermediary", db=db, intermediary_id=None)]
        with pytest.raises(HTTPException) as exc:
            await api.get_intermediary(intermediary_id, db=db)
        return listed, lookup, exc.value.status_code

    listed, lookup, get_status = _run(body)

    assert intermediary_id not in listed
    assert intermediary_id not in lookup
    assert get_status == 404

    with SessionLocal() as session:
        row = session.get(Intermediary, intermediary_id)
        assert row is not None
        assert row.deleted_at is not None
        assert row.deleted_by == user


def test_existing_assignment_survives_delete_but_no_new_ones(case_id, intermediary_and_functions):
    intermediary_id, (fn_a, _, _) = intermediary_and_functions
    step = {"assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_a}]}

    save_intermediary_step(case_id, dict(step))

    _run(lambda db: api.delete_intermediary(intermediary_id, db=db, user_id=uuid.uuid4()))

    # The project keeps it, and re-saving the step with it still works.
    assert _assignments(case_id) == {(intermediary_id, fn_a)}
    save_intermediary_step(case_id, dict(step))
    assert _assignments(case_id) == {(intermediary_id, fn_a)}


def test_deleted_intermediary_cannot_be_newly_assigned(case_id, intermediary_and_functions):
    intermediary_id, (fn_a, _, _) = intermediary_and_functions
    _run(lambda db: api.delete_intermediary(intermediary_id, db=db, user_id=uuid.uuid4()))

    with pytest.raises(ApplicationError):
        save_intermediary_step(
            case_id,
            {"assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_a}]},
        )


def test_assign_and_remove_endpoints_handle_functions(case_id, intermediary_and_functions):
    intermediary_id, (fn_a, fn_b, _) = intermediary_and_functions
    access = SimpleNamespace(user_id=uuid.uuid4())

    async def body(db):
        for fn in (fn_a, fn_b):
            await api.assign_intermediary_to_case(
                case_id,
                CaseIntermediaryAssign(intermediary_id=intermediary_id, intermediary_function_id=fn),
                db=db,
                access=access,
            )
        with pytest.raises(HTTPException) as dup:
            await api.assign_intermediary_to_case(
                case_id,
                CaseIntermediaryAssign(intermediary_id=intermediary_id, intermediary_function_id=fn_a),
                db=db,
                access=access,
            )
        assigned = _assignments(case_id)
        # Removing without a function removes every function it holds.
        await api.remove_intermediary_from_case(case_id, intermediary_id, db=db, access=access)
        return dup.value.status_code, assigned

    dup_status, assigned = _run(body)

    assert assigned == {(intermediary_id, fn_a), (intermediary_id, fn_b)}
    assert dup_status == 409
    assert _assignments(case_id) == set()


def test_resave_keeps_unchanged_assignment_rows(case_id, intermediary_and_functions):
    intermediary_id, (fn_a, fn_b, _) = intermediary_and_functions
    alice, bob = uuid.uuid4(), uuid.uuid4()
    from app.workflows.actor import ACTOR_KEY

    save_intermediary_step(case_id, {
        "assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_a}],
        ACTOR_KEY: str(alice),
    })
    with SessionLocal() as session:
        original = session.execute(
            select(CaseIntermediary).where(CaseIntermediary.case_id == case_id)
        ).scalar_one()
        original_id, original_by = original.id, original.created_by

    # Bob keeps function A and adds function B.
    save_intermediary_step(case_id, {
        "assignments": [
            {"intermediary_id": intermediary_id, "intermediary_function_id": fn_a},
            {"intermediary_id": intermediary_id, "intermediary_function_id": fn_b},
        ],
        ACTOR_KEY: str(bob),
    })
    with SessionLocal() as session:
        rows = {
            row.intermediary_function_id: (row.id, row.created_by)
            for row in session.execute(
                select(CaseIntermediary).where(CaseIntermediary.case_id == case_id)
            ).scalars()
        }

    assert rows[fn_a] == (original_id, alice)
    assert rows[fn_b][1] == bob

    # Dropping function A removes just that row.
    save_intermediary_step(case_id, {
        "assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_b}],
    })
    assert _assignments(case_id) == {(intermediary_id, fn_b)}


def test_duplicate_intermediary_email_is_409():
    email = f"dup-{uuid.uuid4().hex[:8]}@example.org"
    from app.schemas.case_data import IntermediaryCreate

    async def body(db):
        first = await api.create_intermediary(
            IntermediaryCreate(name="One", email=email, function_ids=[]), db=db, user_id=uuid.uuid4()
        )
        with pytest.raises(HTTPException) as exc:
            await api.create_intermediary(
                IntermediaryCreate(name="Two", email=email.upper(), function_ids=[]),
                db=db,
                user_id=uuid.uuid4(),
            )
        # Once the first is deleted, the email can be reused.
        await api.delete_intermediary(first.id, db=db, user_id=uuid.uuid4())
        second = await api.create_intermediary(
            IntermediaryCreate(name="Three", email=email, function_ids=[]), db=db, user_id=uuid.uuid4()
        )
        return exc.value.status_code, [first.id, second.id]

    status_code, ids = _run(body)
    assert status_code == 409

    with SessionLocal() as session:
        session.execute(Intermediary.__table__.delete().where(Intermediary.id.in_(ids)))
        session.commit()


def test_function_lookup_filters_by_intermediary(intermediary_and_functions):
    intermediary_id, (fn_a, fn_b, fn_other) = intermediary_and_functions

    async def body(db):
        # As the endpoint receives it: the parameter is in the request's query
        # string too, which the linked-classification filters also read.
        request = Request({"type": "http", "query_string": f"intermediary_id={intermediary_id}".encode(), "headers": []})
        filtered = {
            int(o["value"])
            for o in await get_lookup("intermediary_function", db=db, intermediary_id=intermediary_id, request=request)
        }
        everything = {int(o["value"]) for o in await get_lookup("intermediary_function", db=db, intermediary_id=None)}
        with pytest.raises(HTTPException) as exc:
            await get_lookup("country", db=db, intermediary_id=intermediary_id)
        return filtered, everything, exc.value.status_code

    filtered, everything, bad_filter = _run(body)

    assert filtered == {fn_a, fn_b}
    assert {fn_a, fn_b, fn_other} <= everything
    assert bad_filter == 400


def test_step_rejects_function_the_intermediary_does_not_provide(case_id, intermediary_and_functions):
    intermediary_id, (_, _, fn_other) = intermediary_and_functions

    with pytest.raises(ApplicationError) as exc:
        save_intermediary_step(
            case_id,
            {"assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_other}]},
        )
    assert "doesn't provide" in str(exc.value.details)


def test_existing_pairing_survives_function_removal(case_id, intermediary_and_functions):
    intermediary_id, (fn_a, _, _) = intermediary_and_functions
    step = {"assignments": [{"intermediary_id": intermediary_id, "intermediary_function_id": fn_a}]}
    save_intermediary_step(case_id, dict(step))

    # The intermediary stops providing function A; the project can still re-save.
    with SessionLocal() as session:
        session.execute(
            IntermediaryFunctionAssignment.__table__.delete().where(
                IntermediaryFunctionAssignment.intermediary_id == intermediary_id,
                IntermediaryFunctionAssignment.intermediary_function_id == fn_a,
            )
        )
        session.commit()

    save_intermediary_step(case_id, dict(step))
    assert _assignments(case_id) == {(intermediary_id, fn_a)}
