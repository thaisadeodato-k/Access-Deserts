"""Convert source features into the common services schema.

No record is dropped: records that should not count are kept with
`included_in_metrics: false` and an `exclusion_reason`. A per-record override
(`record_overrides` in sources.yaml, each approved by the author) replaces the rule
result for one record and is recorded in `override_reason`.

Optional per-source steps (configured in sources.yaml):
- `id_field`: the record id comes from this attribute instead of the WFS feature id
  (needed where the server generates unstable ids);
- `subcategory_rules`: records matching {field, equals} get another subcategory;
- `venue_grouping`: records sharing the same normalised address are one venue; only one
  record per venue is counted, the others are excluded with the configured reason;
- `placeholder_values`: {field: [values]} replaced by null before anything else (e.g. "No"
  in fields that never hold yes/no answers).
"""
from __future__ import annotations

import re
from collections import defaultdict

MISSING_COORDINATES = "missing coordinates"


def clean_placeholders(features: list[dict], source: dict) -> tuple[list[dict], dict[str, int]]:
    """Replace configured placeholder values by None. Returns (features, replacements per field)."""
    spec = source.get("placeholder_values") or {}
    if not spec:
        return features, {}
    counts = {field: 0 for field in spec}
    out = []
    for f in features:
        props = dict(f.get("properties") or {})
        for field, values in spec.items():
            if props.get(field) in values:
                props[field] = None
                counts[field] += 1
        out.append({**f, "properties": props})
    return out, counts


def has_coords(f: dict) -> bool:
    g = f.get("geometry")
    return bool(g and g.get("coordinates"))


def mapped_value(props: dict, spec) -> str | None:
    """Value of a field_map entry: an attribute name or a list of names joined with ', '."""
    if not spec:
        return None
    names = [spec] if isinstance(spec, str) else list(spec)
    parts = [str(props[n]).strip() for n in names if props.get(n) not in (None, "")]
    return ", ".join(parts) or None


def record_key(source: dict, f: dict, index: int | None = None) -> str:
    """Stable id of a record within its source: `id_field` value, else the WFS feature id."""
    id_field = source.get("id_field")
    if id_field:
        value = (f.get("properties") or {}).get(id_field)
        if value not in (None, ""):
            return str(value)
    return f.get("id") or f"#{index}"


def feature_key(source: dict, f: dict, index: int) -> str:
    return f"{source['source_id']}:{record_key(source, f, index)}"


def matching_rules(props: dict, rules: list[dict]) -> list[int]:
    """Indexes of the rules whose field equals the rule value."""
    return [i for i, r in enumerate(rules) if props.get(r["field"]) == r["equals"]]


def rule_reasons(f: dict, rules: list[dict]) -> list[str]:
    """Exclusion reasons from the built-in coordinate rule and the source's rules."""
    reasons = [] if has_coords(f) else [MISSING_COORDINATES]
    return reasons + [rules[i]["reason"] for i in matching_rules(f.get("properties") or {}, rules) if not rules[i]["include"]]


def override_applies(f: dict, override: dict | None) -> bool:
    """An override can include a record only if it has coordinates; it can always exclude one."""
    return override is not None and (not override["include"] or has_coords(f))


def inclusion(f: dict, rules: list[dict], override: dict | None = None) -> tuple[bool, str | None]:
    """(included_in_metrics, exclusion_reason) for one source feature, before venue grouping."""
    if override_applies(f, override):
        return (True, None) if override["include"] else (False, override["reason"])
    reasons = rule_reasons(f, rules)
    return (not reasons, "; ".join(reasons) or None)


def overrides_by_feature(source: dict) -> dict[str, dict]:
    return {str(o["feature_id"]): o for o in source.get("record_overrides") or []}


def subcategory(props: dict, source: dict) -> str | None:
    for r in source.get("subcategory_rules") or []:
        if props.get(r["field"]) == r["equals"]:
            return r["subcategory"]
    return source.get("subcategory")


def venue_key(props: dict, fields: list[str]) -> str | None:
    """Normalised address: lower case, punctuation and repeated spaces removed."""
    raw = " ".join(str(props.get(n) or "") for n in fields)
    key = re.sub(r"[\s,.;]+", " ", raw.lower()).strip()
    return key or None


def group_venues(out: list[dict], features: list[dict], source: dict) -> dict | None:
    """Assign venue ids and keep one counted record per venue. Returns a summary for quality.json."""
    cfg = source.get("venue_grouping")
    if not cfg:
        return None
    groups: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(features):
        key = venue_key(f.get("properties") or {}, cfg["fields"])
        groups[key if key else f"#{i}"].append(i)
    collapsed = 0
    for n, members in enumerate(sorted(groups.values(), key=lambda m: out[m[0]]["properties"]["id"]), start=1):
        for i in members:
            out[i]["properties"]["venue_id"] = f"{source['source_id']}:venue:{n}"
        counted = sorted((i for i in members if out[i]["properties"]["included_in_metrics"]),
                         key=lambda i: out[i]["properties"]["id"])
        for i in counted[1:]:
            out[i]["properties"]["included_in_metrics"] = False
            out[i]["properties"]["exclusion_reason"] = cfg["reason"]
            collapsed += 1
    return {
        "fields": cfg["fields"],
        "records": len(features),
        "venues": len(groups),
        "venues_with_several_records": sum(len(m) > 1 for m in groups.values()),
        "records_excluded_as_same_venue": collapsed,
        "reason": cfg["reason"],
    }


def normalise_services(features: list[dict], source: dict) -> tuple[list[dict], dict | None]:
    """Returns (normalised records, venue grouping summary or None)."""
    field_map = source.get("field_map") or {}
    rules = source.get("inclusion_rules") or []
    overrides = overrides_by_feature(source)
    grouped = bool(source.get("venue_grouping"))
    out = []
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        override = overrides.get(record_key(source, f, i))
        included, reason = inclusion(f, rules, override)
        geometry = f["geometry"] if has_coords(f) else None
        p = {
            "id": feature_key(source, f, i),
            "source_id": source["source_id"],
            "name": mapped_value(props, field_map.get("name")),
            "name_derived": False,
            "category": source.get("category"),
            "subcategory": subcategory(props, source),
            "geometry_type": geometry["type"] if geometry else None,
            "address": mapped_value(props, field_map.get("address")),
            "equipment_type": mapped_value(props, field_map.get("type")),
            "administrative_sphere": mapped_value(props, field_map.get("sphere")),
            "included_in_metrics": included,
            "exclusion_reason": reason,
            "override_reason": override["reason"] if override_applies(f, override) else None,
            "outside_boundary": None,  # set once the city boundary is known (run.py)
        }
        if grouped:
            p["venue_id"] = None
        out.append({"type": "Feature", "geometry": geometry, "properties": p})
    return out, group_venues(out, features, source)
