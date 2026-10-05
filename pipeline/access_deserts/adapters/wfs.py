"""WFS 2.0 adapter: GetCapabilities check and paginated GetFeature (GeoJSON output).

Every response is saved to the raw directory BEFORE it is parsed, and described
(url, HTTP status, bytes, sha256) in the returned metadata for run.json.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import requests

NS = {"wfs": "http://www.opengis.net/wfs/2.0", "xlink": "http://www.w3.org/1999/xlink", "ows": "http://www.opengis.net/ows/1.1"}
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class WFSError(RuntimeError):
    pass


def _get(session: requests.Session, url: str, timeout: float, retries: int) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code < 500:
                return r
            last = WFSError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            last = e
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise WFSError(f"Request failed after {retries} attempts: {last} ({url})")


def _save(raw_path: Path, r: requests.Response) -> dict:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(r.content)
    return {
        "url": r.url,
        "http_status": r.status_code,
        "bytes": len(r.content),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "raw_file": raw_path.name,
    }


def get_capabilities(session, endpoint: str, raw_dir: Path, wfs_params: dict) -> tuple[dict, dict]:
    """Fetch GetCapabilities. Returns (page metadata, {layer_name: {"title", "abstract", "keywords", "urls"}})."""
    url = f"{endpoint}?{urlencode({'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetCapabilities'})}"
    r = _get(session, url, wfs_params["timeout_s"], wfs_params["retries"])
    meta = _save(raw_dir / "capabilities.xml", r)
    if r.status_code != 200:
        raise WFSError(f"GetCapabilities returned HTTP {r.status_code}")
    root = ET.fromstring(r.content)
    layers = {}
    for ft in root.iter(f"{{{NS['wfs']}}}FeatureType"):
        name = ft.findtext("wfs:Name", default="", namespaces=NS)
        hrefs = [el.get(f"{{{NS['xlink']}}}href") for el in ft.iter() if el.get(f"{{{NS['xlink']}}}href")]
        layers[name] = {
            "title": ft.findtext("wfs:Title", default="", namespaces=NS),
            "abstract": ft.findtext("wfs:Abstract", default="", namespaces=NS),
            "keywords": [k.text for k in ft.iterfind("ows:Keywords/ows:Keyword", NS) if k.text],
            "urls": hrefs,
        }
    return meta, layers


def fes_filter(record_filter: dict | None) -> str | None:
    """OGC Filter Encoding 2.0 for {field, equals}; sent as FILTER so the server returns only matches."""
    if not record_filter:
        return None
    return (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:PropertyIsEqualTo>'
        f"<fes:ValueReference>{escape(record_filter['field'])}</fes:ValueReference>"
        f"<fes:Literal>{escape(str(record_filter['equals']))}</fes:Literal>"
        "</fes:PropertyIsEqualTo></fes:Filter>"
    )


def count_hits(session, endpoint: str, layer: str, raw_dir: Path, wfs_params: dict) -> tuple[dict, int | None]:
    """GetFeature RESULTTYPE=hits: total records in the layer, before any record filter."""
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": layer, "RESULTTYPE": "hits"}
    r = _get(session, f"{endpoint}?{urlencode(q)}", wfs_params["timeout_s"], wfs_params["retries"])
    meta = _save(raw_dir / "hits.xml", r)
    m = re.search(rb'numberMatched="(\d+)"', r.content)
    return meta, int(m.group(1)) if m else None


def fetch_layer(session, source: dict, raw_dir: Path, wfs_params: dict) -> dict:
    """Page through GetFeature until a page returns fewer than page_size features.

    A source may set its own `page_size` (e.g. a layer the server cannot page) and a
    `record_filter`, sent to the server as an OGC filter.

    Returns {"pages": [...], "features": [...], "declared_crs": str|None, "number_matched": int|None}.
    """
    page_size = source.get("page_size") or wfs_params["page_size"]
    flt = fes_filter(source.get("record_filter"))
    features: list[dict] = []
    pages: list[dict] = []
    declared_crs = None
    number_matched = None
    start = 0
    for n in range(wfs_params["max_pages"]):
        q = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": source["layer"], "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:4326", "COUNT": page_size, "STARTINDEX": start,
        }
        if source.get("sort_by"):
            q["SORTBY"] = source["sort_by"]
        if flt:
            q["FILTER"] = flt
        r = _get(session, f"{source['endpoint_url']}?{urlencode(q)}", wfs_params["timeout_s"], wfs_params["retries"])
        meta = _save(raw_dir / f"page_{n:04d}.json", r)
        if r.status_code != 200:
            raise WFSError(f"GetFeature returned HTTP {r.status_code}: {r.text[:300]}")
        try:
            doc = json.loads(r.content)
        except json.JSONDecodeError as e:
            raise WFSError(f"GetFeature did not return JSON (page {n}): {r.text[:300]}") from e
        page_features = doc.get("features", [])
        meta["features"] = len(page_features)
        pages.append(meta)
        features.extend(page_features)
        declared_crs = declared_crs or ((doc.get("crs") or {}).get("properties") or {}).get("name")
        if number_matched is None and isinstance(doc.get("numberMatched"), int):
            number_matched = doc["numberMatched"]
        if len(page_features) < page_size:
            break
        start += page_size
    else:
        raise WFSError(f"Stopped after max_pages={wfs_params['max_pages']} without a short page")
    return {"pages": pages, "features": features, "declared_crs": declared_crs, "number_matched": number_matched}


def urls_in(value) -> list[str]:
    """All http(s) URLs inside a (nested) JSON-like value."""
    if isinstance(value, str):
        return URL_RE.findall(value)
    if isinstance(value, dict):
        return [u for v in value.values() for u in urls_in(v)]
    if isinstance(value, list):
        return [u for v in value for u in urls_in(v)]
    return []
