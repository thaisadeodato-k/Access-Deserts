> **SUPERSEDED (2026-10-05)** by `CLAUDE.md` in the repository root. Kept for history only. The pipeline now runs in Python on GitHub Actions and writes static files to `public/data/`; configuration lives in `pipeline/config/*.yaml`.

# Access Deserts — Phased Implementation Plan

São Paulo first. Adding a city means adding configuration rows (city, boundary layer, sources), not new code. I stop after each phase and report what works, what failed, and what I could not verify. Then I wait for your approval before starting the next phase. I will not guess layer names, URLs or field names. Anything I have not verified is marked as unverified and shown in Admin for you to approve.

## Phase 1 — Foundations (the only phase built after you approve this plan)
- Turn on Lovable Cloud. No user login. All pages can be read by anyone.
- Data tables: `cities` (SP, IBGE 3550308, H3 resolution, thresholds), `sources` (fields as listed in the brief, plus `approved`), `discovered_layers`, `runs`, `run_logs`.
- Fill `sources` with every GeoSampa layer from the brief, all set to `approved = false`. The 4 context layers are flagged so they are never counted as services.
- Admin page at `/admin`, unlocked with a key stored as a Cloud secret (`ADMIN_KEY`). The key is checked on the server for every admin action. After a correct key, a signed session cookie is set.
- Discovery: on the server, fetch GeoSampa WFS GetCapabilities from the public host only. Search layer Name/Title for ponto, parada, onibus, terminal, trem, cptm, estacao. Each candidate gets a feature count (`resultType=hits`) and is listed in Admin with an approve button. Any `*.prodam` hostnames are logged as a quality issue.
- Basic app shell: top navigation (Map, Reliability, Method, Community, Proposals), the footer text from the brief, and the design tokens (neutral greys, one colour-blind-safe accent colour for deserts).
- Report: the GetCapabilities result, the candidate list, and whether the 15 seeded layer names actually exist on the server.

## Phase 2 — First end-to-end slice
- FETCH adapter (`wfs`) for `equipamento_saude_ubs_posto_centro`: page through results with COUNT/STARTINDEX and store raw pages with `fetched_at` under a `run_id`.
- NORMALISE into the common schema. If the response comes back in EPSG:31983, convert coordinates with proj4.
- Quality metrics for this source: record count, % missing coordinates, % outside the city boundary (boundary from `area_contexto`), fields more than 20% empty.
- Map page (MapLibre, CARTO Positron) showing the UBS points with a reliability badge.
- Report the feature count so you can compare it with the GeoSampa portal.

## Phase 3 — All GeoSampa service layers and boundaries
- Every approved service layer, including subcategories. Polygon handling: distance to the nearest edge, with centroid as a fallback; the method used is recorded.
- District and municipal boundaries. Change vs the previous run (added/removed).

## Phase 4 — Demand
- I find the IBGE 2022 tract mesh and the income CSV URLs and show them in Admin for your approval. Then: filter to 3550308 and store only that subset. Suppressed values are stored as MISSING, never zero, and their count and share are reported.
- First, check whether `densidade_demografica` carries population per tract.
- H3 grid (resolution 8) clipped to the city boundary. Population and income estimated per hexagon by area weighting.

## Phase 5 — Metrics and full map
- Per hexagon: service counts within 1 km, nearest distance per category, transit within 500 m, desert flags, desert_count, vulnerability score (default formula from the brief).
- Choropleth layer switcher, hexagon detail panel, district summaries, city selector.

## Phase 6 — Reliability and AI
- One card per source per run with every metric. Confidence rules (high/medium/low) written in plain English.
- AI classification for records the rules cannot map, plus duplicate flagging (same category, under 50 m apart, similar names). Suggestions are stored alongside rule-based categories, never replacing them. Every AI decision is logged, and there is an "AI decisions" table with filters.

## Phase 7 — Narrative pages, snapshots, export
- Method page: parameters filled in automatically, plus [TO BE COMPLETED] sections. Community Validation and Proposals pages as placeholders only.
- "Publish snapshot" freezes a run at `/snapshot/{date}`, which only reads stored results. `/` shows "Live data – last updated {date}".
- Export the current map view as a PNG with legend and title.

## Phase 8 — National adapters (only after your approval)
- Overpass adapter for OpenStreetMap; CRAS marked "not available from OSM". CNES and INEP adapters after their endpoints are verified. A second test city.

## Technical notes
- The brief asks for edge functions. This stack's equivalent is server functions plus server routes; the pipeline steps run there, and each step is a separate endpoint that is idempotent and processes one city in batches. A step that needs more time continues across several calls using a cursor stored in `runs`, which keeps each call within time and memory limits. The browser never calls external sources.
- Libraries: `h3-js`, `proj4`, `@turf/turf`, `maplibre-gl` (loaded in the browser only).
- Results are stored per `run_id` and never overwritten. Large raw payloads go to Cloud storage as JSON; normalised records go to tables.
- AI uses the built-in Lovable AI (no external key needed).
- Risk: the GeoSampa host may be slow or block requests from cloud servers. Phase 1 tests this first and reports what happens.
