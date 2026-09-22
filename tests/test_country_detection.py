"""
Pure unit tests for app/services/country_detection.py. No database required.
"""
from __future__ import annotations

import pytest
from pyproj import Geod
from shapely.geometry import Point, box

from app.services.country_detection import build_geometry, detect_country_for_geometry

_GEOD = Geod(ellps="WGS84")


def test_point_detects_single_country_belgium():
    # Brussels
    code, is_multiple = detect_country_for_geometry(Point(4.3517, 50.8503))
    assert code == "BE"
    assert is_multiple is False


def test_point_detects_single_country_netherlands():
    # Amsterdam
    code, is_multiple = detect_country_for_geometry(Point(4.9041, 52.3676))
    assert code == "NL"
    assert is_multiple is False


def test_polygon_straddling_real_border_returns_multiple():
    # A bounding box spanning the Belgium/Netherlands border near Antwerp.
    polygon = box(4.0, 51.2, 4.8, 51.6)
    code, is_multiple = detect_country_for_geometry(polygon)
    assert code == "XX"
    assert is_multiple is True


def test_zero_match_point_in_open_ocean_raises():
    # South Pacific, far from any land.
    with pytest.raises(ValueError):
        detect_country_for_geometry(Point(-140.0, -30.0))


def test_polygon_area_sanity_matches_geodesic_calculation():
    # A small rectangle fully inside Belgium, used both here and in the
    # save_location_step integration test.
    polygon = box(4.30, 50.80, 4.31, 50.81)

    expected_area, _perimeter = _GEOD.geometry_area_perimeter(polygon)
    expected_area = abs(expected_area)

    # Sanity bounds: a ~0.01deg x 0.01deg box near 50.8N is on the order of
    # 7-9 hectares (70,000-90,000 sqm is too tight; use a generous envelope).
    assert 700_000 <= expected_area <= 850_000

    code, is_multiple = detect_country_for_geometry(polygon)
    assert code == "BE"
    assert is_multiple is False


def test_build_geometry_from_wkt():
    geom = build_geometry(geometry_wkt="POINT(4.3517 50.8503)")
    assert geom.geom_type == "Point"
    assert geom.x == pytest.approx(4.3517)
    assert geom.y == pytest.approx(50.8503)


def test_build_geometry_from_lat_lon_uses_lon_lat_order():
    geom = build_geometry(latitude=50.8503, longitude=4.3517)
    assert geom.geom_type == "Point"
    # WKT/shapely coordinate order is (x=lon, y=lat).
    assert geom.x == pytest.approx(4.3517)
    assert geom.y == pytest.approx(50.8503)


def test_build_geometry_requires_wkt_or_lat_lon():
    with pytest.raises(ValueError):
        build_geometry()
