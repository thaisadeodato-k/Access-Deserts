"""Offline tests: no network. A fake session serves canned WFS responses."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from pipeline.access_deserts import config as cfg
from pipeline.access_deserts.adapters import wfs
from pipeline.access_deserts.crs import ensure_lonlat
from pipeline.access_deserts.normalise import normalise_services
from pipeline.access_deserts.output import create_run_dir, read_index, update_index
from pipeline.access_deserts.quality import source_quality
from pipeline.access_deserts.run import run

ENV = [-46.8346, -24.0123, -46.3636, -23.3538]
WFS_PARAMS = {"page_size": 2, "timeout_s": 5, "retries": 1, "max_pages": 10}
SOURCE = {"source_id": "s1", "name": "Test", "publisher": "P", "layer": "geoportal:test", "endpoint_url": "http://wfs.example/wfs",
          "protocol": "wfs", "role": "service", "category": "health_ubs", "subcategory": None, "approved": True, "city_code": "sp"}

CAPS = b"""<?xml version="1.0"?><wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:xlink="http://www.w3.org/1999/xlink">
<wfs:FeatureTypeList><FeatureType xmlns="http://www.opengis.net/wfs/2.0" xmlns:geoportal="http://geoportal.prodam"><Name>geoportal:test</Name><Title>T</Title>
<MetadataURL xlink:href="http://metadados.geosampa.prodam/x?uuid=1"/></FeatureType></wfs:FeatureTypeList></wfs:WFS_Capabilities>"""


def feat(i, coords=(-46.6, -23.5), **props):
    return {"type": "Feature", "id": f"test.{i}", "geometry": {"type": "Point", "coordinates": list(coords)} if coords else None,
            "properties": {"nm": f"Unit {i}", "addr": "Rua X", "empty": None, **props}}


class FakeResponse:
    def __init__(self, url, content, status=200):
        self.url, self.content, self.status_code = url, content, status
        self.text = content.decode("utf-8", "replace")


class FakeSession:
    """Serves GetCapabilities and pages of `features` according to COUNT/STARTINDEX."""
    def __init__(self, features, crs="urn:ogc:def:crs:EPSG::4326"):
        self.features, self.crs, self.requests = features, crs, []

    def get(self, url, timeout):
        self.requests.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if q["REQUEST"] == "GetCapabilities":
            return FakeResponse(url, CAPS)
        start, count = int(q["STARTINDEX"]), int(q["COUNT"])
        page = self.features[start:start + count]
        body = {"type": "FeatureCollection", "numberMatched": len(self.features), "features": page,
                "crs": {"type": "name", "properties": {"name": self.crs}}}
        return FakeResponse(url, json.dumps(body).encode())


# ---- adapter -------------------------------------------------------------------------------

def test_paging_stops_on_short_page_and_saves_raw(tmp_path):
    s = FakeSession([feat(i) for i in range(5)])
    res = wfs.fetch_layer(s, SOURCE, tmp_path, WFS_PARAMS)
    assert len(res["features"]) == 5
    assert [p["features"] for p in res["pages"]] == [2, 2, 1]
    assert res["number_matched"] == 5
    assert all((tmp_path / p["raw_file"]).exists() and len(p["sha256"]) == 64 for p in res["pages"])


def test_paging_with_exact_multiple_requests_one_empty_page(tmp_path):
    s = FakeSession([feat(i) for i in range(4)])
    res = wfs.fetch_layer(s, SOURCE, tmp_path, WFS_PARAMS)
    assert [p["features"] for p in res["pages"]] == [2, 2, 0]


def test_sort_by_is_sent_only_when_configured(tmp_path):
    s = FakeSession([feat(0)])
    wfs.fetch_layer(s, SOURCE, tmp_path, WFS_PARAMS)
    assert "SORTBY" not in s.requests[0]
    wfs.fetch_layer(s, {**SOURCE, "sort_by": "cd_id"}, tmp_path / "b", WFS_PARAMS)
    assert "SORTBY=cd_id" in s.requests[1]


def test_capabilities_lists_layers_and_metadata_urls(tmp_path):
    meta, layers = wfs.get_capabilities(FakeSession([]), "http://wfs.example/wfs", tmp_path, WFS_PARAMS)
    assert layers["geoportal:test"]["urls"] == ["http://metadados.geosampa.prodam/x?uuid=1"]
    assert (tmp_path / "capabilities.xml").exists()


# ---- CRS -----------------------------------------------------------------------------------

def test_crs_lonlat_untouched():
    fs = [feat(0, (-46.6, -23.5))]
    out, rec = ensure_lonlat(fs, ENV, "EPSG:31983", "EPSG:4326")
    assert out[0]["geometry"]["coordinates"] == [-46.6, -23.5] and rec["action"].startswith("none")


def test_crs_swapped_axis_is_fixed():
    out, rec = ensure_lonlat([feat(0, (-23.5, -46.6))], ENV, "EPSG:31983", None)
    assert out[0]["geometry"]["coordinates"] == [-46.6, -23.5] and "swapped" in rec["action"]


def test_crs_utm_is_reprojected():
    out, rec = ensure_lonlat([feat(0, (333000.0, 7395000.0))], ENV, "EPSG:31983", None)
    lon, lat = out[0]["geometry"]["coordinates"]
    assert -46.84 < lon < -46.36 and -24.02 < lat < -23.35 and "reprojected" in rec["action"]


def test_crs_unknown_raises():
    with pytest.raises(ValueError):
        ensure_lonlat([feat(0, (2.35, 48.85))], ENV, "EPSG:31983", None)


# ---- normalise and quality -----------------------------------------------------------------

RULES = [
    {"field": "esfera", "equals": "Estadual", "include": True, "reason": "state-run (public service)"},
    {"field": "esfera", "equals": "Privado", "include": False, "reason": "private provider"},
    {"field": "tipo", "equals": "SEM TIPO", "include": False, "reason": "missing type, needs review"},
]


def test_normalise_without_field_map_keeps_every_record():
    out = normalise_services([feat(0), feat(1, coords=None)], SOURCE)
    assert out[0]["properties"] == {"id": "s1:test.0", "source_id": "s1", "name": None, "category": "health_ubs",
                                    "subcategory": None, "geometry_type": "Point", "address": None,
                                    "included_in_metrics": True, "exclusion_reason": None}
    assert out[1]["geometry"] is None
    assert out[1]["properties"]["included_in_metrics"] is False
    assert out[1]["properties"]["exclusion_reason"] == "missing coordinates"


def test_inclusion_rules():
    src = {**SOURCE, "inclusion_rules": RULES}
    fs = [feat(0, esfera="Municipal"), feat(1, esfera="Estadual"), feat(2, esfera="Privado"),
          feat(3, tipo="SEM TIPO"), feat(4, esfera="Privado", tipo="SEM TIPO")]
    p = [f["properties"] for f in normalise_services(fs, src)]
    assert [x["included_in_metrics"] for x in p] == [True, True, False, False, False]
    assert p[2]["exclusion_reason"] == "private provider"
    assert p[4]["exclusion_reason"] == "private provider; missing type, needs review"
    q = source_quality(src, fs, set(), "t", [], r"\.prodam$", 0.2, None)["inclusion"]
    assert (q["included_in_metrics"], q["excluded_from_metrics"]) == (2, 3)
    assert [r["matched"] for r in q["rules"]] == [1, 2, 2, 0]


def test_bad_inclusion_rule_is_rejected(tmp_path):
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"sources": [{**SOURCE, "inclusion_rules": [{"field": "x", "equals": 1}]}]}))
    with pytest.raises(ValueError):
        cfg.load_sources(tmp_path)


def test_highlighted_finding():
    src = {**SOURCE, "highlight_fields": {"empty": "Opening hours", "absent": "Absent"}}
    f = source_quality(src, [feat(0), feat(1)], set(), "t", [], r"\.prodam$", 0.2, None)["findings"]
    assert f[0] == {"highlight": True, "field": "empty", "label": "Opening hours", "pct_empty": 100.0,
                    "text": "Opening hours (empty) is 100% empty in this run."}
    assert "not present" in f[1]["text"]


def test_normalise_with_field_map():
    src = {**SOURCE, "field_map": {"name": "nm", "address": ["addr", "missing"]}}
    p = normalise_services([feat(0)], src)[0]["properties"]
    assert p["name"] == "Unit 0" and p["address"] == "Rua X"


def test_quality_metrics():
    fs = [feat(0), feat(1, coords=None), feat(2, url="see http://x.prodam/a"), feat(3)]
    q = source_quality(SOURCE, fs, {"s1:test.0", "s1:test.2", "s1:test.3"}, "t", ["http://metadados.geosampa.prodam/x"],
                       r"\.prodam$", 0.20, previous_ids={"s1:test.0", "s1:old"})
    assert q["record_count"] == 4
    assert q["pct_missing_coordinates"] == 25.0
    assert q["fields_over_empty_threshold"] == {"empty": 100.0, "url": 75.0}
    assert q["internal_hosts_in_metadata"] == ["metadados.geosampa.prodam"]
    assert q["internal_hosts_in_data"] == ["x.prodam"]
    assert q["change_vs_previous"] == {"added": 2, "removed": 1, "note": None}
    assert q["pct_outside_city_boundary"] is None


# ---- output --------------------------------------------------------------------------------

def test_run_dir_is_never_overwritten(tmp_path):
    create_run_dir(tmp_path, "r1")
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "r1")


def test_index_latest_only_for_completed(tmp_path):
    update_index(tmp_path, {"run_id": "a", "city_code": "sp", "status": "completed"})
    update_index(tmp_path, {"run_id": "b", "city_code": "sp", "status": "failed"})
    idx = read_index(tmp_path)
    assert idx["latest"] == {"sp": "a"} and [r["run_id"] for r in idx["runs"]] == ["b", "a"]
    assert all(r["snapshot"] is False for r in idx["runs"])


# ---- config and end-to-end -----------------------------------------------------------------

def test_repo_config_is_valid():
    city = cfg.load_city("sp")
    approved = cfg.approved_sources(city, cfg.load_sources())
    assert [s["layer"] for s in approved] == ["geoportal:equipamento_saude_ubs_posto_centro"]


def test_disallowed_host_is_refused():
    city = {"city_code": "sp", "allowed_hosts": ["wfs.geosampa.prefeitura.sp.gov.br"]}
    with pytest.raises(ValueError):
        cfg.approved_sources(city, [{**SOURCE, "endpoint_url": "http://geoportal.prodam/wfs"}])


def test_end_to_end_two_runs(tmp_path):
    conf = tmp_path / "config"
    conf.mkdir()
    for name in ("params.yaml", "cities.yaml"):
        (conf / name).write_text((cfg.CONFIG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    city = yaml.safe_load((conf / "cities.yaml").read_text(encoding="utf-8"))
    city["sp"]["allowed_hosts"] = ["wfs.example"]
    (conf / "cities.yaml").write_text(yaml.safe_dump(city, allow_unicode=True), encoding="utf-8")
    (conf / "sources.yaml").write_text(yaml.safe_dump({"sources": [SOURCE]}), encoding="utf-8")

    data = tmp_path / "data"
    rid1, st1 = run("sp", data, tmp_path / "cache", conf, session=FakeSession([feat(i) for i in range(3)]))
    rid2, st2 = run("sp", data, tmp_path / "cache", conf, session=FakeSession([feat(i) for i in range(1, 5)]))
    assert st1 == st2 == "completed"
    q2 = json.loads((data / "runs" / rid2 / "quality.json").read_text(encoding="utf-8"))
    assert q2["sources"][0]["change_vs_previous"] == {"added": 2, "removed": 1, "note": None}
    r2 = json.loads((data / "runs" / rid2 / "run.json").read_text(encoding="utf-8"))
    assert r2["sources"][0]["count_check"] == "ok" and r2["raw_storage"]["committed"] is False
    assert read_index(data / "runs")["latest"]["sp"] == rid2
    assert (tmp_path / "cache" / "raw" / rid1 / "s1" / "page_0000.json").exists()
