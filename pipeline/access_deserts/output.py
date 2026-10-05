"""Run folders under public/data/runs/ and the runs index. Runs are never overwritten."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

INDEX_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id(today: str | None = None) -> str:
    """ISO date + short random id, e.g. 2026-10-05-3fa9c2."""
    return f"{today or datetime.now(timezone.utc).date().isoformat()}-{secrets.token_hex(3)}"


def write_json(path: Path, data) -> None:
    """JSON with indentation (readable diffs); .geojson files compact, since they are large."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if path.suffix == ".geojson":
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def create_run_dir(runs_dir: Path, run_id: str) -> Path:
    d = runs_dir / run_id
    if d.exists():
        raise FileExistsError(f"Run folder already exists and will not be overwritten: {d}")
    d.mkdir(parents=True)
    return d


def read_index(runs_dir: Path) -> dict:
    p = runs_dir / "index.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"schema_version": INDEX_SCHEMA_VERSION, "latest": {}, "runs": []}


def update_index(runs_dir: Path, entry: dict) -> dict:
    """Add a run (newest first). Only a completed run becomes `latest` for its city."""
    index = read_index(runs_dir)
    if any(r["run_id"] == entry["run_id"] for r in index["runs"]):
        raise ValueError(f"run_id {entry['run_id']} already in index.json")
    index["runs"].insert(0, {**entry, "snapshot": False, "path": f"runs/{entry['run_id']}/"})
    if entry["status"] == "completed":
        index["latest"][entry["city_code"]] = entry["run_id"]
    write_json(runs_dir / "index.json", index)
    return index


def previous_feature_ids(runs_dir: Path, city_code: str, source_id: str) -> set[str] | None:
    """Feature ids of `source_id` in the latest completed run for the city, or None if absent."""
    run_id = read_index(runs_dir)["latest"].get(city_code)
    if not run_id:
        return None
    run_dir = runs_dir / run_id
    quality = json.loads((run_dir / "quality.json").read_text(encoding="utf-8"))
    if not any(q["source_id"] == source_id for q in quality["sources"]):
        return None
    services = json.loads((run_dir / "services.geojson").read_text(encoding="utf-8"))
    return {f["properties"]["id"] for f in services["features"] if f["properties"]["source_id"] == source_id}
