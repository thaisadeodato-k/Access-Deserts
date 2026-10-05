"""Per-source quality record for quality.json.

Metrics that later phases will compute are present as null with a `pending` note,
so the file shape is stable across phases.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .adapters.wfs import urls_in
from .normalise import MISSING_COORDINATES, has_coords, inclusion, matching_rules


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 2) if d else None


def attribute_profile(features: list[dict]) -> dict[str, float]:
    """% of records with an empty value, for every attribute seen."""
    keys: list[str] = []
    for f in features:
        for k in (f.get("properties") or {}):
            if k not in keys:
                keys.append(k)
    return {
        k: _pct(sum(_empty((f.get("properties") or {}).get(k)) for f in features), len(features))
        for k in keys
    }


def internal_hosts(urls: list[str], pattern: str) -> list[str]:
    rx = re.compile(pattern, re.I)
    return sorted({h for h in (urlparse(u).hostname for u in urls) if h and rx.search(h)})


def inclusion_summary(features: list[dict], rules: list[dict]) -> dict:
    """Counts per inclusion rule (a record can match several) and overall included/excluded totals."""
    matched = [0] * len(rules)
    for f in features:
        for i in matching_rules(f.get("properties") or {}, rules):
            matched[i] += 1
    included = sum(inclusion(f, rules)[0] for f in features)
    return {
        "included_in_metrics": included,
        "excluded_from_metrics": len(features) - included,
        "rules": [{**r, "matched": matched[i]} for i, r in enumerate(rules)]
                 + [{"field": "geometry", "equals": None, "include": False, "reason": MISSING_COORDINATES,
                     "matched": sum(not has_coords(f) for f in features), "built_in": True}],
    }


def highlighted_findings(profile: dict[str, float | None], highlight_fields: dict[str, str]) -> list[dict]:
    """Findings for configured attributes, computed from this run's data."""
    out = []
    for field, label in highlight_fields.items():
        pct = profile.get(field)
        text = (f"{label} ({field}): attribute not present in this run's data." if pct is None and field not in profile
                else f"{label} ({field}) is {pct:g}% empty in this run.")
        out.append({"highlight": True, "field": field, "label": label, "pct_empty": pct, "text": text})
    return out


def change_vs_previous(current_ids: set[str], previous_ids: set[str] | None) -> dict:
    """Compares normalised feature ids with the previous completed run."""
    if previous_ids is None:
        return {"added": None, "removed": None, "note": "No previous completed run with this source."}
    return {"added": len(current_ids - previous_ids), "removed": len(previous_ids - current_ids), "note": None}


def source_quality(
    source: dict,
    features: list[dict],
    current_ids: set[str],
    fetched_at: str,
    metadata_urls: list[str],
    internal_host_pattern: str,
    empty_threshold: float,
    previous_ids: set[str] | None,
) -> dict:
    n = len(features)
    missing = sum(not has_coords(f) for f in features)
    profile = attribute_profile(features)
    data_urls = urls_in([f.get("properties") for f in features])
    return {
        "source_id": source["source_id"],
        "name": source["name"],
        "publisher": source["publisher"],
        "layer": source["layer"],
        "fetched_at": fetched_at,
        "record_count": n,
        "findings": highlighted_findings(profile, source.get("highlight_fields") or {}),
        "inclusion": inclusion_summary(features, source.get("inclusion_rules") or []),
        "change_vs_previous": change_vs_previous(current_ids, previous_ids),
        "pct_missing_coordinates": _pct(missing, n),
        "pct_outside_city_boundary": None,
        "pct_outside_city_boundary_note": "Pending: city boundary not yet chosen (Phase 4).",
        "duplicates_flagged": None,
        "pct_classified_by_ai": None,
        "fields_over_empty_threshold": {k: v for k, v in profile.items() if v is not None and v > 100 * empty_threshold},
        "empty_threshold_pct": 100 * empty_threshold,
        "attribute_empty_pct": profile,
        "census_suppression": None,
        "internal_hosts_in_metadata": internal_hosts(metadata_urls, internal_host_pattern),
        "internal_hosts_in_data": internal_hosts(data_urls, internal_host_pattern),
        "confidence": None,
        "confidence_rule": None,
        "pending": {
            "duplicates_flagged": "Phase 7 (deduplication)",
            "pct_classified_by_ai": "Phase 7 (AI classification)",
            "confidence": "Phase 7 (confidence rules)",
            "census_suppression": "Not applicable to this source (census sources only, Phase 5).",
        },
    }
