"""Offline tests: no network. A fake session serves canned WFS responses."""
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from pipeline.access_deserts import config as cfg
from pipeline.access_deserts.adapters import wfs
from pipeline.access_deserts.crs import ensure_lonlat
from pipeline.access_deserts.normalise import normalise_services


def norm(features, source):
    return normalise_services(features, source)[0]
from pipeline.access_deserts.output import create_run_dir, read_index, update_index
from pipeline.access_deserts.quality import layer_check, source_quality
from pipeline.access_deserts.run import run

ENV = [-46.8346, -24.0123, -46.3636, -23.3538]
WFS_PARAMS = {"page_size": 2, "timeout_s": 5, "retries": 1, "max_pages": 10}
SOURCE = {"source_id": "s1", "name": "Test", "publisher": "P", "layer": "geoportal:test", "endpoint_url": "http://wfs.example/wfs",
          "protocol": "wfs", "role": "service", "category": "health_ubs", "subcategory": None, "approved": True, "city_code": "sp"}

CAPS = b"""<?xml version="1.0"?><wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:xlink="http://www.w3.org/1999/xlink">
<wfs:FeatureTypeList><FeatureType xmlns="http://www.opengis.net/wfs/2.0" xmlns:geoportal="http://geoportal.prodam"><Name>geoportal:test</Name><Title>T</Title>
<MetadataURL xlink:href="http://metadados.geosampa.prodam/x?uuid=1"/></FeatureType>
<FeatureType xmlns="http://www.opengis.net/wfs/2.0"><Name>geoportal:districts</Name><Title>D</Title></FeatureType>
<FeatureType xmlns="http://www.opengis.net/wfs/2.0"><Name>geoportal:municipalities</Name><Title>M</Title></FeatureType>
</wfs:FeatureTypeList></wfs:WFS_Capabilities>"""


def feat(i, coords=(-46.6, -23.5), **props):
    return {"type": "Feature", "id": f"test.{i}", "geometry": {"type": "Point", "coordinates": list(coords)} if coords else None,
            "properties": {"nm": f"Unit {i}", "addr": "Rua X", "empty": None, **props}}


class FakeResponse:
    def __init__(self, url, content, status=200):
        self.url, self.content, self.status_code = url, content, status
        self.text = content.decode("utf-8", "replace")


class FakeSession:
    """Serves GetCapabilities, hit counts and pages of `features` according to COUNT/STARTINDEX.

    `layers` maps other layer names to their features; an OGC FILTER {field = literal} is applied.
    """
    def __init__(self, features, crs="urn:ogc:def:crs:EPSG::4326", layers=None):
        self.features, self.crs, self.requests, self.layers = features, crs, [], layers or {}

    def get(self, url, timeout):
        self.requests.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if q["REQUEST"] == "GetCapabilities":
            return FakeResponse(url, CAPS)
        feats = self.layers.get(q.get("TYPENAMES"), self.features)
        if q.get("RESULTTYPE") == "hits":
            return FakeResponse(url, f'<wfs:FeatureCollection numberMatched="{len(feats)}"/>'.encode())
        if "FILTER" in q:
            field = re.search(r"<fes:ValueReference>(.*?)</", q["FILTER"]).group(1)
            value = re.search(r"<fes:Literal>(.*?)</", q["FILTER"]).group(1)
            feats = [f for f in feats if str(f["properties"].get(field)) == value]
        start, count = int(q["STARTINDEX"]), int(q["COUNT"])
        page = feats[start:start + count]
        body = {"type": "FeatureCollection", "numberMatched": len(feats), "features": page,
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
    out = norm([feat(0), feat(1, coords=None)], SOURCE)
    assert out[0]["properties"] == {"id": "s1:test.0", "source_id": "s1", "name": None, "category": "health_ubs",
                                    "subcategory": None, "geometry_type": "Point", "address": None,
                                    "equipment_type": None, "administrative_sphere": None,
                                    "included_in_metrics": True, "exclusion_reason": None, "override_reason": None}
    assert out[1]["geometry"] is None
    assert out[1]["properties"]["included_in_metrics"] is False
    assert out[1]["properties"]["exclusion_reason"] == "missing coordinates"


def test_inclusion_rules():
    src = {**SOURCE, "inclusion_rules": RULES}
    fs = [feat(0, esfera="Municipal"), feat(1, esfera="Estadual"), feat(2, esfera="Privado"),
          feat(3, tipo="SEM TIPO"), feat(4, esfera="Privado", tipo="SEM TIPO")]
    p = [f["properties"] for f in norm(fs, src)]
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
    assert f[0] == {"kind": "empty_field", "highlight": True, "field": "empty", "label": "Opening hours",
                    "pct_empty": 100.0, "text": "Opening hours (empty) is 100% empty in this run."}
    assert "not present" in f[1]["text"]


def test_normalise_with_field_map():
    src = {**SOURCE, "field_map": {"name": "nm", "address": ["addr", "missing"], "type": "tipo", "sphere": "esfera"}}
    p = norm([feat(0, tipo="UBS", esfera="Municipal")], src)[0]["properties"]
    assert p["name"] == "Unit 0" and p["address"] == "Rua X"
    assert (p["equipment_type"], p["administrative_sphere"]) == ("UBS", "Municipal")


def test_unknown_field_map_key_is_rejected(tmp_path):
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"sources": [{**SOURCE, "field_map": {"phone": "x"}}]}))
    with pytest.raises(ValueError):
        cfg.load_sources(tmp_path)


OVERRIDE = {"feature_id": "test.3", "include": True, "reason": "state health centre (verified)",
            "evidence": "CNES record", "approved_on": "2026-10-06"}


def test_record_override_includes_one_record_and_is_reported():
    src = {**SOURCE, "inclusion_rules": RULES, "field_map": {"name": "nm", "sphere": "esfera"},
           "record_overrides": [OVERRIDE, {**OVERRIDE, "feature_id": "test.99"}]}
    fs = [feat(0), feat(3, tipo="SEM TIPO", esfera="Estadual")]
    p = [f["properties"] for f in norm(fs, src)]
    assert p[1]["included_in_metrics"] is True and p[1]["exclusion_reason"] is None
    assert p[1]["override_reason"] == "state health centre (verified)" and p[0]["override_reason"] is None
    inc = source_quality(src, fs, set(), "t", [], r"\.prodam$", 0.2, None)["inclusion"]
    assert (inc["included_in_metrics"], inc["excluded_from_metrics"]) == (2, 0)
    found, missing = inc["overrides"]
    assert found["applied"] and found["rule_result"] == "excluded: missing type, needs review"
    assert not missing["found"] and not missing["applied"]


def test_override_cannot_include_a_record_without_coordinates():
    src = {**SOURCE, "record_overrides": [OVERRIDE]}
    p = norm([feat(3, coords=None)], src)[0]["properties"]
    assert p["included_in_metrics"] is False and p["exclusion_reason"] == "missing coordinates"
    assert p["override_reason"] is None


def test_incomplete_override_is_rejected(tmp_path):
    bad = {**OVERRIDE, "evidence": ""}
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"sources": [{**SOURCE, "record_overrides": [bad]}]}))
    with pytest.raises(ValueError):
        cfg.load_sources(tmp_path)


def test_rule_findings_list_records_and_include_rules_without_effect():
    src = {**SOURCE, "inclusion_rules": RULES, "field_map": {"name": "nm", "sphere": "esfera"}}
    fs = [feat(0, esfera="Municipal"), feat(1, esfera="Estadual", tipo="SEM TIPO"), feat(2, esfera="Privado", tipo="SEM TIPO")]
    f = {x["kind"] + ":" + x["rule_reason"]: x for x in source_quality(src, fs, set(), "t", [], r"\.prodam$", 0.2, None)["findings"]}
    no_type = f["rule_matches:missing type, needs review"]
    assert no_type["count"] == 2 and "Unit 1 (Estadual); Unit 2 (Privado)" in no_type["text"]
    no_effect = f["include_rule_without_effect:state-run (public service)"]
    assert no_effect["count"] == 1 and no_effect["records"][0]["feature_id"] == "test.1"


def test_layer_check_records_version_names():
    layers = {"geoportal:a": {"title": "A", "abstract": "", "keywords": ["a_v2", "features"], "urls": []},
              "geoportal:a_v3": {"title": "A3", "abstract": "", "keywords": [], "urls": []},
              "geoportal:b": {"title": "B", "abstract": "", "keywords": [], "urls": []}}
    c = layer_check("geoportal:a", "geoportal:a", layers)
    assert c["layer_in_capabilities"] and c["version_keywords"] == ["a_v2"]
    assert c["similar_layers_in_capabilities"] == ["geoportal:a_v3"]


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
    layers = {s["layer"] for s in approved}
    assert "geoportal:equipamento_saude_ubs_posto_centro" in layers and "geoportal:ponto_onibus" in layers
    assert "geoportal:centro_referencia_assistencia_social" not in layers  # coverage areas, not locations
    assert "geoportal:pde_transporte_estacao_terminal" not in layers       # rejected 2026-10-05


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
    assert r2["sources"][0]["type_name_queried"] == "geoportal:test"
    assert q2["sources"][0]["layer_check"]["layer_in_capabilities"] is True
    assert read_index(data / "runs")["latest"]["sp"] == rid2
    assert (tmp_path / "cache" / "raw" / rid1 / "s1" / "page_0000.json").exists()
    assert "services/s1.geojson" in r2["outputs"] and not (data / "runs" / rid2 / "services.geojson").exists()
    s2 = json.loads((data / "runs" / rid2 / "services" / "s1.geojson").read_text(encoding="utf-8"))
    assert len(s2["features"]) == 4


def test_previous_ids_from_a_run_with_a_single_services_file(tmp_path):
    from pipeline.access_deserts.output import previous_feature_ids, write_json
    runs = tmp_path / "runs"
    d = runs / "old"
    write_json(d / "quality.json", {"sources": [{"source_id": "s1"}]})
    write_json(d / "services.geojson", {"type": "FeatureCollection", "features": [
        {"properties": {"id": "s1:a", "source_id": "s1"}}, {"properties": {"id": "s2:b", "source_id": "s2"}}]})
    update_index(runs, {"run_id": "old", "city_code": "sp", "status": "completed"})
    assert previous_feature_ids(runs, "sp", "s1") == {"s1:a"}


# ---- inventory -----------------------------------------------------------------------------

def test_inventory_sort_field_candidates_only_confirmed_identifiers():
    from pipeline.access_deserts.inventory import sort_field_candidates
    fields = [{"name": "cd_identificador_ponto_onibus", "type": "xsd:int"}, {"name": "nm_ponto", "type": "xsd:string"},
              {"name": "cd_identificador", "type": "xsd:string"}]
    assert sort_field_candidates("geoportal:ponto_onibus", fields) == ["cd_identificador_ponto_onibus"]
    assert sort_field_candidates("geoportal:other", fields) == []


def test_inventory_field_profile():
    from pipeline.access_deserts.inventory import field_profile
    fs = [feat(0, tipo="A"), feat(1, tipo="A"), feat(2, tipo=" ")]
    p = {x["field"]: x for x in field_profile(fs, [{"name": "tipo", "type": "xsd:string"}, {"name": "g", "type": "gml:Point"}])}
    assert list(p) == ["tipo"]
    assert p["tipo"]["pct_empty"] == 33.33 and p["tipo"]["values"] == [{"value": "A", "count": 2}]


# ---- Phase 4 options -----------------------------------------------------------------------

def test_id_field_gives_stable_record_ids():
    src = {**SOURCE, "id_field": "code"}
    p = norm([{**feat(0, code=77), "id": "test.fid--abc"}], src)[0]["properties"]
    assert p["id"] == "s1:77"


def test_subcategory_rules():
    src = {**SOURCE, "subcategory": "early_childhood",
           "subcategory_rules": [{"field": "tipo", "equals": "CR.P.CONV", "subcategory": "partner_network"}]}
    p = [f["properties"]["subcategory"] for f in norm([feat(0, tipo="EMEI"), feat(1, tipo="CR.P.CONV")], src)]
    assert p == ["early_childhood", "partner_network"]


def test_venue_grouping_counts_one_record_per_venue():
    src = {**SOURCE, "inclusion_rules": RULES,
           "venue_grouping": {"fields": ["addr"], "reason": "another room of the same venue (venue counted once)"}}
    fs = [feat(0, addr="Av. X,, 10"), feat(1, addr="av x 10"), feat(2, addr="Rua Y, 5"),
          feat(3, addr="Rua Z, 1", esfera="Privado"), feat(4, addr="Rua Z 1", esfera="Privado")]
    out, summary = normalise_services(fs, src)
    p = [f["properties"] for f in out]
    assert [x["included_in_metrics"] for x in p] == [True, False, True, False, False]
    assert p[1]["exclusion_reason"].startswith("another room") and p[4]["exclusion_reason"] == "private provider"
    assert p[0]["venue_id"] == p[1]["venue_id"] != p[2]["venue_id"]
    assert (summary["records"], summary["venues"], summary["records_excluded_as_same_venue"]) == (5, 3, 1)
    inc = source_quality(src, fs, set(), "t", [], r"\.prodam$", 0.2, None, services=out, venue_grouping=summary)["inclusion"]
    assert inc["included_in_metrics"] == 2
    assert inc["excluded_by_reason"] == {"private provider": 2, "another room of the same venue (venue counted once)": 1}


def test_record_filter_and_page_size_are_sent(tmp_path):
    s = FakeSession([feat(0, kind="A"), feat(1, kind="B"), feat(2, kind="A")])
    res = wfs.fetch_layer(s, {**SOURCE, "record_filter": {"field": "kind", "equals": "A"}, "page_size": 50},
                          tmp_path, WFS_PARAMS)
    assert len(res["features"]) == 2 and res["number_matched"] == 2
    q = parse_qs(urlparse(s.requests[0]).query)
    assert q["COUNT"] == ["50"] and "<fes:Literal>A</fes:Literal>" in q["FILTER"][0]
    assert wfs.count_hits(s, SOURCE["endpoint_url"], SOURCE["layer"], tmp_path, WFS_PARAMS)[1] == 3


def test_bad_options_are_rejected(tmp_path):
    for bad in ({"page_size": 0}, {"record_filter": {"field": "x"}}, {"venue_grouping": {"fields": []}},
                {"subcategory_rules": [{"field": "x"}]}, {"role": "other"}):
        (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"sources": [{**SOURCE, **bad}]}))
        with pytest.raises(ValueError):
            cfg.load_sources(tmp_path)


def square(x0, y0, d=0.01, **props):
    ring = [[x0, y0], [x0 + d, y0], [x0 + d, y0 + d], [x0, y0 + d], [x0, y0]]
    return {"type": "Feature", "id": f"p.{x0}", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


def test_boundary_union_check_and_outside():
    from pipeline.access_deserts import boundary as bnd
    proj = bnd.Projector("EPSG:31983")
    districts = [square(-46.70, -23.60), square(-46.69, -23.60)]
    b = bnd.union_boundary(districts, proj)
    check = bnd.consistency_check(b, [square(-46.70, -23.60, d=0.02)], proj, "ref")
    assert check["reference_area_km2"] > check["boundary_area_km2"] > 0
    assert check["symmetric_difference_km2"] == pytest.approx(-check["area_difference_km2"], rel=1e-6)
    services = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.695, -23.595]},
                 "properties": {"id": "s1:a", "source_id": "s1", "name": "in"}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.60, -23.50]},
                 "properties": {"id": "s1:b", "source_id": "s1", "name": "out"}},
                {"type": "Feature", "geometry": None, "properties": {"id": "s1:c", "source_id": "s1", "name": "none"}}]
    o = bnd.outside_records(services, b, proj)["s1"]
    assert (o["with_geometry"], o["outside"], o["pct_outside"]) == (2, 1, 50.0)
    assert o["examples"] == [{"id": "s1:b", "name": "out"}]


def test_end_to_end_with_context_reference_and_boundary(tmp_path):
    conf = tmp_path / "config"
    conf.mkdir()
    (conf / "params.yaml").write_text((cfg.CONFIG_DIR / "params.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    city = yaml.safe_load((cfg.CONFIG_DIR / "cities.yaml").read_text(encoding="utf-8"))
    city["sp"]["allowed_hosts"] = ["wfs.example"]
    city["sp"]["boundary"] = {"method": "union", "source_id": "d", "check_against": "m"}
    (conf / "cities.yaml").write_text(yaml.safe_dump(city, allow_unicode=True), encoding="utf-8")
    base = {k: SOURCE[k] for k in ("name", "publisher", "endpoint_url", "protocol", "approved", "city_code")}
    sources = [SOURCE,
               {**base, "source_id": "d", "layer": "geoportal:districts", "role": "context", "field_map": {"name": "nm"}},
               {**base, "source_id": "m", "layer": "geoportal:municipalities", "role": "reference",
                "record_filter": {"field": "code", "equals": 27}}]
    (conf / "sources.yaml").write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    layers = {"geoportal:districts": [square(-46.70, -23.60, nm="A"), square(-46.69, -23.60, nm="B")],
              "geoportal:municipalities": [square(-46.70, -23.60, d=0.02, code=27), square(-46.0, -23.0, code=28)]}
    pts = [feat(0, coords=(-46.695, -23.595)), feat(1, coords=(-46.60, -23.50))]
    data = tmp_path / "data"
    rid, st = run("sp", data, tmp_path / "cache", conf, session=FakeSession(pts, layers=layers))
    assert st == "completed"
    d = data / "runs" / rid
    r = json.loads((d / "run.json").read_text(encoding="utf-8"))
    assert r["boundary"]["features_unioned"] == 2
    assert r["boundary"]["consistency_check"]["reference_features"] == 1
    assert {"boundary.geojson", "context/d.geojson"} <= set(r["outputs"])
    assert not (d / "context" / "m.geojson").exists()
    q = {s["source_id"]: s for s in json.loads((d / "quality.json").read_text(encoding="utf-8"))["sources"]}
    assert q["s1"]["pct_outside_city_boundary"] == 50.0
    assert q["m"]["record_filter"] == {"field": "code", "equals": 27, "records_in_layer": 2, "records_kept": 1}
    ctx = json.loads((d / "context" / "d.geojson").read_text(encoding="utf-8"))
    assert [f["properties"]["name"] for f in ctx["features"]] == ["A", "B"]
