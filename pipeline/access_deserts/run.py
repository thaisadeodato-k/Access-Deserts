"""Pipeline entry point.

    python -m pipeline.access_deserts.run --city sp

Phase 2 steps: FETCH -> NORMALISE -> QUALITY for approved service sources.
Writes public/data/runs/{run_id}/{services.geojson, quality.json, run.json} and updates
public/data/runs/index.json. Raw responses go to pipeline/cache/raw/{run_id}/ (not committed).
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

from . import config as cfg
from .adapters import wfs
from .crs import ensure_lonlat
from .normalise import normalise_services
from .output import create_run_dir, new_run_id, now_iso, previous_feature_ids, update_index, write_json
from .quality import layer_check, source_quality

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "access-deserts-pipeline (+https://github.com/thaisadeodato-k/Access-Deserts)"
STEPS_EXECUTED = ["fetch", "normalise", "quality"]
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


def _process_source(session, source, city, params, raw_root, caps, runs_dir):
    """FETCH -> NORMALISE -> QUALITY for one source. Returns (services, quality, run record)."""
    if source["protocol"] != "wfs":
        raise NotImplementedError(f"Protocol '{source['protocol']}' is not implemented yet")
    if source["role"] != "service":
        raise NotImplementedError(f"Role '{source['role']}' outputs are not implemented yet (Phase 4/5)")

    endpoint = source["endpoint_url"]
    if endpoint not in caps:
        host = urlparse(endpoint).hostname
        caps[endpoint] = wfs.get_capabilities(session, endpoint, raw_root / "_capabilities" / host, params["wfs"])
    caps_meta, layers = caps[endpoint]
    if source["layer"] not in layers:
        raise LookupError(f"Layer {source['layer']} not listed in GetCapabilities")

    fetched_at = now_iso()
    raw_dir = raw_root / source["source_id"]
    res = wfs.fetch_layer(session, source, raw_dir, params["wfs"])
    features, crs_record = ensure_lonlat(res["features"], city["wgs84_envelope"], city["native_crs"], res["declared_crs"])
    services = normalise_services(features, source)
    layer_info = layer_check(source["layer"], _type_name_queried(res["pages"]), layers)

    quality = source_quality(
        source=source,
        features=features,
        current_ids={s["properties"]["id"] for s in services},
        fetched_at=fetched_at,
        metadata_urls=layers[source["layer"]]["urls"],
        internal_host_pattern=city["internal_host_pattern"],
        empty_threshold=params["quality"]["empty_field_threshold"],
        previous_ids=previous_feature_ids(runs_dir, city["city_code"], source["source_id"]),
        layer_info=layer_info,
    )
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
        "field_map": source.get("field_map"),
        "inclusion_rules": source.get("inclusion_rules"),
        "record_overrides": source.get("record_overrides") or [],
        "highlight_fields": source.get("highlight_fields"),
        "fetched_at": fetched_at,
        "number_matched_reported": res["number_matched"],
        "features_returned": len(res["features"]),
        "features_normalised": len(services),
        "features_included_in_metrics": sum(s["properties"]["included_in_metrics"] for s in services),
        "count_check": (
            "ok" if res["number_matched"] == len(res["features"])
            else f"MISMATCH: server reported {res['number_matched']}, received {len(res['features'])}"
            if res["number_matched"] is not None else "server did not report numberMatched"
        ),
        "crs": crs_record,
        "raw_dir": f"{source['source_id']}/",
        "pages": res["pages"],
    }
    return services, quality, record


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
    for source in sources:
        print(f"[{source['source_id']}] fetching {source['layer']} ...", flush=True)
        try:
            services, quality, record = _process_source(session, source, city, params, raw_root, caps, runs_dir)
        except Exception as e:  # one failing source must not hide the others
            errors.append({"source_id": source["source_id"], "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)})
            print(f"[{source['source_id']}] FAILED: {e}", flush=True)
            continue
        all_services.extend(services)
        qualities.append(quality)
        records.append(record)
        print(f"[{source['source_id']}] {record['features_returned']} features in {len(record['pages'])} page(s); "
              f"included in metrics {record['features_included_in_metrics']}; CRS: {record['crs']['action']}", flush=True)

    if not sources:
        errors.append({"source_id": None, "error": "No approved sources for this city."})
    status = "failed" if not records else "completed_with_errors" if errors else "completed"
    finished_at = now_iso()
    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"

    write_json(run_dir / "services.geojson", {"type": "FeatureCollection", "features": all_services})
    write_json(run_dir / "quality.json", {"run_id": run_id, "city_code": city_code, "generated_at": finished_at, "sources": qualities})
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
        "polygon_distance": {"method_used": None, "note": "No polygon service sources in this run."},
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
        "outputs": ["services.geojson", "quality.json", "run.json"],
    })
    update_index(runs_dir, {"run_id": run_id, "city_code": city_code, "started_at": started_at,
                            "finished_at": finished_at, "status": status})

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"run_id={run_id}\nstatus={status}\n")
    print(f"Run {run_id}: {status}. {len(all_services)} service points written to {run_dir}", flush=True)
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
