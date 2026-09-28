"""
created_by / updated_by on step tables, and cases.updated_by, filled from the
acting user the API adds to a step payload (ACTOR_KEY).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.case_data import Case, CaseBasicInfo, CaseLocation
from app.workflows.activities import SessionLocal, save_basic_info_step, save_location_step
from app.workflows.actor import ACTOR_KEY


def _basic_info(case_id: int):
    with SessionLocal() as session:
        row = session.execute(
            select(CaseBasicInfo).where(CaseBasicInfo.case_id == case_id)
        ).scalar_one()
        return row.created_by, row.updated_by


def _case_updated_by(case_id: int):
    with SessionLocal() as session:
        return session.get(Case, case_id).updated_by


def test_first_save_sets_created_and_updated_by(case_id):
    alice = uuid.uuid4()
    save_basic_info_step(case_id, {"name": "A", "high_level_description": "d", ACTOR_KEY: str(alice)})

    assert _basic_info(case_id) == (alice, alice)
    assert _case_updated_by(case_id) == alice


def test_later_save_keeps_creator_and_updates_editor(case_id):
    alice, bob = uuid.uuid4(), uuid.uuid4()
    save_basic_info_step(case_id, {"name": "A", "high_level_description": "d", ACTOR_KEY: str(alice)})
    save_basic_info_step(case_id, {"name": "B", "high_level_description": "d", ACTOR_KEY: str(bob)})

    assert _basic_info(case_id) == (alice, bob)
    assert _case_updated_by(case_id) == bob


def test_save_without_actor_leaves_columns_empty(case_id):
    before = _case_updated_by(case_id)
    save_basic_info_step(case_id, {"name": "A", "high_level_description": "d"})

    assert _basic_info(case_id) == (None, None)
    assert _case_updated_by(case_id) == before


def test_invalid_actor_is_ignored(case_id):
    save_basic_info_step(case_id, {"name": "A", "high_level_description": "d", ACTOR_KEY: "not-a-uuid"})

    assert _basic_info(case_id) == (None, None)


def test_unchanged_location_keeps_its_editor(case_id):
    alice, bob = uuid.uuid4(), uuid.uuid4()
    polygon = "POLYGON((4.34 50.84, 4.36 50.84, 4.36 50.86, 4.34 50.86, 4.34 50.84))"
    save_location_step(case_id, {
        "locations": [{"friendly_name": "Brussels", "location_type": "polygon", "geometry_wkt": polygon}],
        ACTOR_KEY: str(alice),
    })

    with SessionLocal() as session:
        stored = session.execute(
            select(CaseLocation).where(CaseLocation.case_id == case_id)
        ).scalar_one().geometry_wkt

    # Bob resubmits the same location unchanged and adds a point.
    save_location_step(case_id, {
        "locations": [
            {"friendly_name": "Brussels", "location_type": "polygon", "geometry_wkt": stored},
            {"friendly_name": "Amsterdam", "location_type": "point", "latitude": 52.3676, "longitude": 4.9041},
        ],
        ACTOR_KEY: str(bob),
    })

    with SessionLocal() as session:
        rows = {
            row.friendly_name: (row.created_by, row.updated_by)
            for row in session.execute(
                select(CaseLocation).where(CaseLocation.case_id == case_id)
            ).scalars()
        }

    assert rows["Brussels"] == (alice, alice)
    assert rows["Amsterdam"] == (bob, bob)


def test_financing_type_records_editor(case_id):
    from app.models.case_data import CaseFinancingType, FinancingType
    from app.workflows.activities import save_financing_type_step

    with SessionLocal() as session:
        type_ids = [t.id for t in session.execute(select(FinancingType).limit(2)).scalars()]
        if len(type_ids) < 2:
            for code in ("t_a", "t_b"):
                session.add(FinancingType(code=f"{code}_{uuid.uuid4().hex[:6]}", name=code))
            session.commit()
            type_ids = [t.id for t in session.execute(select(FinancingType).limit(2)).scalars()]

    alice, bob = uuid.uuid4(), uuid.uuid4()
    save_financing_type_step(case_id, {"financing_type_id": type_ids[0], ACTOR_KEY: str(alice)})
    save_financing_type_step(case_id, {"financing_type_id": type_ids[1], ACTOR_KEY: str(bob)})

    with SessionLocal() as session:
        row = session.execute(
            select(CaseFinancingType).where(CaseFinancingType.case_id == case_id)
        ).scalar_one()
        assert (row.created_by, row.updated_by) == (alice, bob)
        assert row.updated_at is not None
