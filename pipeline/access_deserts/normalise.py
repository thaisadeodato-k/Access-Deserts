"""Convert source features into the common services schema.

No record is dropped: records that should not count are kept with
`included_in_metrics: false` and an `exclusion_reason`. A per-record override
(`record_overrides` in sources.yaml, each approved by the author) replaces the rule
result for one record and is recorded in `override_reason`.
"""
from __future__ import annotations

MISSING_COORDINATES = "missing coordinates"


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


def feature_key(source: dict, f: dict, index: int) -> str:
    return f"{source['source_id']}:{f.get('id') or f'#{index}'}"


def matching_rules(props: dict, rules: list[dict]) -> list[int]:
    """Indexes of the inclusion rules whose field equals the rule value."""
    return [i for i, r in enumerate(rules) if props.get(r["field"]) == r["equals"]]


def rule_reasons(f: dict, rules: list[dict]) -> list[str]:
    """Exclusion reasons from the built-in coordinate rule and the source's rules."""
    reasons = [] if has_coords(f) else [MISSING_COORDINATES]
    return reasons + [rules[i]["reason"] for i in matching_rules(f.get("properties") or {}, rules) if not rules[i]["include"]]


def override_applies(f: dict, override: dict | None) -> bool:
    """An override can include a record only if it has coordinates; it can always exclude one."""
    return override is not None and (not override["include"] or has_coords(f))


def inclusion(f: dict, rules: list[dict], override: dict | None = None) -> tuple[bool, str | None]:
    """(included_in_metrics, exclusion_reason) for one source feature."""
    if override_applies(f, override):
        return (True, None) if override["include"] else (False, override["reason"])
    reasons = rule_reasons(f, rules)
    return (not reasons, "; ".join(reasons) or None)


def overrides_by_feature(source: dict) -> dict[str, dict]:
    return {o["feature_id"]: o for o in source.get("record_overrides") or []}


def normalise_services(features: list[dict], source: dict) -> list[dict]:
    field_map = source.get("field_map") or {}
    rules = source.get("inclusion_rules") or []
    overrides = overrides_by_feature(source)
    out = []
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        override = overrides.get(f.get("id"))
        included, reason = inclusion(f, rules, override)
        geometry = f["geometry"] if has_coords(f) else None
        out.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "id": feature_key(source, f, i),
                "source_id": source["source_id"],
                "name": mapped_value(props, field_map.get("name")),
                "category": source.get("category"),
                "subcategory": source.get("subcategory"),
                "geometry_type": geometry["type"] if geometry else None,
                "address": mapped_value(props, field_map.get("address")),
                "equipment_type": mapped_value(props, field_map.get("type")),
                "administrative_sphere": mapped_value(props, field_map.get("sphere")),
                "included_in_metrics": included,
                "exclusion_reason": reason,
                "override_reason": override["reason"] if override_applies(f, override) else None,
            },
        })
    return out
