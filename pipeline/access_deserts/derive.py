"""Names derived from another layer when the source has no name field (e.g. CRAS).

A record gets the name of the area that contains it only when the match is one-to-one: the
point lies in exactly one area AND that area contains no other point of the source. Otherwise
the name stays null. Derived names are flagged with `name_derived: true`. Geometry operations
run in the city's native CRS.
"""
from __future__ import annotations

from collections import Counter

from .boundary import Projector

METHOD = ("name of the {source} area ({field}) containing the record; assigned only for "
          "one-to-one matches (point in exactly one area, area containing no other point)")


def derive_names(services: list[dict], areas: list[dict], conf: dict, proj: Projector) -> dict:
    """Assign derived names in place. Returns a summary for quality.json and run.json."""
    field = conf["field"]
    polys = [((a.get("properties") or {}).get(field), proj.to_native(a["geometry"]))
             for a in areas if a.get("geometry")]
    matches: dict[int, list[int]] = {}
    for i, s in enumerate(services):
        if s.get("geometry"):
            g = proj.to_native(s["geometry"])
            matches[i] = [k for k, (_, poly) in enumerate(polys) if poly.covers(g)]
    points_per_area = Counter(k for m in matches.values() for k in m)
    assigned = 0
    for i, m in matches.items():
        p = services[i]["properties"]
        if len(m) == 1 and points_per_area[m[0]] == 1 and p.get("name") is None and polys[m[0]][0]:
            p["name"] = polys[m[0]][0]
            p["name_derived"] = True
            assigned += 1
    per_point = Counter(len(m) for m in matches.values())
    return {
        "method": METHOD.format(source=conf["from_source"], field=field),
        "from_source": conf["from_source"],
        "field": field,
        "records": len(services),
        "records_with_geometry": len(matches),
        "in_exactly_one_area": per_point.get(1, 0),
        "in_no_area": per_point.get(0, 0),
        "in_several_areas": sum(v for k, v in per_point.items() if k > 1),
        "areas": len(polys),
        "areas_without_record": sorted(n or "(no name)" for k, (n, _) in enumerate(polys) if not points_per_area[k]),
        "areas_with_several_records": [
            {"area": polys[k][0], "records": c} for k, c in sorted(points_per_area.items()) if c > 1
        ],
        "names_assigned": assigned,
        "names_left_null": sum(1 for s in services if s["properties"].get("name") is None),
    }
