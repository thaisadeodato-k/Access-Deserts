"""Make sure geometries are lon/lat WGS84, whatever the server actually returned.

The WFS may ignore SRSNAME (returning native UTM metres) or return lat/lon axis order
for EPSG:4326. We test coordinates against the city's plausibility envelope and decide
once per layer; the decision is recorded in run.json.
"""
from __future__ import annotations

from collections import Counter

from pyproj import Transformer

MARGIN_DEG = 0.5  # tolerance around the envelope: points slightly outside the city are legitimate


def _map_coords(coords, fn):
    if coords and isinstance(coords[0], (int, float)):
        return list(fn(coords[0], coords[1])) + list(coords[2:])
    return [_map_coords(c, fn) for c in coords]


def _iter_xy(coords):
    if coords and isinstance(coords[0], (int, float)):
        yield coords[0], coords[1]
    else:
        for c in coords:
            yield from _iter_xy(c)


def _classify(x: float, y: float, env: list[float]) -> str:
    min_lon, min_lat, max_lon, max_lat = env
    if min_lon - MARGIN_DEG <= x <= max_lon + MARGIN_DEG and min_lat - MARGIN_DEG <= y <= max_lat + MARGIN_DEG:
        return "lonlat"
    if min_lon - MARGIN_DEG <= y <= max_lon + MARGIN_DEG and min_lat - MARGIN_DEG <= x <= max_lat + MARGIN_DEG:
        return "latlon"
    if 1e5 <= abs(x) <= 1e6 and 1e6 <= abs(y) <= 1e7:
        return "projected"
    return "unknown"


def ensure_lonlat(features: list[dict], envelope: list[float], native_crs: str, declared_crs: str | None) -> tuple[list[dict], dict]:
    """Return (features in lon/lat, record of what was detected and done)."""
    votes: Counter = Counter()
    for f in features:
        g = f.get("geometry")
        if g and g.get("coordinates"):
            votes.update(_classify(x, y, envelope) for x, y in _iter_xy(g["coordinates"]))
    record = {"declared_crs": declared_crs, "coordinate_votes": dict(votes)}
    if not votes:
        return features, {**record, "action": "none (no coordinates)"}

    verdict = votes.most_common(1)[0][0]
    if verdict == "lonlat":
        return features, {**record, "action": "none (lon/lat WGS84 as returned)"}
    if verdict == "latlon":
        fn = lambda x, y: (y, x)  # noqa: E731
        action = "swapped axis order (server returned lat/lon)"
    elif verdict == "projected":
        t = Transformer.from_crs(native_crs, "EPSG:4326", always_xy=True)
        fn = t.transform
        action = f"reprojected from {native_crs} (server ignored SRSNAME)"
    else:
        raise ValueError(f"Cannot determine coordinate system: {dict(votes)}")

    out = []
    for f in features:
        g = f.get("geometry")
        if g and g.get("coordinates"):
            f = {**f, "geometry": {**g, "coordinates": _map_coords(g["coordinates"], fn)}}
        out.append(f)
    return out, {**record, "action": action}
