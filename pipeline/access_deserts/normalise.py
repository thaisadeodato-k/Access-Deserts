"""Convert source features into the common services schema.

No record is dropped: records that should not count are kept with
`included_in_metrics: false` and an `exclusion_reason`.
"""
from __future__ import annotations

MISSING_COORDINATES = "missing coordinates"


def has_coords(f: dict) -> bool:
    g = f.get("geometry")
    return bool(g and g.get("coordinates"))


def _mapped(props: dict, spec) -> str | None:
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


def inclusion(f: dict, rules: list[dict]) -> tuple[bool, str | None]:
    """(included_in_metrics, exclusion_reason) for one source feature."""
    reasons = [] if has_coords(f) else [MISSING_COORDINATES]
    reasons += [rules[i]["reason"] for i in matching_rules(f.get("properties") or {}, rules) if not rules[i]["include"]]
    return (not reasons, "; ".join(reasons) or None)


def normalise_services(features: list[dict], source: dict) -> list[dict]:
    field_map = source.get("field_map") or {}
    rules = source.get("inclusion_rules") or []
    out = []
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        included, reason = inclusion(f, rules)
        geometry = f["geometry"] if has_coords(f) else None
        out.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "id": feature_key(source, f, i),
                "source_id": source["source_id"],
                "name": _mapped(props, field_map.get("name")),
                "category": source.get("category"),
                "subcategory": source.get("subcategory"),
                "geometry_type": geometry["type"] if geometry else None,
                "address": _mapped(props, field_map.get("address")),
                "included_in_metrics": included,
                "exclusion_reason": reason,
            },
        })
    return out
