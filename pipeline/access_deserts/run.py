"""Pipeline entry point.

    python -m pipeline.access_deserts.run --city sp

Steps: FETCH -> NORMALISE -> QUALITY for approved sources, then the city boundary.
Roles (sources.yaml): `service` records go to services.geojson; `context` layers are published
for display under context/{source_id}.geojson; `reference` layers are fetched for checks only.
Writes public/data/runs/{run_id}/ and updates public/data/runs/index.json.
Raw responses go to pipeline/cache/raw/{run_id}/ (not committed).
"""
from __future__ import annotations

import argparse
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
from .adapters import wfs
from .crs import ensure_lonlat
from .normalise import feature_key, mapped_value, normalise_services
from .output import create_run_dir, new_run_id, now_iso, previous_feature_ids, update_index, write_json
from .quality import layer_check, source_quality

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "access-deserts-pipeline (+https://github.com/thaisadeodato-k/Access-Deserts)"
STEPS_EXECUTED = ["fetch", "normalise", "quality", "boundary"]
STEPS_PENDING = ["classify + deduplicate (Phase 7)", "grid (Phase 5)", "metrics (Phase 6)"]


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
    if source["role"] not in ("service", "context", "reference"):
        raise NotImplementedError(f"Role '{source['role']}' is not implemented yet (Phase 5)")

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
    context: dict[str, list[dict]] = {}
    by_source: dict[str, list[dict]] = {}
    for source in sources:
        print(f"[{source['source_id']}] fetching {source['layer']} ...", flush=True)
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
        elif source["role"] == "context":
            context[source["source_id"]] = out
        by_source[source["source_id"]] = features
        qualities.append(quality)
        records.append(record)
        inc = record["features_included_in_metrics"]
        print(f"[{source['source_id']}] {record['features_returned']} features in {len(record['pages'])} page(s)"
              + (f"; included in metrics {inc}" if inc is not None else "") + f"; CRS: {record['crs']['action']}", flush=True)

    proj = bnd.Projector(city["native_crs"])
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

    if not sources:
        errors.append({"source_id": None, "error": "No approved sources for this city."})
    status = "failed" if not records else "completed_with_errors" if errors else "completed"
    finished_at = now_iso()
    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"

    outputs = ["services.geojson", "quality.json", "run.json"]
    write_json(run_dir / "services.geojson", {"type": "FeatureCollection", "features": all_services})
    write_json(run_dir / "quality.json", {"run_id": run_id, "city_code": city_code, "generated_at": finished_at, "sources": qualities})
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
