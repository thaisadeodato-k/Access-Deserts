"""Pipeline entry point.

    python -m pipeline.access_deserts.run --city sp

Steps: FETCH -> NORMALISE -> QUALITY for approved sources, then the city boundary.
Roles (sources.yaml): `service` records go to services/{source_id}.geojson (one file per source, so
the map can load dense layers only when shown); `context` layers are published
for display under context/{source_id}.geojson; `reference` layers are fetched for checks only.
Writes public/data/runs/{run_id}/ and updates public/data/runs/index.json.
Raw responses go to pipeline/cache/raw/{run_id}/ (not committed).
"""
from __future__ import annotations

import argparse
from collections import Counter
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from . import boundary as bnd
from . import config as cfg
from . import demand as dmd
from .adapters import wfs
from .adapters.csv_zip import fetch_csv_zip, parse_value
from .crs import ensure_lonlat
from .derive import derive_names
from .normalise import clean_placeholders, feature_key, mapped_value, normalise_services
from .output import create_run_dir, new_run_id, now_iso, previous_feature_ids, update_index, write_json
from .quality import layer_check, source_quality

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "access-deserts-pipeline (+https://github.com/thaisadeodato-k/Access-Deserts)"
STEPS_EXECUTED = ["fetch", "normalise", "quality", "boundary", "grid (demand)"]
STEPS_PENDING = ["classify + deduplicate (Phase 7)", "metrics (Phase 6)"]


def _git_commit() -> str | None:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _type_name_queried(pages: list[dict]) -> str | None:
    """TYPENAMES of the GetFeature request actually sent (first page), as the server received it."""
    if not pages:
        return None
    values = parse_qs(urlparse(pages[0]["url"]).query).get("TYPENAMES")
    return values[0] if values else None


def _context_features(features: list[dict], source: dict) -> list[dict]:
    """Display records for a context layer: id, name and type only."""
    fm = source.get("field_map") or {}
    return [{
        "type": "Feature",
        "geometry": f.get("geometry"),
        "properties": {
            "id": feature_key(source, f, i),
            "source_id": source["source_id"],
            "name": mapped_value(f.get("properties") or {}, fm.get("name")),
            "type": mapped_value(f.get("properties") or {}, fm.get("type")),
        },
    } for i, f in enumerate(features)]


def _process_source(session, source, city, params, raw_root, caps, runs_dir):
    """FETCH -> NORMALISE -> QUALITY for one source.

    Returns (records, quality, run record, lon/lat features, count error or None).
    `records` are services for role `service`, display records for `context`, [] for `reference`.
    """
    if source["protocol"] != "wfs":
        raise NotImplementedError(f"Protocol '{source['protocol']}' is not implemented yet")
    if source["role"] not in ("service", "context", "reference", "demand"):
        raise NotImplementedError(f"Role '{source['role']}' is not implemented yet")

    endpoint = source["endpoint_url"]
    if endpoint not in caps:
        host = urlparse(endpoint).hostname
        caps[endpoint] = wfs.get_capabilities(session, endpoint, raw_root / "_capabilities" / host, params["wfs"])
    caps_meta, layers = caps[endpoint]
    if source["layer"] not in layers:
        raise LookupError(f"Layer {source['layer']} not listed in GetCapabilities")

    fetched_at = now_iso()
    raw_dir = raw_root / source["source_id"]
    filter_info = None
    if source.get("record_filter"):
        _, total = wfs.count_hits(session, endpoint, source["layer"], raw_dir, params["wfs"])
        filter_info = {**source["record_filter"], "records_in_layer": total}
    res = wfs.fetch_layer(session, source, raw_dir, params["wfs"])
    if filter_info is not None:
        filter_info["records_kept"] = len(res["features"])
    features, crs_record = ensure_lonlat(res["features"], city["wgs84_envelope"], city["native_crs"], res["declared_crs"])
    features, placeholders = clean_placeholders(features, source)
    layer_info = layer_check(source["layer"], _type_name_queried(res["pages"]), layers)

    if source["role"] == "service":
        records, venues = normalise_services(features, source)
        current_ids = {s["properties"]["id"] for s in records}
        previous_ids = previous_feature_ids(runs_dir, city["city_code"], source["source_id"])
    else:
        records = _context_features(features, source) if source["role"] == "context" else []
        venues, current_ids, previous_ids = None, {feature_key(source, f, i) for i, f in enumerate(features)}, None

    quality = source_quality(
        source=source,
        features=features,
        current_ids=current_ids,
        fetched_at=fetched_at,
        metadata_urls=layers[source["layer"]]["urls"],
        internal_host_pattern=city["internal_host_pattern"],
        empty_threshold=params["quality"]["empty_field_threshold"],
        previous_ids=previous_ids,
        layer_info=layer_info,
        services=records if source["role"] == "service" else None,
        venue_grouping=venues,
        record_filter=filter_info,
    )
    if source.get("placeholder_values"):
        quality["placeholder_values"] = {"values": source["placeholder_values"], "replaced_by_null": placeholders}
    n, matched = len(res["features"]), res["number_matched"]
    count_error = (f"Count mismatch: server reported {matched}, received {n}"
                   if matched is not None and matched != n else None)
    record = {
        "source_id": source["source_id"],
        "layer": source["layer"],
        "type_name_queried": layer_info["type_name_queried"],
        "layer_check": layer_info,
        "endpoint_url": endpoint,
        "role": source["role"],
        "category": source.get("category"),
        "subcategory": source.get("subcategory"),
        "sort_by": source.get("sort_by"),
        "page_size": source.get("page_size") or params["wfs"]["page_size"],
        "id_field": source.get("id_field"),
        "record_filter": filter_info,
        "field_map": source.get("field_map"),
        "inclusion_rules": source.get("inclusion_rules"),
        "subcategory_rules": source.get("subcategory_rules"),
        "venue_grouping": source.get("venue_grouping"),
        "record_overrides": source.get("record_overrides") or [],
        "placeholder_values": source.get("placeholder_values"),
        "derived_name": source.get("derived_name"),
        "highlight_fields": source.get("highlight_fields"),
        "fetched_at": fetched_at,
        "number_matched_reported": matched,
        "features_returned": n,
        "features_normalised": len(records) if source["role"] == "service" else None,
        "features_included_in_metrics": (sum(s["properties"]["included_in_metrics"] for s in records)
                                         if source["role"] == "service" else None),
        "count_check": count_error or ("ok" if matched is not None else "server did not report numberMatched"),
        "crs": crs_record,
        "raw_dir": f"{source['source_id']}/",
        "pages": res["pages"],
    }
    return records, quality, record, features, count_error


def _process_csv(session, source, city, params, raw_root):
    """FETCH a census CSV (ZIP), keep the city's rows. Returns (quality, run record, rows)."""
    fetched_at = now_iso()
    res = fetch_csv_zip(session, source, raw_root / source["source_id"], str(city["ibge_code"]),
                        params["wfs"]["timeout_s"], params["wfs"]["retries"])
    statuses = {c: dict(Counter(parse_value(r[c], source["csv"]["decimal"])[1] for r in res["rows"].values()))
                for c in res["columns"]}
    quality = {
        "source_id": source["source_id"], "name": source["name"], "publisher": source["publisher"],
        "layer": source["layer"], "role": source["role"], "category": None, "fetched_at": fetched_at,
        "record_count": len(res["rows"]), "rows_in_file": res["rows_in_file"],
        "filter": f"{source['csv']['key']} starts with {city['ibge_code']}",
        "value_status": statuses,
        "value_status_note": "ok = number; suppressed = 'X'; not_available = '.'; both are missing, never zero.",
    }
    record = {
        "source_id": source["source_id"], "layer": source["layer"], "endpoint_url": source["endpoint_url"],
        "role": source["role"], "protocol": "csv", "csv": source["csv"], "fetched_at": fetched_at,
        "rows_in_file": res["rows_in_file"], "rows_kept": len(res["rows"]),
        "features_returned": len(res["rows"]), "features_included_in_metrics": None,
        "count_check": "not applicable (file download)", "crs": {"action": "not applicable (table)"},
        "raw_dir": f"{source['source_id']}/", "pages": [res["file"]],
    }
    return quality, record, res["rows"]


def _demand(city, params, by_source, tables, boundary_geom, proj):
    """Tracts -> H3 hexagons. Returns (hexagon features, summary for run.json/quality.json)."""
    conf = city["demand"]
    need = [conf["tracts"]["source_id"]]
    missing = [s for s in need if s not in by_source] + [
        s for s in (conf["population"]["source_id"], conf["income"]["source_id"]) if s not in tables]
    if missing:
        raise LookupError(f"Demand sources not available in this run: {missing}")
    decimals = {"population": conf["population"]["_decimal"], "income": conf["income"]["_decimal"]}
    pop_rows, inc_rows = tables[conf["population"]["source_id"]], tables[conf["income"]["source_id"]]
    tracts = dmd.build_tracts(by_source[conf["tracts"]["source_id"]], pop_rows, inc_rows, conf, decimals)
    checks = dmd.tract_checks(tracts, pop_rows, inc_rows)
    p = params["demand"]
    hexes = dmd.hex_grid(boundary_geom, params["h3_resolution"], proj)
    dmd.interpolate(tracts, hexes, proj)
    cmp_conf = conf["tracts"].get("comparison_index") or {}
    dmd.finish(hexes, p["income_coverage_threshold"], cmp_conf.get("vulnerable_from"))
    scored = dmd.vulnerability(hexes)
    districts = by_source.get((city.get("boundary") or {}).get("source_id"))
    district_display = ([{"geometry": f["geometry"], "properties": {"name": (f.get("properties") or {}).get(
        conf.get("district_name_field", "nm_distrito_municipal"))}} for f in districts] if districts else None)
    comparison = (dmd.comparison(hexes, p["comparison_min_coverage"], district_display, proj)
                  if cmp_conf else None)
    hex_pop = sum(h["props"]["population_est"] for h in hexes)
    summary = {
        "method": {
            "h3_resolution": params["h3_resolution"],
            "hexagons": "H3 cells intersecting the city boundary",
            "interpolation": "area-weighted from census tracts (uniform population within each tract)",
            "population": f"{conf['population']['source_id']}.{conf['population']['field']}",
            "income": (f"{conf['income']['source_id']}.{conf['income']['mean_field']} (mean income of household heads "
                       f"with income), weighted by {conf['income']['weight_field']} (all household heads) x area share; "
                       "suppressed and unavailable values are missing"),
            "income_bias": ("The mean excludes household heads without income; the number of heads with income is "
                            "not published by tract, so the mean cannot be adjusted and overstates income where many "
                            "heads have no income."),
            "income_coverage_threshold": p["income_coverage_threshold"],
            "vulnerability_score": "1 - percentile rank of income_est among populated hexagons with income (1 = lowest income)",
            "comparison_index": cmp_conf.get("label"),
        },
        "tracts": checks,
        "hexagons": len(hexes),
        "hexagons_populated": sum(h["props"]["population_est"] > 0 for h in hexes),
        "hexagons_with_income": sum(h["props"]["income_est"] is not None for h in hexes),
        "hexagons_scored": scored,
        "population_in_hexagons": round(hex_pop),
        "population_in_tracts": round(checks["population_total"]),
        "sensitivity": dmd.sensitivity(hexes, p["sensitivity_thresholds"]),
        "comparison": comparison,
    }
    return [dmd.to_feature(h) for h in hexes], summary


def _boundary(city, by_source, proj):
    """Union of the configured boundary source and its consistency check. Returns (geometry, record)."""
    conf = city.get("boundary")
    if not conf:
        return None, {"method": None, "note": "No boundary configured for this city."}
    if conf["source_id"] not in by_source:
        return None, {**conf, "note": f"Boundary source {conf['source_id']} not available in this run."}
    geom = bnd.union_boundary(by_source[conf["source_id"]], proj)
    check_id = conf.get("check_against")
    check = (bnd.consistency_check(geom, by_source.get(check_id, []), proj, check_id) if check_id else None)
    return geom, {**conf, "native_crs": city["native_crs"], "area_km2": round(geom.area / 1e6, 3),
                  "features_unioned": len(by_source[conf["source_id"]]), "consistency_check": check}


def run(city_code: str, data_dir: Path, cache_dir: Path, config_dir: Path = cfg.CONFIG_DIR, session=None) -> tuple[str, str]:
    params = cfg.load_params(config_dir)
    city = cfg.load_city(city_code, config_dir)
    sources = cfg.approved_sources(city, cfg.load_sources(config_dir))

    runs_dir = data_dir / "runs"
    run_id = new_run_id()
    run_dir = create_run_dir(runs_dir, run_id)
    raw_root = cache_dir / "raw" / run_id
    started_at = now_iso()

    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

    caps: dict = {}
    all_services, qualities, records, errors = [], [], [], []
    service_ids: list[str] = []
    context: dict[str, list[dict]] = {}
    by_source: dict[str, list[dict]] = {}
    tables: dict[str, dict] = {}
    for source in sources:
        print(f"[{source['source_id']}] fetching {source['layer']} ...", flush=True)
        if source["protocol"] == "csv":
            try:
                quality, record, rows = _process_csv(session, source, city, params, raw_root)
            except Exception as e:
                errors.append({"source_id": source["source_id"], "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)})
                print(f"[{source['source_id']}] FAILED: {e}", flush=True)
                continue
            tables[source["source_id"]] = rows
            qualities.append(quality)
            records.append(record)
            print(f"[{source['source_id']}] {record['rows_kept']} of {record['rows_in_file']} rows kept", flush=True)
            continue
        try:
            out, quality, record, features, count_error = _process_source(
                session, source, city, params, raw_root, caps, runs_dir)
        except Exception as e:  # one failing source must not hide the others
            errors.append({"source_id": source["source_id"], "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)})
            print(f"[{source['source_id']}] FAILED: {e}", flush=True)
            continue
        if count_error:
            errors.append({"source_id": source["source_id"], "error": count_error})
        if source["role"] == "service":
            all_services.extend(out)
            service_ids.append(source["source_id"])
        elif source["role"] == "context":
            context[source["source_id"]] = out
        by_source[source["source_id"]] = features
        qualities.append(quality)
        records.append(record)
        inc = record["features_included_in_metrics"]
        print(f"[{source['source_id']}] {record['features_returned']} features in {len(record['pages'])} page(s)"
              + (f"; included in metrics {inc}" if inc is not None else "") + f"; CRS: {record['crs']['action']}", flush=True)

    proj = bnd.Projector(city["native_crs"])
    by_quality = {q["source_id"]: q for q in qualities}
    by_record = {r["source_id"]: r for r in records}
    for source in sources:
        conf = source.get("derived_name")
        if not conf or source["source_id"] not in by_quality:
            continue
        own = [s for s in all_services if s["properties"]["source_id"] == source["source_id"]]
        if conf["from_source"] not in by_source:
            summary = {"error": f"Source {conf['from_source']} not available in this run; names left null."}
            errors.append({"source_id": source["source_id"], "error": summary["error"]})
        else:
            summary = derive_names(own, by_source[conf["from_source"]], conf, proj)
        by_quality[source["source_id"]]["name_derivation"] = summary
        by_record[source["source_id"]]["name_derivation"] = summary
    try:
        boundary_geom, boundary_record = _boundary(city, by_source, proj)
    except Exception as e:
        boundary_geom, boundary_record = None, {"error": f"{type(e).__name__}: {e}"}
        errors.append({"source_id": None, "error": f"Boundary: {type(e).__name__}: {e}"})
    if boundary_geom is not None:
        outside = bnd.outside_records(all_services, boundary_geom, proj)
        for q in qualities:
            o = outside.get(q["source_id"])
            if o is not None:
                q["pct_outside_city_boundary"] = o["pct_outside"]
                q["pct_outside_city_boundary_note"] = (
                    f"Records whose geometry does not intersect the city boundary ({boundary_record['method']} of "
                    f"{boundary_record['source_id']}).")
                q["outside_city_boundary"] = o
            elif q.get("role") != "service":
                q["pct_outside_city_boundary_note"] = "Not applicable (not a service layer)."

    hexagons, demand_summary = None, None
    if city.get("demand"):
        if boundary_geom is None:
            demand_summary = {"error": "No city boundary in this run; demand step skipped."}
            errors.append({"source_id": None, "error": demand_summary["error"]})
        else:
            for part in ("population", "income"):
                sid = city["demand"][part]["source_id"]
                src = next((s for s in sources if s["source_id"] == sid), None)
                city["demand"][part]["_decimal"] = (src or {}).get("csv", {}).get("decimal", ".")
            try:
                print("[demand] tracts -> hexagons ...", flush=True)
                hexagons, demand_summary = _demand(city, params, by_source, tables, boundary_geom, proj)
                print(f"[demand] {demand_summary['hexagons']} hexagons; population {demand_summary['population_in_hexagons']} "
                      f"(tracts {demand_summary['population_in_tracts']})", flush=True)
                if demand_summary["tracts"]["population_check"]["mismatches"]:
                    errors.append({"source_id": city["demand"]["tracts"]["source_id"],
                                   "error": f"Population check: {demand_summary['tracts']['population_check']['mismatches']} "
                                            "tracts differ from the reference population"})
            except Exception as e:
                demand_summary = {"error": f"{type(e).__name__}: {e}"}
                errors.append({"source_id": None, "error": f"Demand: {type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)})

    if not sources:
        errors.append({"source_id": None, "error": "No approved sources for this city."})
    status = "failed" if not records else "completed_with_errors" if errors else "completed"
    finished_at = now_iso()
    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"

    outputs = ["quality.json", "run.json"]
    for sid in service_ids:
        feats = [s for s in all_services if s["properties"]["source_id"] == sid]
        write_json(run_dir / "services" / f"{sid}.geojson", {"type": "FeatureCollection", "features": feats})
        outputs.append(f"services/{sid}.geojson")
    write_json(run_dir / "quality.json", {"run_id": run_id, "city_code": city_code, "generated_at": finished_at,
                                          "sources": qualities, "demand": demand_summary})
    if hexagons is not None:
        write_json(run_dir / "hexagons.geojson", {"type": "FeatureCollection", "features": hexagons})
        outputs.append("hexagons.geojson")
    if boundary_geom is not None:
        write_json(run_dir / "boundary.geojson", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": proj.to_lonlat(boundary_geom),
            "properties": {"name": city["name"], "method": boundary_record["method"], "source_id": boundary_record["source_id"]}}]})
        outputs.append("boundary.geojson")
    for sid, feats in context.items():
        write_json(run_dir / "context" / f"{sid}.geojson", {"type": "FeatureCollection", "features": feats})
        outputs.append(f"context/{sid}.geojson")
    write_json(run_dir / "run.json", {
        "run_id": run_id,
        "city_code": city_code,
        "city_name": city["name"],
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "code_version": {"git_commit": _git_commit()},
        "environment": {"runner": "github-actions" if on_actions else "local", "python": platform.python_version()},
        "parameters": params,
        "steps": {"executed": STEPS_EXECUTED, "pending": STEPS_PENDING},
        "boundary": boundary_record,
        "demand": demand_summary,
        "polygon_distance": {"method_used": None, "note": "Distances are computed in Phase 6."},
        "capabilities": [{"endpoint_url": ep, **meta, "layers_listed": len(layers)} for ep, (meta, layers) in caps.items()],
        "sources": records,
        "raw_storage": {
            "committed": False,
            "local_path": f"pipeline/cache/raw/{run_id}/",
            "github_artifact": f"raw-{run_id}" if on_actions else None,
            "artifact_retention_days": 90 if on_actions else None,
            "release": None,
            "note": "Raw responses are not committed; page hashes (sha256) are listed per source. "
                    "Snapshot runs get their raw files attached to a GitHub Release.",
        },
        "errors": errors,
        "outputs": outputs,
    })
    update_index(runs_dir, {"run_id": run_id, "city_code": city_code, "started_at": started_at,
                            "finished_at": finished_at, "status": status})

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"run_id={run_id}\nstatus={status}\n")
    print(f"Run {run_id}: {status}. {len(all_services)} service records written to {run_dir}", flush=True)
    return run_id, status


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Access Deserts data pipeline")
    p.add_argument("--city", default="sp")
    p.add_argument("--data-dir", type=Path, default=REPO_ROOT / "public" / "data")
    p.add_argument("--cache-dir", type=Path, default=REPO_ROOT / "pipeline" / "cache")
    a = p.parse_args(argv)
    _, status = run(a.city, a.data_dir, a.cache_dir)
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
