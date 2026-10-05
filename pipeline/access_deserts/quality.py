"""Per-source quality record for quality.json.

Metrics that later phases will compute are present as null with a `pending` note,
so the file shape is stable across phases.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .adapters.wfs import urls_in
from .normalise import (
    MISSING_COORDINATES,
    has_coords,
    inclusion,
    mapped_value,
    matching_rules,
    override_applies,
    overrides_by_feature,
    rule_reasons,
)

# Rule findings list the matching records by name only when there are this many or fewer.
MAX_LISTED_RECORDS = 10
VERSION_SUFFIX = re.compile(r"_v\d+$")


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


def inclusion_summary(features: list[dict], rules: list[dict], overrides: dict[str, dict] | None = None) -> dict:
    """Counts per inclusion rule (a record can match several), overrides, and included/excluded totals."""
    overrides = overrides or {}
    matched = [0] * len(rules)
    for f in features:
        for i in matching_rules(f.get("properties") or {}, rules):
            matched[i] += 1
    included = sum(inclusion(f, rules, overrides.get(f.get("id")))[0] for f in features)
    by_id = {f.get("id"): f for f in features}
    override_report = []
    for fid, o in overrides.items():
        f = by_id.get(fid)
        reasons = rule_reasons(f, rules) if f else []
        override_report.append({
            **o,
            "found": f is not None,
            "applied": f is not None and override_applies(f, o),
            "rule_result": None if f is None else ("excluded: " + "; ".join(reasons)) if reasons else "included",
        })
    return {
        "included_in_metrics": included,
        "excluded_from_metrics": len(features) - included,
        "rules": [{**r, "matched": matched[i]} for i, r in enumerate(rules)]
                 + [{"field": "geometry", "equals": None, "include": False, "reason": MISSING_COORDINATES,
                     "matched": sum(not has_coords(f) for f in features), "built_in": True}],
        "overrides": override_report,
    }


def _record(f: dict, field_map: dict) -> dict:
    props = f.get("properties") or {}
    return {
        "feature_id": f.get("id"),
        "name": mapped_value(props, field_map.get("name")),
        "equipment_type": mapped_value(props, field_map.get("type")),
        "administrative_sphere": mapped_value(props, field_map.get("sphere")),
    }


def _names(records: list[dict]) -> str:
    return "; ".join(
        (r["name"] or r["feature_id"]) + (f" ({r['administrative_sphere']})" if r["administrative_sphere"] else "")
        for r in records
    )


def rule_findings(features: list[dict], rules: list[dict], field_map: dict, overrides: dict[str, dict]) -> list[dict]:
    """Findings about what the inclusion rules did in this run.

    - exclusion rules matching few records list those records, so they can be reviewed;
    - inclusion rules whose records are still excluded by another rule are reported, because
      the include rule then has no effect on them.
    """
    out = []
    for i, r in enumerate(rules):
        hits = [f for f in features if i in matching_rules(f.get("properties") or {}, rules)]
        if not hits:
            continue
        cond = f"{r['field']} = {r['equals']}"
        if not r["include"] and len(hits) <= MAX_LISTED_RECORDS:
            records = [_record(f, field_map) for f in hits]
            out.append({
                "kind": "rule_matches", "highlight": False, "rule_reason": r["reason"], "count": len(hits),
                "records": records,
                "text": f'{len(hits)} record(s) match the exclusion rule "{r["reason"]}" ({cond}): {_names(records)}.',
            })
        if r["include"]:
            still_excluded = [f for f in hits if not inclusion(f, rules, overrides.get(f.get("id")))[0]]
            if still_excluded:
                records = [_record(f, field_map) for f in still_excluded][:MAX_LISTED_RECORDS]
                out.append({
                    "kind": "include_rule_without_effect", "highlight": False, "rule_reason": r["reason"],
                    "count": len(still_excluded), "records": records,
                    "text": f'The inclusion rule "{r["reason"]}" ({cond}) matches {len(hits)} record(s), but '
                            f"{len(still_excluded)} of them are excluded by other rules (exclusion takes precedence): "
                            f"{_names(records)}.",
                })
    return out


def layer_check(layer: str, type_name_queried: str | None, layers: dict) -> dict:
    """What was queried versus what GetCapabilities lists, including version-like names.

    Version suffixes (e.g. `_v2`) can appear as other published layers or as keywords of the
    queried layer (often the name of the underlying table). Both are recorded, never acted on.
    """
    base = VERSION_SUFFIX.sub("", layer)
    entry = layers.get(layer) or {}
    keywords = entry.get("keywords", [])
    return {
        "layer_configured": layer,
        "type_name_queried": type_name_queried,
        "layer_in_capabilities": layer in layers,
        "title": entry.get("title"),
        "abstract": entry.get("abstract"),
        "keywords": keywords,
        "version_keywords": [k for k in keywords if VERSION_SUFFIX.search(k)],
        "similar_layers_in_capabilities": sorted(
            n for n in layers if n != layer and (n.startswith(f"{layer}_") or VERSION_SUFFIX.sub("", n) == base)
        ),
    }


def highlighted_findings(profile: dict[str, float | None], highlight_fields: dict[str, str]) -> list[dict]:
    """Findings for configured attributes, computed from this run's data."""
    out = []
    for field, label in highlight_fields.items():
        pct = profile.get(field)
        text = (f"{label} ({field}): attribute not present in this run's data." if pct is None and field not in profile
                else f"{label} ({field}) is {pct:g}% empty in this run.")
        out.append({"kind": "empty_field", "highlight": True, "field": field, "label": label,
                    "pct_empty": pct, "text": text})
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
    layer_info: dict | None = None,
) -> dict:
    n = len(features)
    rules = source.get("inclusion_rules") or []
    overrides = overrides_by_feature(source)
    missing = sum(not has_coords(f) for f in features)
    profile = attribute_profile(features)
    data_urls = urls_in([f.get("properties") for f in features])
    return {
        "source_id": source["source_id"],
        "name": source["name"],
        "publisher": source["publisher"],
        "layer": source["layer"],
        "layer_check": layer_info,
        "fetched_at": fetched_at,
        "record_count": n,
        "findings": highlighted_findings(profile, source.get("highlight_fields") or {})
                    + rule_findings(features, rules, source.get("field_map") or {}, overrides),
        "inclusion": inclusion_summary(features, rules, overrides),
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
