"""
Integration tests for save_location_step against a real Postgres database
(see tests/conftest.py for how the target database is selected/skipped).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from temporalio.exceptions import ApplicationError

from app.models.case_data import CaseLocation
from app.workflows.activities import SessionLocal, save_location_step


def _locations_for_case(case_id: int) -> list[CaseLocation]:
    with SessionLocal() as session:
        rows = session.execute(
            select(CaseLocation).where(CaseLocation.case_id == case_id)
        ).scalars().all()
        # Detach-safe: read everything we need while the session is open.
        return [
            {
                "friendly_name": row.friendly_name,
                "location_type": row.location_type,
                "geometry_wkt": row.geometry_wkt,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "area_sqm": row.area_sqm,
                "area_is_manual": row.area_is_manual,
                "country_code": row.country.code,
            }
            for row in rows
        ]


def test_two_locations_in_different_countries(case_id):
    save_location_step(
        case_id,
        {
            "locations": [
                {
                    "friendly_name": "Brussels site",
                    "location_type": "point",
                    "latitude": 50.8503,
                    "longitude": 4.3517,
                },
                {
                    "friendly_name": "Amsterdam site",
                    "location_type": "point",
                    "latitude": 52.3676,
                    "longitude": 4.9041,
                },
            ]
        },
    )

    rows = _locations_for_case(case_id)
    assert len(rows) == 2
    codes = {row["country_code"] for row in rows}
    assert codes == {"BE", "NL"}


def test_resubmitting_replaces_existing_locations(case_id):
    save_location_step(
        case_id,
        {"locations": [{"location_type": "point", "latitude": 50.8503, "longitude": 4.3517}]},
    )
    assert len(_locations_for_case(case_id)) == 1

    save_location_step(
        case_id,
        {
            "locations": [
                {"location_type": "point", "latitude": 50.8503, "longitude": 4.3517},
                {"location_type": "point", "latitude": 52.3676, "longitude": 4.9041},
            ]
        },
    )
    assert len(_locations_for_case(case_id)) == 2


def _location_ids_and_risk(case_id: int) -> dict[str, tuple[int, str | None]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(CaseLocation).where(CaseLocation.case_id == case_id)
        ).scalars().all()
        return {row.friendly_name: (row.id, row.risk_id) for row in rows}


def _set_risk_id(case_id: int, friendly_name: str, risk_id: str) -> None:
    with SessionLocal() as session:
        row = session.execute(
            select(CaseLocation).where(
                CaseLocation.case_id == case_id,
                CaseLocation.friendly_name == friendly_name,
            )
        ).scalar_one()
        row.risk_id = risk_id
        session.commit()


BRUSSELS_POLYGON = (
    "POLYGON((4.34 50.84, 4.36 50.84, 4.36 50.86, 4.34 50.86, 4.34 50.84))"
)


def test_resubmitting_keeps_unchanged_locations_and_risk_id(case_id):
    save_location_step(
        case_id,
        {"locations": [{
            "friendly_name": "Brussels",
            "location_type": "polygon",
            "geometry_wkt": BRUSSELS_POLYGON,
        }]},
    )
    _set_risk_id(case_id, "Brussels", "risk-1")
    original_id, _ = _location_ids_and_risk(case_id)["Brussels"]

    # Same polygon (resubmitted as stored) plus a new location, and the
    # unchanged one renamed.
    with SessionLocal() as session:
        stored_wkt = session.get(CaseLocation, original_id).geometry_wkt

    save_location_step(
        case_id,
        {"locations": [
            {
                "friendly_name": "Brussels renamed",
                "location_type": "polygon",
                "geometry_wkt": stored_wkt,
            },
            {
                "friendly_name": "Amsterdam",
                "location_type": "point",
                "latitude": 52.3676,
                "longitude": 4.9041,
            },
        ]},
    )

    rows = _location_ids_and_risk(case_id)
    assert rows["Brussels renamed"] == (original_id, "risk-1")
    assert rows["Amsterdam"][1] is None
    assert len(rows) == 2


def test_resubmitting_drops_removed_and_changed_locations(case_id):
    save_location_step(
        case_id,
        {"locations": [
            {"friendly_name": "Brussels", "location_type": "polygon", "geometry_wkt": BRUSSELS_POLYGON},
            {"friendly_name": "Amsterdam", "location_type": "point", "latitude": 52.3676, "longitude": 4.9041},
        ]},
    )
    _set_risk_id(case_id, "Brussels", "risk-1")
    original_id, _ = _location_ids_and_risk(case_id)["Brussels"]

    moved_polygon = (
        "POLYGON((4.35 50.84, 4.37 50.84, 4.37 50.86, 4.35 50.86, 4.35 50.84))"
    )
    save_location_step(
        case_id,
        {"locations": [
            {"friendly_name": "Brussels", "location_type": "polygon", "geometry_wkt": moved_polygon},
        ]},
    )

    rows = _location_ids_and_risk(case_id)
    assert list(rows) == ["Brussels"]
    new_id, risk_id = rows["Brussels"]
    assert new_id != original_id
    assert risk_id is None


def test_polygon_straddling_border_detects_multiple_countries(case_id):
    save_location_step(
        case_id,
        {
            "locations": [
                {
                    "location_type": "polygon",
                    "geometry_wkt": (
                        "POLYGON((4.0 51.2, 4.8 51.2, 4.8 51.6, 4.0 51.6, 4.0 51.2))"
                    ),
                }
            ]
        },
    )

    rows = _locations_for_case(case_id)
    assert len(rows) == 1
    assert rows[0]["country_code"] == "XX"
    assert rows[0]["location_type"] == "polygon"
    assert rows[0]["area_is_manual"] is False
    assert rows[0]["area_sqm"] is not None


def test_point_with_manual_area(case_id):
    save_location_step(
        case_id,
        {
            "locations": [
                {
                    "location_type": "point",
                    "latitude": 50.8503,
                    "longitude": 4.3517,
                    "area_sqm": 12345.6,
                }
            ]
        },
    )

    rows = _locations_for_case(case_id)
    assert len(rows) == 1
    assert rows[0]["area_is_manual"] is True
    assert rows[0]["area_sqm"] == pytest.approx(12345.6)
    assert rows[0]["latitude"] == pytest.approx(50.8503)
    assert rows[0]["longitude"] == pytest.approx(4.3517)


def test_point_without_area_is_not_manual(case_id):
    save_location_step(
        case_id,
        {"locations": [{"location_type": "point", "latitude": 50.8503, "longitude": 4.3517}]},
    )

    rows = _locations_for_case(case_id)
    assert rows[0]["area_is_manual"] is False
    assert rows[0]["area_sqm"] is None


def test_polygon_area_sanity_check(case_id):
    # Small rectangle fully inside Belgium (~7-9 hectares).
    save_location_step(
        case_id,
        {
            "locations": [
                {
                    "location_type": "polygon",
                    "geometry_wkt": (
                        "POLYGON((4.30 50.80, 4.31 50.80, 4.31 50.81, 4.30 50.81, 4.30 50.80))"
                    ),
                }
            ]
        },
    )

    rows = _locations_for_case(case_id)
    assert rows[0]["country_code"] == "BE"
    assert 700_000 <= rows[0]["area_sqm"] <= 850_000


def test_zero_match_location_is_rejected(case_id):
    with pytest.raises(ApplicationError) as exc_info:
        save_location_step(
            case_id,
            {
                "locations": [
                    {
                        "location_type": "point",
                        "latitude": -30.0,
                        "longitude": -140.0,
                    }
                ]
            },
        )

    assert exc_info.value.type == "ValidationError"
    assert exc_info.value.non_retryable is True

    # Nothing should have been persisted for the rejected submission.
    assert _locations_for_case(case_id) == []
