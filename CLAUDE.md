# CLAUDE.md — Access Deserts

## What this project is
"Access Deserts" is a web app that automatically collects open public data, computes where high population density and social vulnerability coincide with poor access to essential public services, and shows how reliable the underlying data is. First city: São Paulo, Brazil. Adding another Brazilian city must be a configuration change, not new code.

It is a portfolio piece for a master's application (Erasmus Mundus AISS – AI for Sustainable Societies). Reviewers are academics. All UI text in English. Sober, evidence-based, no marketing language.

## Working rules (always follow)
1. **Plan before coding.** For any non-trivial task, propose a plan first and wait for my approval. Work in the phases listed below; stop after each phase and report what works, what failed and what you could not verify.
2. **Never guess data source details** (layer names, URLs, field names, codes). If something is not verified, say so and ask. Unverified sources stay disabled until I approve them.
3. **Never invent findings, numbers or quotes** in page text. Use `[TO BE COMPLETED]` placeholders for narrative content.
4. **No secrets in the repository.** Never commit API keys, tokens or passwords. Secrets live in GitHub Actions secrets or Lovable Cloud secrets only. Check `.gitignore` before committing.
5. **Git workflow.** This repo is synced two-way with Lovable. Before starting, run `git pull`. Make small, focused commits with clear messages. Do not rewrite history or force-push.
6. **Do not run `npm audit fix --force`** or upgrade major dependency versions without asking.
7. **Windows environment.** Use commands that work in Command Prompt (cmd). The project path contains spaces and accented characters; quote paths.
8. When you change architecture or parameters, update the Method page placeholders and this file.

## Architecture
The project was scaffolded in Lovable as TanStack Start (React 19 + Vite + TypeScript, SSR via Nitro with a Cloudflare build target), with Lovable Cloud (Supabase) enabled. Lovable's own plan in `.lovable/plan/` is superseded by this file. Heavy processing does NOT run in the browser or in edge functions. Current target architecture:

- **Pipeline (Python, GitHub Actions)** in `/pipeline`:
  - Runs on manual trigger (`workflow_dispatch`) and optionally on a schedule.
  - Libraries: geopandas, shapely, pyproj, h3, requests, pandas.
  - Steps: FETCH → NORMALISE → (CLASSIFY + DEDUPLICATE, later phase) → GRID → METRICS → QUALITY.
  - Writes results as static files to `public/data/runs/{run_id}/` (run_id = ISO date + short id) and updates `public/data/runs/index.json` (list of runs, latest run, snapshot flag).
  - Commits the output back to the repo with a clear message. Runs are never overwritten.
  - Raw responses are never committed: they go to gitignored `pipeline/cache/raw/{run_id}/` and to a GitHub Actions artifact `raw-{run_id}` (90-day retention); `run.json` lists every page's URL, HTTP status, size and sha256. When a run is marked as a snapshot, its raw files are attached to a GitHub Release so they never expire (implemented in the snapshot phase).
  - Only libraries actually used are in `pipeline/requirements.txt` (pinned); geopandas/shapely/pandas/h3 are added in the phase that first needs them.
  - Run locally (Windows): `py -3.13 -m venv .venv-pipeline`, `.venv-pipeline\Scripts\pip install -r pipeline\requirements.txt`, `.venv-pipeline\Scripts\python -m pipeline.access_deserts.run --city sp` (use `--data-dir`/`--cache-dir` to write outside the repo for test runs).
- **Source configuration** in `/pipeline/config/sources.yaml` (versioned, reviewable): source_id, city_code, name, publisher, layer, endpoint_url, protocol (`wfs` | `csv` | `geojson` | `overpass` | `api`), type_name/query, category, subcategory, role, approved (true/false). Only approved sources are used. Roles: `service` (services.geojson), `context` (published under `context/{source_id}.geojson`, display only), `reference` (fetched for checks only), `demand` (Phase 5). Optional per-source keys (approved 2026-10-05): `sort_by`, `page_size`, `id_field`, `record_filter` ({field, equals}, sent as an OGC FES filter), `field_map` (name, address, type, sphere), `inclusion_rules`, `subcategory_rules`, `venue_grouping`, `record_overrides`, `highlight_fields`, `map_initially_hidden`, `placeholder_values`, `derived_name`; documented at the top of the file. Candidate layers (inventoried, never used) live in `pipeline/config/candidates.yaml` with status pending/approved/rejected.
- **Findings log:** `pipeline/findings.md` — running log of data-quality findings (date, source, finding, evidence, impact, handling). Feeds the Reliability page and Limitations. Add an entry whenever a new data-quality issue is found.
- **Frontend** reads only files under `public/data/`. It never calls external data sources (the CARTO basemap tiles are the only external request). Run files are read by `src/lib/runs.ts`; the map is `src/components/ServiceMap.tsx` (MapLibre, browser only) inside `src/components/RunView.tsx`, shared by `/` and `/snapshot/$date`. maplibre-gl 6 needs its worker passed explicitly (`?worker&url` import + `setWorkerUrl`), otherwise it fails under Vite.
- **Snapshots:** a run marked `snapshot: true` in `index.json` is served at `/snapshot/{date}` and must never change. `{date}` is the date prefix of the run_id; at most one snapshot per date (two are shown as a data error, never guessed). The snapshot's data files are fixed, but its appearance follows the current frontend code (no frozen build yet). This is the link submitted with the application. The live route `/` shows the latest run with the label "Live data – last updated {date}".
- If something from the Lovable scaffold (database tables, admin area, edge functions) becomes redundant with this architecture, list it and ask before removing.

### To retire later
Kept working for now, but new code must not depend on them. Retire only after the pipeline works end to end, and only with approval.
- Lovable Cloud tables `cities`, `sources`, `discovered_layers`, `runs`, `run_logs` and their migration `drizzle/migrations/0000_migration.sql` (replaced by `pipeline/config/*.yaml`, `run.json`, `runs/index.json`).
- `/admin` route (`src/routes/admin.tsx`) and `src/lib/admin.functions.ts` (GetCapabilities discovery: port its logic to a Python pipeline step). Removed from public navigation on 2026-10-05; the route still works by URL.
- `src/integrations/supabase/*`, `supabase/config.toml`, `drizzle.config.ts`, `drizzle/schema.ts`, and the `@supabase/supabase-js`, `drizzle-orm`, `drizzle-kit`, `postgres` dependencies.
- Cloud secret `ADMIN_KEY` and the Supabase variables in `.env`.

## Output data model (per run)
- `services/{source_id}.geojson` — one file per service source (since 5 Oct 2026; earlier runs have a single `services.geojson`, still readable by the pipeline and the frontend). Normalised service records (points; parks and squares as polygons): id, source_id, name, name_derived, category, subcategory, geometry_type, address, equipment_type, administrative_sphere, included_in_metrics, exclusion_reason, override_reason, outside_boundary (+ venue_id where venue grouping applies). Every source record is present (except records outside a source's `record_filter`); records without coordinates have `geometry: null`. GeoJSON outputs are written compact (no indentation); ~21 MB of service files per run in Phase 4, mostly bus stops (10 MB) and squares (6.5 MB). Sources with `map_initially_hidden: true` (bus stops, squares) start hidden on the map and their file is downloaded only when the layer is switched on; the rest (~5 MB) loads with the page.
- `boundary.geojson` — city boundary (union of the 96 districts). `context/{source_id}.geojson` — context layers for display (districts, bus corridors in operation): id, source_id, name, type.
- `hexagons.geojson` — H3 cells (resolution 8, configurable) intersecting the city boundary. Phase 5: h3_id, area_km2, area_in_city_km2, population_est, households_est, heads_est, pop_density_km2, income_est, income_coverage, vulnerability_score, comparison_mean / comparison_vulnerable_share / comparison_coverage (IPVS 2022, comparison only). Phase 6 adds count_{category}_1km, nearest_{category}_m, transit_within_500m, desert_{category}, desert_count. ~1.6 MB.
- quality.json `demand` and run.json `demand`: tract join and population check, income status counts (ok / suppressed / not_available / absent), hexagon counts, coverage-threshold sensitivity, IPVS comparison (Spearman rho, largest disagreements by district).
- `districts.json` — district summaries: population, share of population in desert hexagons per category.
- `quality.json` — per source: fetched_at, record_count, change vs previous run (added/removed), % missing coordinates, % outside city boundary, duplicates flagged, % classified by AI, fields with >20% empty values, layer check (configured vs queried TYPENAMES, presence in GetCapabilities, `_vN` keywords and similarly named layers), findings (highlighted empty fields; records matched by exclusion rules; include rules without effect), inclusion rule counts and record overrides, suppressed/missing census values, unreachable or internal-only URLs found in metadata, confidence (high/medium/low) and the rule that produced it.
- `run.json` — run_id, timestamps, parameters (thresholds, H3 resolution, desert rule, vulnerability formula, polygon distance method), sources used (incl. `type_name_queried`, `layer_check`, `record_overrides`), errors.

## Method (default parameters — configurable in `/pipeline/config/params.yaml`)
- Service access threshold: 1 km from hexagon centre (≈15 min walk).
- Transit access: any approved transit point within 500 m.
- Desert flag per category: population above city median AND zero services of that category within threshold.
- Vulnerability score: 1 − percentile rank of hexagon income_est among populated hexagons with income (ties averaged); 1 = lowest income. IPVS 2022 (SEADE) is a comparison layer only (Method page explains why: Census covers all municipalities; IPVS only SP state, 1,426 city tracts unclassified).
- Population and income per hexagon: area-weighted from census tracts (uniform population within a tract; dasymetric interpolation is future work). Population = IBGE v0001 (GeoSampa `qt_populacao` checked equal every run); households = v0007; income = V06004 weighted by V06001 (all heads) × area share, only tracts with usable income. V06004 excludes heads without income and cannot be corrected (no tract count of heads with income): limitation on the Method page, findings.md #18. V06006 (median) is not aggregated.
- Income coverage: share of a hexagon's population in tracts with usable income; below `demand.income_coverage_threshold` (0.5) no income estimate. Sensitivity reported for 0.3 / 0.5 / 0.7 (5 Oct 2026: 67 / 69 / 76 of 2,108 populated hexagons without income; 0.011% / 0.011% / 0.068% of the population).
- Hexagons: `h3shape_to_cells` (stable h3 API, h3==4.5.0, centre containment) on the boundary buffered by 1 km, kept if the cell intersects the boundary (5 Oct 2026: 2,278 cells, 2,108 populated, 2,039 with income).
- Polygons (parks, squares): distance to nearest edge; fallback to centroid, recorded in run.json.
- City boundary: union of the 96 `distrito_municipal` polygons (in EPSG:31983). Every run checks it against `area_contexto` feature 27 (fetched alone with a filter) and records areas and symmetric difference in run.json (`boundary.consistency_check`); 5 Oct 2026: both 1,522.532 km², symmetric difference 0. "% outside boundary" = share of records whose geometry does not intersect the boundary. Records outside the boundary stay in the metrics (author decision 5 Oct 2026: excluding them would create artificial deserts at the city edge); each is flagged `outside_boundary: true`, counts per source in quality.json (`outside_city_boundary`). 5 Oct 2026: 188 records outside (52 of 109 train stations, 15 of 50 bus terminals, 120 bus stops, 1 park). Edge effect is a limitation on the Method page.
- Derived names: CRAS have no unit-name field; a CRAS takes the `nm_cras` of the coverage area that contains it, only for one-to-one matches (`derived_name` in sources.yaml, `name_derived: true`, summary in quality.json `name_derivation`). 5 Oct 2026: 50 of 54 named; 4 null (two areas hold two points each).
- Placeholder values: "No" replaced by null in 5 CRAS fields (`placeholder_values`); only for fields where the value is clearly a placeholder, never in yes/no fields.
- Metrics rule (author, 5 Oct 2026): only services that are public, free at the point of use and currently existing are counted.
- Record inclusion: no record is ever dropped. Each service record carries `included_in_metrics` and `exclusion_reason`; rules live per source in `sources.yaml` (`inclusion_rules`), match counts go to quality.json. Built-in rule: no coordinates → excluded ("missing coordinates"). UBS layer (approved 5 Oct 2026): state-run → included (public service); private → excluded ("private provider"); Type "SEM TIPO" → excluded ("missing type, needs review"). Exclusion takes precedence over inclusion: the 2 state-run records are both "SEM TIPO" and stay excluded (reported as "include_rule_without_effect"). Other layers (approved 5 Oct 2026): early childhood "CR.P.CONV" included as subcategory `partner_network`; libraries, cultural spaces, museums, theatres/cinemas "Particular" → excluded ("private provider"); theatres/cinemas grouped into venues by normalised address, one record counted per venue (410 rooms = 107 venues); parks "Proposto" → excluded ("planned, not built"); bus terminals "RODOVIARIO" → excluded ("intercity terminal, not daily access"); bus corridors: only "Em Operação" (record_filter). Listed on the Method page.
- Record overrides: `record_overrides` in `sources.yaml` ({feature_id, include, reason, evidence, approved_on}) replace the rule result for one record; only added after the author approves them with cited evidence; reported in quality.json and on the Method page; cannot include a record without coordinates. None. Author decision 5 Oct 2026: the two state-run "SEM TIPO" centres (CS Escola Geraldo de Paula Souza, CS Escola Samuel Barnsley Pessoa) stay excluded and are a known limitation (findings.md #8). The source marks Samuel Barnsley Pessoa as "Estadual" (Secretaria de Estado da Saúde), not private; the source does not mention USP.
- Highlighted findings: `highlight_fields` in `sources.yaml` produce computed findings in quality.json (`findings`), cited on the Reliability page and in Limitations. UBS: opening hours (`tx_horario_funcionamento`).

## Data sources — São Paulo
Layer names verified in the public GeoSampa WFS GetCapabilities on 4 Oct 2026; all 16 re-verified on 5 Oct 2026 (feature counts recorded in `pipeline/config/sources.yaml`).

### 1. GeoSampa WFS (Prefeitura de São Paulo / SMUL-Geoinfo)
- Base URL: `http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs`
- Use ONLY the public host `wfs.geosampa.prefeitura.sp.gov.br`. Ignore any `*.prodam` hostnames found in metadata (internal network); log them as a quality issue.
- Request pattern: `SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES={layer}&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326&COUNT=1000&STARTINDEX={n}`
- Native CRS: EPSG:31983 (SIRGAS 2000 / UTM 23S). Reproject if the server ignores SRSNAME.
- Paginate until a page returns fewer than COUNT features. Save raw responses before normalising.
- Layers without a primary key reject STARTINDEX ("Cannot do natural order without a primary key") unless `SORTBY` is given: set `sort_by` in sources.yaml to a field confirmed by DescribeFeatureType (e.g. `area_contexto` → `cd_identificador_area_contexto`).
- `*.prodam` occurrences: `http://geoportal.prodam` is only the XML namespace URI (not a host); `metadados.geosampa.prodam` appears in a MetadataURL (internal host, flagged). Internal hosts are matched with `\.prodam$`.
- Observed 5 Oct 2026 on the UBS layer: SRSNAME=EPSG:4326 honoured, lon/lat axis order, all 483 features in one page. The pipeline still checks CRS/axis order on every run. GetCapabilities lists keyword `equipamento_saude_ubs_posto_centro_v2` for this layer (likely the underlying table); no layer with that name is published. 71 layers carry `_vN` keywords; only `geoportal:torre_alta_tensao` has a MetadataURL (the internal `metadados.geosampa.prodam` host).

Layer → category:
- school: `geoportal:equipamento_educacao_rede_publica` (primary_secondary), `geoportal:equipamento_educacao_infantil_rede_publica` (early_childhood), `geoportal:equipamento_educacao_ceu` (ceu)
- health_ubs: `geoportal:equipamento_saude_ubs_posto_centro`
- cras: `geoportal:equipamento_assistencia_social` filtered to class "CENTRO DE REFERÊNCIA DE ASSISTÊNCIA SOCIAL - CRAS" (54 of 1,336). `geoportal:centro_referencia_assistencia_social` holds coverage areas, not locations (kept as non-approved context `sp_geosampa_cras_coverage`). The layer has no unit-name field.
- park_square: `geoportal:pde_parque_municipal` (polygons), `geoportal:GEOSAMPA_v_praca_largo` (polygons)
- library: `geoportal:equipamento_cultura_bibliotecas`
- culture: `geoportal:equipamento_cultura_espacos_culturais`, `geoportal:equipamento_cultura_museus`, `geoportal:equipamento_cultura_teatro_cinema_show`
- metro_train: `geoportal:estacao_metro` (metro only, 94) and `geoportal:estacao_trem` (CPTM + ViaMobilidade, 109; subcategory `train`)
- transit: `geoportal:ponto_onibus` (bus_stop, 22,570) and `geoportal:terminal_onibus` (bus_terminal, 50). Approved 5 Oct 2026. Which categories count as "transit" for transit_within_500m is decided in Phase 6.
- Context (not counted): `geoportal:distrito_municipal` (context; its union is the city boundary), `geoportal:area_contexto` (reference: only feature 27), `geoportal:corredor_onibus` (context, only "Em Operação"), `geoportal:densidade_demografica` (demand, Phase 5; 2022 tracts; primary demand layer if it carries population/density)
- `geoportal:area_contexto` is NOT the city boundary: 1,359 features = municipalities of São Paulo state (type M) + "OCEANO ATLÂNTICO" (O) + "RMSP" (R). São Paulo appears twice: id 27 "São Paulo" (1,522.5 km², identical area and bbox to the union of the 96 `distrito_municipal` polygons) and id 10027 "SÃO PAULO" (1,527.5 km², different version). The full layer is 86 MB; the pipeline fetches only feature 27 (OGC filter on `cd_identificador_area_contexto`).

Transit candidates (discovery 5 Oct 2026). Decided 5 Oct 2026: `ponto_onibus`, `terminal_onibus` (without RODOVIARIO) and `estacao_trem` approved; `pde_transporte_estacao_terminal` rejected (628 of 900 planned, 518 without geometry). 50 layers matched the search terms; most are `sac_*` complaint layers or unrelated (spot heights, lighting). Plausible:
- `geoportal:ponto_onibus` — Pontos de Ônibus — 22,570 features
- `geoportal:terminal_onibus` — Terminal de Ônibus — 50
- `geoportal:estacao_trem` — Trem Metropolitano – Estação — 109
- `geoportal:pde_transporte_estacao_terminal` — Transporte público coletivo – Estações e Terminais (PDE Mapa 9) — 900
- Lines/lanes (context only): `geoportal:linha_onibus` (2,322), `geoportal:linha_trem` (26), `geoportal:faixa_onibus` (7,378)

Layer inventory 5 Oct 2026 (`python -m pipeline.access_deserts.inventory`; report in `pipeline/discovery/inventory-2026-10-05.md`). All counts match `features_at_verification`. Decisions on 5 Oct 2026 are applied in `sources.yaml`; findings are logged in `pipeline/findings.md`. Findings that affected approval:
- Paging: `equipamento_educacao_infantil_rede_publica` and `ponto_onibus` need SORTBY (`cd_identificador`, `cd_identificador_ponto_onibus`; both unique). `GEOSAMPA_v_praca_largo` returns empty pages for any STARTINDEX > 0, even with SORTBY, but one request with COUNT ≥ 3,831 returns all 3,830 (7.3 MB).
- Generated (unstable) feature ids (`*.fid--…`): `equipamento_educacao_infantil_rede_publica`, `area_contexto`, `ponto_onibus`. Record ids must come from an attribute for these.
- Education layers: `nm_esfera_administrativa_equipamento` contradicts the type (EE state schools = "MUNICIPAL"; EMEF, EMEI, CEI DIRET and all 150 CEU units = "PRIVADA"). Not usable for inclusion rules.
- `centro_referencia_assistencia_social` = 58 polygons of CRAS coverage areas (`qt_area_abrangencia_centro`), not facility points. CRAS points: `geoportal:equipamento_assistencia_social`, class "CENTRO DE REFERÊNCIA DE ASSISTÊNCIA SOCIAL - CRAS" (54 points, all "DIRETA"; `nm_equipamento` holds the operator "PREFEITURA MUNICIPAL DE SAO PAULO", not the unit name). Candidate in `pipeline/config/candidates.yaml`.
- `pde_parque_municipal`: 164 of 280 parks are "Proposto" (planned), 116 "Existente".
- `equipamento_cultura_teatro_cinema_show`: one record per cinema/theatre room (387 cinema rooms), 364 "Particular".
- `estacao_metro`: metro only (6 lines incl. ViaQuatro and monorail line 15); interchange stations appear once per line. CPTM is `estacao_trem` (109).
- `pde_transporte_estacao_terminal`: 628 of 900 "Planejado"; 518 without geometry.
- `area_contexto` as served is 86 MB (whole state); fetch only the São Paulo feature for the boundary check.

### 2. IBGE Census 2022 (demand)
URLs verified (HTTP 200) and approved for download on 5 Oct 2026. Base: `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/`. File names carry date suffixes; check the directory listing if a download returns 404.
- Income: `Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip` (9.4 MB; contains `Agregados_por_setores_renda_responsavel_BR.csv`, UTF-8, `;`, decimal point). Dictionary: `…/dicionario_de_dados_renda_responsavel_20260508.xlsx`.
- Basic aggregates (population, households): `Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip` (15.4 MB; `Agregados_por_setores_basico_BR.csv`, Latin-1, `;`, decimal comma; columns lower case `v0001`…). Dictionary: `Agregados_por_Setores_Censitarios/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx`.
- Tract mesh (not needed, see below): `Agregados_por_Setores_Censitarios/malha_com_atributos/setores/gpkg/UF/SP/SP_setores_CD2022.gpkg` (182 MB).
- Variables (confirmed in the dictionaries): V06004 = average nominal monthly income of household heads WITH income, occupied permanent private dwellings (V06006 = median; V06001 = household heads). v0001 = total persons; v0007 = occupied private households (DPPO + DPIO); v0002 = all dwellings incl. vacant and collective.
- São Paulo municipality code: 3550308; join key: tract code CD_SETOR (15 digits; the income file has no municipality column, filter by prefix). 27,301 tracts in the basic file; 26,889 in the income file (the 412 absent tracts have 0 persons and 0 households).
- Suppression (5.1 verification, 5 Oct 2026): V06004 is "X" in 212 tracts (10,979 persons) and "." in 5 tracts (946 persons); the downloaded dictionaries do not explain either code. Most "X" tracts have 1–4 occupied households, but 10 have 10 or more (up to 322), so the rule is not only "fewer than 5 households". Both are treated as MISSING (never zero), excluded from medians, count and share reported in quality.json.
- Population and geometry: `geoportal:densidade_demografica` (GeoSampa, 2022 tracts, 27,301 features, 47.7 MB, stable ids, needs SORTBY) matches IBGE exactly: same 27,301 tract codes, `qt_populacao` = v0001 in every tract (total 11,451,999), identical areas. Its `qt_domicilio` equals v0002 (all dwellings), NOT occupied households: use IBGE v0007 / V06001 for household weights.
- `cd_indice_vulnerabilidade_social` in the GeoSampa layer = IPVS 2022 (Índice Paulista de Vulnerabilidade Social, Fundação SEADE, based on the 2022 Census; GeoSampa layer `geoportal:indice_paulista_vulnerabilidadesocial`, same codes). Codes 1–6: group 1 "baixíssima vulnerabilidade" … group 6 "vulnerabilidade muito alta" (groups 4–6 "vulneráveis"); 1,426 tracts unclassified (null). Label field empty in GeoSampa; names of groups 2–5 not verified. Comparison only, never replaces the approved vulnerability formula.

### 3. National adapters (last phase only, after approval)
- OpenStreetMap via Overpass (`https://overpass-api.de/api/interpreter`): amenity=school, amenity=library, leisure=park, highway=bus_stop, public_transport=station, railway=station. No reliable OSM tag for CRAS: mark "not available from OSM".
- CNES (health) and INEP school catalogue: verify endpoints and coordinate fields first.

## Frontend pages
- **Map (main):** MapLibre GL + free CARTO Positron tiles (no API key). Hexagon choropleth (desert_count, desert by category/subcategory, population density, vulnerability); toggleable service layers; transit points; reliability badge per layer linking to its quality card; hexagon popup (population, vulnerability, services within threshold, nearest distances, missing services); district summary panel.
- **Reliability:** one card per source per run from quality.json, confidence rules in plain English, AI decisions table (later phase).
- **Method:** auto-filled from run.json + `[TO BE COMPLETED]` sections (research question, limitations: proximity ≠ capacity/opening hours/quality; census suppression; 2022 population vs current facilities; tools: "Code written with Lovable and Claude Code; method, data model and quality rules designed by the author").
- **Community Validation:** placeholders for 5–8 conversation summaries (role, area, what the map confirmed, what it missed).
- **Proposals:** placeholders for 3 proposals (problem shown by data, spatial proposal, sketch image slot, evidence and open questions).
- Design: map-first, editorial, neutral greys + one accent for deserts, colour-blind-safe, responsive, keyboard accessible. Footer with data credits and run date.

## Phases
1. **Review the scaffold:** read the repo, summarise what Lovable built (pages, Cloud tables, edge functions, admin) and how it maps to this architecture. No code changes.
2. **Pipeline skeleton:** `/pipeline` structure, config files, GitHub Actions workflow (manual trigger), FETCH + NORMALISE for ONE layer (`geoportal:equipamento_saude_ubs_posto_centro`), output `services.geojson` + `quality.json` + `run.json`. Report feature count so I can compare with the GeoSampa portal.
3. **Frontend reads run files:** map shows UBS points from the latest run; runs index; snapshot route.
4. **All GeoSampa layers** + district and municipal boundaries; discovery list for transit candidates.
5. **Demand:** IBGE tracts, population, income (with suppression handling), H3 grid, area-weighted estimates.
6. **Metrics:** access counts, nearest distances, desert flags, district summaries, full map interactions.
7. **Reliability page + confidence rules**; AI classification/deduplication with logged decisions (API key only in GitHub secrets).
8. **Method, Community Validation, Proposals pages**; PNG export of the current map view.
9. **National adapters** (OSM first) and a second test city — only after approval.

## Open items
- Repo size (before the snapshot phase): each official run adds ~26 MB to git history. Propose a retention policy (e.g. commit only official runs, keep the latest N in `public/data`, archive older run folders as GitHub Release assets). No action until then.

## Deadline context
Portfolio item must be functional by ~31 Oct 2026. If phase 6 is not done by ~20 Oct, stop adding scope: freeze the latest working run as a snapshot and describe the remaining phases as next steps.
