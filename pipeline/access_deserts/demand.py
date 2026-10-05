"""Demand: census tracts -> H3 hexagons (population, households, income, vulnerability).

Inputs (configured under `demand` in cities.yaml):
- tract polygons with the tract code (GeoSampa `densidade_demografica`), plus a population field
  used only for a consistency check and an optional comparison index (IPVS 2022);
- population and households per tract (IBGE basic aggregates, v0001 / v0007);
- income per tract (IBGE V06004, mean income of household heads WITH income) and its weight
  (V06001, all household heads). V06006 (median) is kept at tract level only: medians cannot be
  aggregated across tracts.

Method (parameters in params.yaml `demand`):
- hexagons: H3 cells at `h3_resolution` that intersect the city boundary;
- area weighting: each tract contributes value x (area of tract within the hexagon / tract area),
  i.e. people are assumed to be spread evenly within a tract;
- income: mean of tract V06004 weighted by household heads (V06001 x area weight), over tracts with
  usable income only; suppressed ("X") and unavailable (".") values are missing, never zero;
- income coverage: share of the hexagon's population living in tracts with usable income; below
  `income_coverage_threshold` the hexagon gets no income estimate;
- vulnerability_score: 1 - percentile rank of income_est among populated hexagons with income
  (ties averaged), so 1 = lowest income;
- comparison index (IPVS): population-weighted mean group and share of population in groups
  >= `vulnerable_from`; compared with vulnerability_score by Spearman rank correlation.
All geometry runs in the city's native CRS (metres).
"""
from __future__ import annotations

from collections import Counter

import h3
from shapely import STRtree
from shapely.geometry import Polygon, mapping

from .adapters.csv_zip import parse_value
from .boundary import Projector

MAX_LISTED = 10


# ---- tracts ------------------------------------------------------------------------------------

def build_tracts(tract_features: list[dict], pop_rows: dict, inc_rows: dict, conf: dict, decimals: dict) -> list[dict]:
    """One record per tract polygon, joined by tract code to the IBGE rows."""
    t, p, i = conf["tracts"], conf["population"], conf["income"]
    cmp_field = (t.get("comparison_index") or {}).get("field")
    out = []
    for f in tract_features:
        props = f.get("properties") or {}
        code = str(props.get(t["code_field"]))
        pr, ir = pop_rows.get(code), inc_rows.get(code)
        pop, _ = parse_value(pr[p["field"]], decimals["population"]) if pr else (None, "absent")
        hh, _ = parse_value(pr[p["households_field"]], decimals["population"]) if pr else (None, "absent")
        if ir is None:
            mean = heads = median = None
            status = "absent"
        else:
            mean, status = parse_value(ir[i["mean_field"]], decimals["income"])
            heads, _ = parse_value(ir[i["weight_field"]], decimals["income"])
            median, _ = parse_value(ir[i["median_field"]], decimals["income"]) if i.get("median_field") else (None, "")
            if status == "ok" and not heads:
                status = "no_heads"
        out.append({
            "code": code,
            "geometry": f.get("geometry"),
            "population": pop,
            "households": hh,
            "heads": heads,
            "income_mean": mean if status == "ok" else None,
            "income_median": median,
            "income_status": status,
            "population_check": props.get(t["population_check_field"]) if t.get("population_check_field") else None,
            "comparison": props.get(cmp_field) if cmp_field else None,
        })
    return out


def tract_checks(tracts: list[dict], pop_rows: dict, inc_rows: dict) -> dict:
    """Join and consistency report: codes, population check, income status."""
    codes = {t["code"] for t in tracts}
    mismatch = [t for t in tracts if t["population_check"] is not None and t["population"] is not None
                and float(t["population_check"]) != t["population"]]
    by_status: dict[str, dict] = {}
    for t in tracts:
        s = by_status.setdefault(t["income_status"], {"tracts": 0, "population": 0.0})
        s["tracts"] += 1
        s["population"] += t["population"] or 0
    total_pop = sum(t["population"] or 0 for t in tracts)
    return {
        "tract_polygons": len(tracts),
        "tracts_with_population_row": sum(t["code"] in pop_rows for t in tracts),
        "population_rows_without_polygon": len(set(pop_rows) - codes),
        "income_rows_without_polygon": len(set(inc_rows) - codes),
        "population_total": total_pop,
        "population_check": {
            "compared": sum(t["population_check"] is not None and t["population"] is not None for t in tracts),
            "mismatches": len(mismatch),
            "examples": [{"code": t["code"], "reference": t["population"], "check": t["population_check"]}
                         for t in mismatch[:MAX_LISTED]],
        },
        "income_status": {k: {**v, "population_pct": round(100 * v["population"] / total_pop, 3) if total_pop else None}
                          for k, v in sorted(by_status.items())},
    }


# ---- hexagons ----------------------------------------------------------------------------------

def hex_grid(boundary_native, resolution: int, proj: Projector) -> list[dict]:
    """H3 cells intersecting the boundary: cells whose centre lies in the boundary buffered by
    1 km (stable h3 API), kept if their polygon intersects the boundary."""
    buffered = proj.to_lonlat_geom(boundary_native.buffer(1000))
    cells = h3.h3shape_to_cells(h3.geo_to_h3shape(mapping(buffered)), resolution)
    out = []
    for c in sorted(cells):
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(c)]
        poly_ll = Polygon(ring)
        native = proj.to_native(mapping(poly_ll))
        if native.intersects(boundary_native):
            out.append({"h3_id": c, "geometry": mapping(poly_ll), "native": native,
                        "area_km2": native.area / 1e6,
                        "area_in_city_km2": native.intersection(boundary_native).area / 1e6})
    return out


def interpolate(tracts: list[dict], hexes: list[dict], proj: Projector) -> None:
    """Area-weighted sums per hexagon (in place)."""
    geoms = [proj.to_native(t["geometry"]) for t in tracts]
    tree = STRtree(geoms)
    for h in hexes:
        acc = Counter()
        cmp_codes = Counter()
        for k in tree.query(h["native"], predicate="intersects"):
            t, g = tracts[k], geoms[k]
            if not g.area:
                continue
            w = g.intersection(h["native"]).area / g.area
            if w <= 0:
                continue
            pop = (t["population"] or 0) * w
            acc["population"] += pop
            acc["households"] += (t["households"] or 0) * w
            acc["heads"] += (t["heads"] or 0) * w
            if t["income_mean"] is not None:
                acc["pop_with_income"] += pop
                acc["income_x_heads"] += t["income_mean"] * (t["heads"] or 0) * w
                acc["heads_with_income"] += (t["heads"] or 0) * w
            if t["comparison"] is not None:
                acc["pop_with_comparison"] += pop
                acc["comparison_x_pop"] += float(t["comparison"]) * pop
                cmp_codes[int(t["comparison"])] += pop
        h["sums"] = acc
        h["comparison_codes"] = cmp_codes


def finish(hexes: list[dict], threshold: float, vulnerable_from: int | None) -> None:
    """Estimates per hexagon from the sums (in place)."""
    for h in hexes:
        s = h["sums"]
        # Population as published (0.1 person). Slivers below that count as unpopulated, so
        # "with income", "scored" and "populated" always refer to the same hexagons.
        pop = round(s["population"], 1)
        cov = s["pop_with_income"] / s["population"] if pop > 0 else None
        income = (s["income_x_heads"] / s["heads_with_income"]
                  if s["heads_with_income"] > 0 and cov is not None and cov >= threshold else None)
        ccov = s["pop_with_comparison"] / s["population"] if pop > 0 else None
        h["props"] = {
            "h3_id": h["h3_id"],
            "area_km2": round(h["area_km2"], 4),
            "area_in_city_km2": round(h["area_in_city_km2"], 4),
            "population_est": pop,
            "households_est": round(s["households"], 1),
            "heads_est": round(s["heads"], 1),
            "pop_density_km2": round(s["population"] / h["area_in_city_km2"], 1) if h["area_in_city_km2"] > 0 else None,
            "income_est": round(income, 2) if income is not None else None,
            "income_coverage": round(cov, 4) if cov is not None else None,
            "vulnerability_score": None,
            "comparison_mean": (round(s["comparison_x_pop"] / s["pop_with_comparison"], 3)
                                if s["pop_with_comparison"] > 0 else None),
            "comparison_vulnerable_share": (
                round(sum(v for c, v in h["comparison_codes"].items() if c >= vulnerable_from)
                      / s["pop_with_comparison"], 4)
                if vulnerable_from is not None and s["pop_with_comparison"] > 0 else None),
            "comparison_coverage": round(ccov, 4) if ccov is not None else None,
        }


def percentile_ranks(values: list[float]) -> list[float]:
    """Percentile rank in [0, 1] (ascending), ties averaged."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg / (n - 1) if n > 1 else 0.0
        i = j + 1
    return ranks


def vulnerability(hexes: list[dict]) -> int:
    """1 - percentile rank of income among populated hexagons with income. Returns how many scored."""
    scored = [h for h in hexes if h["props"]["population_est"] > 0 and h["props"]["income_est"] is not None]
    for h, r in zip(scored, percentile_ranks([h["props"]["income_est"] for h in scored])):
        h["props"]["vulnerability_score"] = round(1 - r, 4)
    return len(scored)


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = percentile_ranks(a), percentile_ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return round(cov / (va * vb) ** 0.5, 4) if va and vb else None


def sensitivity(hexes: list[dict], thresholds: list[float]) -> list[dict]:
    """Populated hexagons and population without an income estimate at each coverage threshold."""
    populated = [h for h in hexes if h["props"]["population_est"] > 0]
    total = sum(h["props"]["population_est"] for h in populated)
    out = []
    for t in thresholds:
        without = [h for h in populated if h["sums"]["heads_with_income"] <= 0
                   or (h["props"]["income_coverage"] or 0) < t]
        pop = sum(h["props"]["population_est"] for h in without)
        out.append({"threshold": t, "hexagons_without_income": len(without), "populated_hexagons": len(populated),
                    "population_without_income": round(pop), "population_pct": round(100 * pop / total, 3) if total else None})
    return out


def comparison(hexes: list[dict], min_coverage: float, districts: list[dict] | None, proj: Projector) -> dict:
    """Spearman correlation between vulnerability_score and the comparison index, and the hexagons
    where they disagree most (difference of percentile ranks)."""
    both = [h for h in hexes if h["props"]["vulnerability_score"] is not None
            and h["props"]["comparison_mean"] is not None and (h["props"]["comparison_coverage"] or 0) >= min_coverage]
    rho = spearman([h["props"]["vulnerability_score"] for h in both], [h["props"]["comparison_mean"] for h in both])
    rv = percentile_ranks([h["props"]["vulnerability_score"] for h in both])
    rc = percentile_ranks([h["props"]["comparison_mean"] for h in both])
    named = []
    if districts:
        d_geoms = [(d["properties"].get("name"), proj.to_native(d["geometry"])) for d in districts if d.get("geometry")]
    for h, a, b in zip(both, rv, rc):
        district = None
        if districts:
            c = h["native"].centroid
            district = next((n for n, g in d_geoms if g.covers(c)), None)
        named.append({"h3_id": h["h3_id"], "district": district, "vulnerability_score": h["props"]["vulnerability_score"],
                      "comparison_mean": h["props"]["comparison_mean"], "income_est": h["props"]["income_est"],
                      "population_est": h["props"]["population_est"], "rank_difference": round(a - b, 4)})
    named.sort(key=lambda x: x["rank_difference"])
    return {
        "hexagons_compared": len(both),
        "min_comparison_coverage": min_coverage,
        "spearman_rho": rho,
        "more_vulnerable_by_income_than_by_index": named[::-1][:MAX_LISTED],
        "more_vulnerable_by_index_than_by_income": named[:MAX_LISTED],
        "note": "rank_difference = percentile rank of vulnerability_score minus percentile rank of the comparison "
                "index mean group (both: higher = more vulnerable).",
    }


def to_feature(h: dict) -> dict:
    return {"type": "Feature", "geometry": h["geometry"], "properties": h["props"]}
