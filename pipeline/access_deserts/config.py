"""Load and validate the YAML configuration in pipeline/config/."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PROTOCOLS = {"wfs", "csv", "geojson", "overpass", "api"}
REQUIRED_SOURCE_KEYS = ("source_id", "city_code", "name", "publisher", "layer", "endpoint_url", "protocol", "role", "approved")
FIELD_MAP_KEYS = {"name", "address", "type", "sphere"}
OVERRIDE_KEYS = {"feature_id", "include", "reason", "evidence", "approved_on"}
# service: counted per category; context: published for display; reference: fetched for checks only
ROLES = {"service", "context", "reference", "demand"}


def _check_options(s: dict) -> None:
    """Optional per-source keys added in Phase 4 (approved 2026-10-05)."""
    sid = s["source_id"]
    if s["role"] not in ROLES:
        raise ValueError(f"Source {sid}: unknown role '{s['role']}'")
    if "id_field" in s and not (isinstance(s["id_field"], str) and s["id_field"]):
        raise ValueError(f"Source {sid}: id_field must be an attribute name")
    if "page_size" in s and not (isinstance(s["page_size"], int) and s["page_size"] > 0):
        raise ValueError(f"Source {sid}: page_size must be a positive integer")
    rf = s.get("record_filter")
    if rf is not None and (set(rf) != {"field", "equals"} or not rf["field"]):
        raise ValueError(f"Source {sid}: record_filter must be {{field, equals}}: {rf}")
    for r in s.get("subcategory_rules") or []:
        if set(r) != {"field", "equals", "subcategory"}:
            raise ValueError(f"Source {sid}: subcategory rule must have field, equals, subcategory: {r}")
    vg = s.get("venue_grouping")
    if vg is not None and (set(vg) != {"fields", "reason"} or not vg["fields"] or not vg["reason"]):
        raise ValueError(f"Source {sid}: venue_grouping must be {{fields: [...], reason}}: {vg}")


def _load(name: str, config_dir: Path) -> dict:
    with open(config_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_params(config_dir: Path = CONFIG_DIR) -> dict:
    return _load("params.yaml", config_dir)


def load_city(city_code: str, config_dir: Path = CONFIG_DIR) -> dict:
    cities = _load("cities.yaml", config_dir)
    if city_code not in cities:
        raise ValueError(f"Unknown city_code '{city_code}'. Configured: {sorted(cities)}")
    return {"city_code": city_code, **cities[city_code]}


def load_sources(config_dir: Path = CONFIG_DIR) -> list[dict]:
    raw = _load("sources.yaml", config_dir)
    defaults = raw.get("defaults", {})
    sources = [{**defaults, **s} for s in raw["sources"]]
    seen = set()
    for s in sources:
        missing = [k for k in REQUIRED_SOURCE_KEYS if k not in s]
        if missing:
            raise ValueError(f"Source {s.get('source_id')} is missing keys: {missing}")
        if s["protocol"] not in PROTOCOLS:
            raise ValueError(f"Source {s['source_id']}: unknown protocol '{s['protocol']}'")
        for r in s.get("inclusion_rules") or []:
            if set(r) != {"field", "equals", "include", "reason"} or not isinstance(r["include"], bool):
                raise ValueError(f"Source {s['source_id']}: inclusion rule must have field, equals, include (bool), reason: {r}")
        if set(s.get("field_map") or {}) - FIELD_MAP_KEYS:
            raise ValueError(f"Source {s['source_id']}: unknown field_map keys {sorted(set(s['field_map']) - FIELD_MAP_KEYS)}")
        ids = []
        for o in s.get("record_overrides") or []:
            if set(o) != OVERRIDE_KEYS or not isinstance(o["include"], bool) or not all(
                    o[k] for k in ("feature_id", "reason", "evidence", "approved_on")):
                raise ValueError(f"Source {s['source_id']}: record override must have non-empty "
                                 f"feature_id, include (bool), reason, evidence, approved_on: {o}")
            ids.append(o["feature_id"])
        if len(ids) != len(set(ids)):
            raise ValueError(f"Source {s['source_id']}: more than one override for the same feature_id")
        _check_options(s)
        if s["source_id"] in seen:
            raise ValueError(f"Duplicate source_id '{s['source_id']}'")
        seen.add(s["source_id"])
    return sources


def approved_sources(city: dict, sources: list[dict]) -> list[dict]:
    """Approved sources for the city. Refuses any endpoint host not in the city's allow-list."""
    out = []
    for s in sources:
        if s["city_code"] != city["city_code"] or not s["approved"]:
            continue
        host = urlparse(s["endpoint_url"]).hostname
        if host not in city["allowed_hosts"]:
            raise ValueError(f"Source {s['source_id']}: host '{host}' is not in allowed_hosts for {city['city_code']}")
        out.append(s)
    return out
