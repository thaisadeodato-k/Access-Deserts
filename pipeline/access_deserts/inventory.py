"""Inventory of layers that are not approved yet, so their use can be decided on evidence.

    python -m pipeline.access_deserts.inventory --city sp

For every non-approved service/context source in sources.yaml and every candidate in
candidates.yaml: GetCapabilities entry, DescribeFeatureType fields, feature count, geometry
types, coordinate check, per-field empty share and most frequent values, sample records and
the size of the GeoJSON as served. Read-only: nothing here changes configuration or run data.

Paging: layers without a primary key either reject STARTINDEX ("natural order") or, as seen on
GEOSAMPA_v_praca_largo, silently return empty pages. When that happens the inventory retries
with SORTBY on an identifier field confirmed by DescribeFeatureType (`cd_identificador` or
`cd_identificador_<layer>`) and reports whether that field is unique. It only tests: sort_by
is set in sources.yaml after approval. If SORTBY does not help either, one request with COUNT
above the reported total is tried (a per-source page_size would then be proposed).

Writes pipeline/discovery/inventory-{date}.json and .md (committed, reviewable). Raw responses
go to pipeline/cache/raw/inventory-{date}/ (not committed).
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
import yaml

from . import config as cfg
from .adapters import wfs
from .crs import ensure_lonlat
from .output import now_iso, write_json
from .quality import layer_check
from .run import REPO_ROOT, USER_AGENT

XSD = "http://www.w3.org/2001/XMLSchema"
TOP_VALUES = 10           # most frequent values listed per field
LIST_ALL_DISTINCT = 30    # fields with at most this many distinct values list them all
SAMPLES = 3
MAX_VALUE_CHARS = 80
MAX_SINGLE_PAGE = 50000  # largest COUNT tried when the server cannot page a layer


def load_candidates(config_dir: Path = cfg.CONFIG_DIR) -> list[dict]:
    with open(config_dir / "candidates.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [{**raw.get("defaults", {}), **c, "kind": "candidate"} for c in raw["candidates"]]


def describe_feature_type(session, endpoint: str, layer: str, raw_dir: Path, wfs_params: dict) -> tuple[dict, list[dict]]:
    """DescribeFeatureType (XML schema). Returns (page metadata, [{name, type, nillable}])."""
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "DescribeFeatureType", "TYPENAMES": layer}
    r = wfs._get(session, f"{endpoint}?{urlencode(q)}", wfs_params["timeout_s"], wfs_params["retries"])
    meta = wfs._save(raw_dir / "describe_feature_type.xsd", r)
    if r.status_code != 200:
        raise wfs.WFSError(f"DescribeFeatureType returned HTTP {r.status_code}")
    root = ET.fromstring(r.content)
    fields = [
        {"name": el.get("name"), "type": el.get("type"), "nillable": el.get("nillable") == "true"}
        for el in root.iter(f"{{{XSD}}}element")
        if el.get("name") and el.get("type") and not el.get("substitutionGroup")
    ]
    return meta, fields


def sort_field_candidates(layer: str, fields: list[dict]) -> list[str]:
    """Identifier fields confirmed by DescribeFeatureType that SORTBY may be tested on."""
    short = layer.split(":", 1)[-1]
    wanted = ("cd_identificador", f"cd_identificador_{short}")
    return [f["name"] for f in fields if f["name"] in wanted and f["type"] in ("xsd:int", "xsd:long", "xsd:decimal")]


def _fetch(session, item, raw_dir, wfs_params) -> tuple[dict | None, str | None]:
    """fetch_layer plus a count check. Returns (result, error)."""
    try:
        res = wfs.fetch_layer(session, item, raw_dir, wfs_params)
    except Exception as e:
        return None, f"GetFeature: {type(e).__name__}: {e}"
    n, matched = len(res["features"]), res["number_matched"]
    if matched is not None and n != matched:
        return res, f"Count mismatch: server reported {matched}, paging returned {n}"
    return res, None


def _short(v):
    s = v if isinstance(v, str) else repr(v)
    return s if len(s) <= MAX_VALUE_CHARS else s[: MAX_VALUE_CHARS - 1] + "…"


def field_profile(features: list[dict], fields: list[dict]) -> list[dict]:
    """Empty share, distinct count and most frequent values for every schema field."""
    n = len(features)
    out = []
    names = [f["name"] for f in fields if not f["type"].startswith("gml:")]
    for name in names:
        values = [(f.get("properties") or {}).get(name) for f in features]
        present = [v for v in values if v not in (None, "") and not (isinstance(v, str) and not v.strip())]
        counts = Counter(_short(v) for v in present)
        listed = counts.most_common(None if len(counts) <= LIST_ALL_DISTINCT else TOP_VALUES)
        out.append({
            "field": name,
            "type": next(f["type"] for f in fields if f["name"] == name),
            "pct_empty": round(100 * (n - len(present)) / n, 2) if n else None,
            "distinct": len(counts),
            "values": [{"value": v, "count": c} for v, c in listed],
            "values_complete": len(counts) <= LIST_ALL_DISTINCT,
        })
    return out


def inventory_layer(session, item: dict, city: dict, caps: dict, raw_root: Path, wfs_params: dict) -> dict:
    layer, endpoint = item["layer"], item["endpoint_url"]
    raw_dir = raw_root / layer.replace(":", "_")
    _, layers = caps[endpoint]
    entry = {
        "layer": layer,
        "kind": item.get("kind", "source"),
        "source_id": item.get("source_id"),
        "role": item.get("role"),
        "category": item.get("category"),
        "subcategory": item.get("subcategory"),
        "purpose": item.get("purpose"),
        "count_at_verification": item.get("features_at_verification", item.get("features_at_discovery")),
        "layer_check": layer_check(layer, None, layers),
        "metadata_urls": (layers.get(layer) or {}).get("urls", []),
        "errors": [],
    }
    if layer not in layers:
        entry["errors"].append("Layer not listed in GetCapabilities")
        return entry

    try:
        _, fields = describe_feature_type(session, endpoint, layer, raw_dir, wfs_params)
    except Exception as e:  # keep going: the other layers are still useful
        entry["errors"].append(f"DescribeFeatureType: {type(e).__name__}: {e}")
        fields = []
    entry["schema"] = fields

    res, err = _fetch(session, item, raw_dir, wfs_params)
    entry["sort_by_tested"] = None
    if err:
        entry["paging_without_sort_by"] = err
        candidates = [] if item.get("sort_by") else sort_field_candidates(layer, fields)
        if not candidates:
            entry["errors"].append(err)
            if res is None:
                return entry
        else:
            field = candidates[0]
            res, err = _fetch(session, {**item, "sort_by": field}, raw_dir / f"sortby_{field}", wfs_params)
            values = [(f.get("properties") or {}).get(field) for f in (res or {}).get("features", [])]
            entry["sort_by_tested"] = {
                "field": field,
                "result": err or "ok",
                "values_unique": len(values) == len(set(values)) and None not in values,
            }
            if err:
                entry["errors"].append(f"With SORTBY={field}: {err}")
            if res is None:
                return entry
    # Last resort, seen on GEOSAMPA_v_praca_largo: STARTINDEX > 0 returns empty pages, but one
    # request large enough for the reported count returns everything.
    matched = res.get("number_matched")
    entry["single_page_tested"] = None
    if err and matched and matched <= MAX_SINGLE_PAGE:
        single, single_err = _fetch(session, item, raw_dir / "single_page", {**wfs_params, "page_size": matched + 1})
        entry["single_page_tested"] = {"count": matched + 1, "result": single_err or "ok"}
        if not single_err:
            entry["errors"] = [e for e in entry["errors"] if not e.startswith("With SORTBY=")]
            res = single
    feats = res["features"]
    ids = [f.get("id") or "" for f in feats]
    entry["feature_ids"] = {
        "examples": ids[:2],
        "generated": sum(".fid-" in i for i in ids),
        "unique": len(ids) == len(set(ids)),
    }
    entry["number_matched_reported"] = res["number_matched"]
    entry["features_returned"] = len(feats)
    entry["pages"] = len(res["pages"])
    entry["geojson_bytes_as_served"] = sum(p["bytes"] for p in res["pages"])
    entry["geometry_types"] = dict(Counter((f.get("geometry") or {}).get("type") for f in feats))
    try:
        _, crs = ensure_lonlat(feats, city["wgs84_envelope"], city["native_crs"], res["declared_crs"])
    except ValueError as e:
        crs = {"declared_crs": res["declared_crs"], "action": f"not determined: {e}"}
    entry["crs"] = crs
    entry["fields"] = field_profile(feats, fields)
    entry["samples"] = [
        {"id": f.get("id"), "geometry_type": (f.get("geometry") or {}).get("type"),
         "properties": {k: _short(v) if isinstance(v, str) else v for k, v in (f.get("properties") or {}).items()}}
        for f in feats[:SAMPLES]
    ]
    return entry


def to_markdown(report: dict) -> str:
    lines = [
        f"# Layer inventory – {report['city_code']} – {report['generated_at']}",
        "",
        "Generated by `python -m pipeline.access_deserts.inventory`. Read-only evidence for deciding",
        "which layers to approve and how to map their fields. Nothing here is used by the pipeline.",
        "",
        "| Layer | Kind | Role / purpose | Count (now / at verification) | Geometry | GeoJSON MB | Paging | Errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in report["layers"]:
        mb = f"{e['geojson_bytes_as_served'] / 1e6:.1f}" if "geojson_bytes_as_served" in e else "–"
        geom = ", ".join(f"{k} {v}" for k, v in (e.get("geometry_types") or {}).items()) or "–"
        lines.append(
            f"| `{e['layer']}` | {e['kind']} | {e.get('role') or e.get('purpose') or ''} | "
            f"{e.get('features_returned', '–')} / {e.get('count_at_verification', '–')} | {geom} | {mb} | "
            f"{_paging(e)} | {'; '.join(e['errors']) or '–'} |"
        )
    for e in report["layers"]:
        lc = e["layer_check"]
        lines += ["", f"## `{e['layer']}`", "",
                  f"- Title: {lc['title']}", f"- Abstract: {lc['abstract'] or '–'}",
                  f"- Keywords: {', '.join(lc['keywords']) or '–'}",
                  f"- Similar layers: {', '.join(lc['similar_layers_in_capabilities']) or '–'}",
                  f"- Metadata URLs: {', '.join(e['metadata_urls']) or '–'}"]
        if e.get("paging_without_sort_by"):
            lines.append(f"- Paging without SORTBY: {e['paging_without_sort_by']}")
        if e.get("sort_by_tested"):
            t = e["sort_by_tested"]
            lines.append(f"- SORTBY={t['field']} tested: {t['result']}; values unique: {t['values_unique']}")
        if e.get("single_page_tested"):
            t = e["single_page_tested"]
            lines.append(f"- Single request with COUNT={t['count']}: {t['result']}")
        if e.get("feature_ids"):
            fi = e["feature_ids"]
            lines.append(f"- Feature ids: e.g. {', '.join(fi['examples'])}; generated (unstable): {fi['generated']}; "
                         f"unique: {fi['unique']}")
        if "crs" in e:
            lines.append(f"- CRS: declared {e['crs'].get('declared_crs')}; {e['crs']['action']}")
        if e.get("fields"):
            lines += ["", "| Field | Type | % empty | Distinct | Values (count) |", "|---|---|---|---|---|"]
            for f in e["fields"]:
                vals = "; ".join(f"{v['value']} ({v['count']})" for v in f["values"]).replace("|", "\\|")
                more = "" if f["values_complete"] else f" … (top {len(f['values'])})"
                lines.append(f"| `{f['field']}` | {f['type']} | {f['pct_empty']} | {f['distinct']} | {vals}{more} |")
        for s in e.get("samples", []):
            lines += ["", f"Sample `{s['id']}` ({s['geometry_type']}):", "",
                      "```", yaml.safe_dump(s["properties"], allow_unicode=True, sort_keys=False).strip(), "```"]
    return "\n".join(lines) + "\n"


def _paging(e: dict) -> str:
    if not e.get("paging_without_sort_by"):
        return "ok" if "features_returned" in e else "–"
    single, t = e.get("single_page_tested"), e.get("sort_by_tested")
    if single and single["result"] == "ok":
        return f"only as a single request (COUNT={single['count']})"
    return f"needs SORTBY ({t['field']}: {t['result']})" if t else "fails"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Inventory of non-approved and candidate layers")
    p.add_argument("--city", default="sp")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "pipeline" / "discovery")
    p.add_argument("--cache-dir", type=Path, default=REPO_ROOT / "pipeline" / "cache")
    p.add_argument("--layers", nargs="*", help="Only these layer names (default: all)")
    a = p.parse_args(argv)

    params = cfg.load_params()
    city = cfg.load_city(a.city)
    items = [s for s in cfg.load_sources() if s["city_code"] == a.city and not s["approved"]
             and s["role"] in ("service", "context")]
    items += [c for c in load_candidates() if c["city_code"] == a.city]
    if a.layers:
        items = [i for i in items if i["layer"] in a.layers]
    for i in items:
        if urlparse(i["endpoint_url"]).hostname not in city["allowed_hosts"]:
            raise ValueError(f"{i['layer']}: host not in allowed_hosts")

    date = datetime.now(timezone.utc).date().isoformat()
    raw_root = a.cache_dir / "raw" / f"inventory-{date}"
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    caps = {}
    for ep in sorted({i["endpoint_url"] for i in items}):
        caps[ep] = wfs.get_capabilities(session, ep, raw_root / "_capabilities" / urlparse(ep).hostname, params["wfs"])

    layers = []
    for i in items:
        print(f"[{i['layer']}] ...", flush=True)
        e = inventory_layer(session, i, city, caps, raw_root, params["wfs"])
        print(f"[{i['layer']}] {e.get('features_returned', '–')} features; errors: {e['errors'] or 'none'}", flush=True)
        layers.append(e)

    report = {"city_code": a.city, "generated_at": now_iso(),
              "capabilities": [{"endpoint_url": ep, **meta} for ep, (meta, _) in caps.items()], "layers": layers}
    write_json(a.out_dir / f"inventory-{date}.json", report)
    (a.out_dir / f"inventory-{date}.md").write_text(to_markdown(report), encoding="utf-8", newline="\n")
    print(f"Wrote {a.out_dir / f'inventory-{date}.md'}", flush=True)
    return 1 if any(e["errors"] for e in layers) else 0


if __name__ == "__main__":
    sys.exit(main())
