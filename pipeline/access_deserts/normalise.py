"""Convert source features into the common services schema."""
from __future__ import annotations


def _has_coords(f: dict) -> bool:
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


def normalise_services(features: list[dict], source: dict) -> list[dict]:
    """Normalised GeoJSON features. Features without coordinates are excluded (counted in quality)."""
    field_map = source.get("field_map") or {}
    out = []
    for i, f in enumerate(features):
        if not _has_coords(f):
            continue
        props = f.get("properties") or {}
        out.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "id": feature_key(source, f, i),
                "source_id": source["source_id"],
                "name": _mapped(props, field_map.get("name")),
                "category": source.get("category"),
                "subcategory": source.get("subcategory"),
                "geometry_type": f["geometry"]["type"],
                "address": _mapped(props, field_map.get("address")),
            },
        })
    return out
