from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.wkt import loads as wkt_loads

_COUNTRY_BOUNDARIES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "country_boundaries.geojson"
)


def _load_country_geometries() -> dict[str, BaseGeometry]:
    """
    Load the bundled country boundary GeoJSON once at import time into a
    {iso_a2: shapely_geometry} lookup used for country detection.
    """
    with _COUNTRY_BOUNDARIES_PATH.open("r", encoding="utf-8") as f:
        collection = json.load(f)

    geometries: dict[str, BaseGeometry] = {}

    for feature in collection.get("features", []):
        properties = feature.get("properties", {})
        iso_a2 = properties.get("iso_a2")

        if not iso_a2:
            continue

        geometries[iso_a2] = shape(feature["geometry"])

    return geometries


COUNTRY_GEOMETRIES: dict[str, BaseGeometry] = _load_country_geometries()


def build_geometry(
        *,
        geometry_wkt: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
) -> BaseGeometry:
    """
    Build a shapely geometry from either a WKT string or a (lat, lon) pair.

    Exactly one of `geometry_wkt` or the (`latitude`, `longitude`) pair should be
    provided. WKT coordinate order is X=lon, Y=lat, so a point built from
    latitude/longitude is constructed as Point(longitude, latitude).
    """
    if geometry_wkt is not None:
        return wkt_loads(geometry_wkt)

    if latitude is not None and longitude is not None:
        return Point(longitude, latitude)

    raise ValueError(
        "Either geometry_wkt or both latitude and longitude must be provided."
    )


def detect_country_for_geometry(geom: BaseGeometry) -> tuple[str, bool]:
    """
    Detect which seeded country(ies) a geometry falls within.

    Returns (iso_a2_code, is_multiple):
    - Exactly one matching country -> (that country's code, False)
    - Two or more matching countries -> ("XX", True)
    - Zero matching countries -> raises ValueError

    For a point that matches nothing, a single retry is made against a small
    buffer around the point (handles pins dropped just offshore against a
    simplified coastline) before giving up.
    """
    matches = [
        code
        for code, country_geom in COUNTRY_GEOMETRIES.items()
        if country_geom.intersects(geom)
    ]

    if not matches and geom.geom_type == "Point":
        buffered = geom.buffer(0.05)
        matches = [
            code
            for code, country_geom in COUNTRY_GEOMETRIES.items()
            if country_geom.intersects(buffered)
        ]

    if not matches:
        raise ValueError(
            "No supported country found for this location. Please adjust it to "
            "fall within a supported country."
        )

    if len(matches) == 1:
        return matches[0], False

    return "XX", True
