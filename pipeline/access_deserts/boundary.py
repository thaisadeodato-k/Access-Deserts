"""City boundary: union of the configured polygons, consistency check, records outside it.

All geometry operations run in the city's native projected CRS (metres); outputs are lon/lat.
A record is "outside" when its geometry does not intersect the boundary (points on the
boundary line count as inside).
"""
from __future__ import annotations

import numpy as np
from pyproj import Transformer
from shapely import make_valid, transform, union_all
from shapely.geometry import mapping, shape
from shapely.prepared import prep

MAX_LISTED_OUTSIDE = 10


class Projector:
    def __init__(self, native_crs: str):
        self.native_crs = native_crs
        fwd = Transformer.from_crs("EPSG:4326", native_crs, always_xy=True)
        back = Transformer.from_crs(native_crs, "EPSG:4326", always_xy=True)
        # Vectorised: shapely passes all coordinates of a geometry as one (n, 2) array.
        self._fwd = lambda xy: np.column_stack(fwd.transform(xy[:, 0], xy[:, 1]))
        self._back = lambda xy: np.column_stack(back.transform(xy[:, 0], xy[:, 1]))

    def to_native(self, geojson_geometry: dict):
        return make_valid(transform(shape(geojson_geometry), self._fwd))

    def to_lonlat_geom(self, geom):
        return transform(geom, self._back)

    def to_lonlat(self, geom) -> dict:
        return mapping(self.to_lonlat_geom(geom))


def union_boundary(features: list[dict], proj: Projector):
    """Union of all polygon features (native CRS)."""
    return make_valid(union_all([proj.to_native(f["geometry"]) for f in features if f.get("geometry")]))


def consistency_check(boundary, reference_features: list[dict], proj: Projector, label: str) -> dict:
    """Compare the boundary with a reference polygon (e.g. area_contexto id 27)."""
    if not reference_features:
        return {"reference": label, "result": "reference feature not available"}
    ref = make_valid(union_all([proj.to_native(f["geometry"]) for f in reference_features if f.get("geometry")]))
    sym = boundary.symmetric_difference(ref).area
    return {
        "reference": label,
        "reference_features": len(reference_features),
        "boundary_area_km2": round(boundary.area / 1e6, 3),
        "reference_area_km2": round(ref.area / 1e6, 3),
        "area_difference_km2": round((boundary.area - ref.area) / 1e6, 3),
        "symmetric_difference_km2": round(sym / 1e6, 3),
        "symmetric_difference_pct_of_boundary": round(100 * sym / boundary.area, 4) if boundary.area else None,
    }


def outside_records(services: list[dict], boundary, proj: Projector) -> dict[str, dict]:
    """Per source: records with geometry, how many fall outside the boundary, and a few of them.

    Also sets `outside_boundary` (true/false; null without geometry) on every record. Records
    outside stay in the metrics (author decision 2026-10-05: dropping them would create
    artificial deserts at the city edge)."""
    inside = prep(boundary)
    out: dict[str, dict] = {}
    for s in services:
        p, g = s["properties"], s.get("geometry")
        rec = out.setdefault(p["source_id"], {"with_geometry": 0, "outside": 0, "examples": []})
        if not g:
            p["outside_boundary"] = None
            continue
        rec["with_geometry"] += 1
        p["outside_boundary"] = not inside.intersects(proj.to_native(g))
        if p["outside_boundary"]:
            rec["outside"] += 1
            if len(rec["examples"]) < MAX_LISTED_OUTSIDE:
                rec["examples"].append({"id": p["id"], "name": p.get("name")})
    for rec in out.values():
        rec["pct_outside"] = round(100 * rec["outside"] / rec["with_geometry"], 2) if rec["with_geometry"] else None
    return out
