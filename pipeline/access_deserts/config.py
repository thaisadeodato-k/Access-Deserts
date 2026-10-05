"""Load and validate the YAML configuration in pipeline/config/."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PROTOCOLS = {"wfs", "csv", "geojson", "overpass", "api"}
REQUIRED_SOURCE_KEYS = ("source_id", "city_code", "name", "publisher", "layer", "endpoint_url", "protocol", "role", "approved")


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
