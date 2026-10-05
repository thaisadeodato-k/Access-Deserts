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
- **Source configuration** in `/pipeline/config/sources.yaml` (versioned, reviewable): source_id, city_code, name, publisher, layer, endpoint_url, protocol (`wfs` | `csv` | `geojson` | `overpass` | `api`), type_name/query, category, subcategory, approved (true/false). Only approved sources are used.
- **Frontend** reads only files under `public/data/`. It never calls external data sources.
- **Snapshots:** a run marked `snapshot: true` in `index.json` is served at `/snapshot/{date}` and must never change. This is the link submitted with the application. The live route `/` shows the latest run with the label "Live data – last updated {date}".
- If something from the Lovable scaffold (database tables, admin area, edge functions) becomes redundant with this architecture, list it and ask before removing.

### To retire later
Kept working for now, but new code must not depend on them. Retire only after the pipeline works end to end, and only with approval.
- Lovable Cloud tables `cities`, `sources`, `discovered_layers`, `runs`, `run_logs` and their migration `drizzle/migrations/0000_migration.sql` (replaced by `pipeline/config/*.yaml`, `run.json`, `runs/index.json`).
- `/admin` route (`src/routes/admin.tsx`) and `src/lib/admin.functions.ts` (GetCapabilities discovery: port its logic to a Python pipeline step). Removed from public navigation on 2026-10-05; the route still works by URL.
- `src/integrations/supabase/*`, `supabase/config.toml`, `drizzle.config.ts`, `drizzle/schema.ts`, and the `@supabase/supabase-js`, `drizzle-orm`, `drizzle-kit`, `postgres` dependencies.
- The Supabase query on the Map page (`src/routes/index.tsx`, source counts).
- Cloud secret `ADMIN_KEY` and the Supabase variables in `.env`.

## Output data model (per run)
- `services.geojson` — normalised points: id, source_id, name, category, subcategory, geometry_type, address.
- `hexagons.geojson` — H3 cells (resolution 8, configurable): h3_id, population_est, income_est, vulnerability_score, count_{category}_1km, nearest_{category}_m, transit_within_500m, desert_{category}, desert_count.
- `districts.json` — district summaries: population, share of population in desert hexagons per category.
- `quality.json` — per source: fetched_at, record_count, change vs previous run (added/removed), % missing coordinates, % outside city boundary, duplicates flagged, % classified by AI, fields with >20% empty values, suppressed/missing census values, unreachable or internal-only URLs found in metadata, confidence (high/medium/low) and the rule that produced it.
- `run.json` — run_id, timestamps, parameters (thresholds, H3 resolution, desert rule, vulnerability formula, polygon distance method), sources used, errors.

## Method (default parameters — configurable in `/pipeline/config/params.yaml`)
- Service access threshold: 1 km from hexagon centre (≈15 min walk).
- Transit access: any approved transit point within 500 m.
- Desert flag per category: population above city median AND zero services of that category within threshold.
- Vulnerability score: inverse percentile of average household-head income (IBGE V06004).
- Population and income per hexagon: area-weighted from census tracts.
- Polygons (parks, squares): distance to nearest edge; fallback to centroid, recorded in run.json.

## Data sources — São Paulo
Layer names verified in the public GeoSampa WFS GetCapabilities on 4 Oct 2026.

### 1. GeoSampa WFS (Prefeitura de São Paulo / SMUL-Geoinfo)
- Base URL: `http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs`
- Use ONLY the public host `wfs.geosampa.prefeitura.sp.gov.br`. Ignore any `*.prodam` hostnames found in metadata (internal network); log them as a quality issue.
- Request pattern: `SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES={layer}&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326&COUNT=1000&STARTINDEX={n}`
- Native CRS: EPSG:31983 (SIRGAS 2000 / UTM 23S). Reproject if the server ignores SRSNAME.
- Paginate until a page returns fewer than COUNT features. Save raw responses before normalising.

Layer → category:
- school: `geoportal:equipamento_educacao_rede_publica` (primary_secondary), `geoportal:equipamento_educacao_infantil_rede_publica` (early_childhood), `geoportal:equipamento_educacao_ceu` (ceu)
- health_ubs: `geoportal:equipamento_saude_ubs_posto_centro`
- cras: `geoportal:centro_referencia_assistencia_social`
- park_square: `geoportal:pde_parque_municipal` (polygons), `geoportal:GEOSAMPA_v_praca_largo` (polygons)
- library: `geoportal:equipamento_cultura_bibliotecas`
- culture: `geoportal:equipamento_cultura_espacos_culturais`, `geoportal:equipamento_cultura_museus`, `geoportal:equipamento_cultura_teatro_cinema_show`
- metro_train: `geoportal:estacao_metro` (check whether it includes CPTM train stations)
- Context (not counted): `geoportal:distrito_municipal`, `geoportal:area_contexto`, `geoportal:corredor_onibus`, `geoportal:densidade_demografica` (2022 tracts; primary demand layer if it carries population/density)

TO DISCOVER (not confirmed): bus stops, bus terminals, CPTM train stations. Search GetCapabilities Name/Title for "ponto", "parada", "onibus", "terminal", "trem", "cptm", "estacao"; list candidates (name, title, feature count) and wait for my approval.

### 2. IBGE Census 2022 (demand)
- São Paulo municipality code: 3550308. Join key: tract code (CD_SETOR).
- Tract geometry: IBGE 2022 census tract mesh.
- Population: from `geoportal:densidade_demografica` if available; otherwise IBGE "Agregados por Setores Censitários – Resultados do Universo" (2022).
- Income: `Agregados_por_setores_renda_responsavel_BR.csv`, field V06004 (average household-head income). National file: download once, filter to 3550308, keep only that subset (cache it; do not commit large raw files).
- IBGE suppresses values for tracts with fewer than 5 permanent private households: treat as MISSING (never zero), exclude from medians, report count and share in quality.json.
- Exact download URLs are NOT verified: find them on the IBGE downloads portal and show them to me before the first run.

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

## Deadline context
Portfolio item must be functional by ~31 Oct 2026. If phase 6 is not done by ~20 Oct, stop adding scope: freeze the latest working run as a snapshot and describe the remaining phases as next steps.
