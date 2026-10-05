// Reads pipeline run files from public/data/ (served at /data/). The frontend never calls
// external data sources: everything shown comes from these static files.

/** City shown on the live route. Cities themselves are configured in pipeline/config/cities.yaml. */
export const DEFAULT_CITY = "sp";

const DATA_BASE = "/data";

export type RunIndexEntry = {
  run_id: string;
  city_code: string;
  started_at: string;
  finished_at: string;
  status: string;
  snapshot: boolean;
  path: string;
};

export type RunIndex = {
  schema_version: number;
  latest: Record<string, string>;
  runs: RunIndexEntry[];
};

export type RunInfo = {
  run_id: string;
  city_code: string;
  city_name: string;
  status: string;
  started_at: string;
  finished_at: string;
  errors: unknown[];
  /** Files written by the run (relative to the run folder); older runs list fewer. */
  outputs?: string[];
};

/** kind: "empty_field" (highlight_fields), "rule_matches", "include_rule_without_effect". */
export type QualityFinding = {
  kind: string;
  highlight: boolean;
  text: string;
};

export type QualitySource = {
  source_id: string;
  name: string;
  publisher: string;
  layer: string;
  fetched_at: string;
  record_count: number;
  pct_missing_coordinates: number | null;
  role?: string;
  category?: string | null;
  /** From sources.yaml map_initially_hidden; heavy layers load only when switched on. */
  map_initially_visible?: boolean;
  findings: QualityFinding[];
  inclusion: {
    included_in_metrics: number;
    excluded_from_metrics: number;
    excluded_by_reason?: Record<string, number>;
  };
  pct_outside_city_boundary?: number | null;
  confidence: string | null;
};

export type DemandSummary = {
  method?: Record<string, unknown>;
  hexagons?: number;
  hexagons_populated?: number;
  hexagons_scored?: number;
  comparison?: { hexagons_compared: number; spearman_rho: number | null } | null;
  error?: string;
};

export type Quality = {
  run_id: string;
  city_code: string;
  generated_at: string;
  sources: QualitySource[];
  /** Phase 5 onwards. */
  demand?: DemandSummary | null;
};

export type HexagonProperties = {
  h3_id: string;
  population_est: number;
  households_est: number;
  pop_density_km2: number | null;
  income_est: number | null;
  income_coverage: number | null;
  vulnerability_score: number | null;
  comparison_mean: number | null;
  comparison_vulnerable_share: number | null;
  comparison_coverage: number | null;
};

export type ServiceProperties = {
  id: string;
  source_id: string;
  name: string | null;
  /** True when the name comes from another layer (e.g. CRAS coverage area), not the source. */
  name_derived?: boolean;
  category: string | null;
  subcategory: string | null;
  geometry_type: string | null;
  address: string | null;
  equipment_type: string | null;
  administrative_sphere: string | null;
  included_in_metrics: boolean;
  exclusion_reason: string | null;
  override_reason: string | null;
  venue_id?: string | null;
  /** Outside the municipal boundary (still counted); null without geometry. */
  outside_boundary?: boolean | null;
};

export type ServiceFeature = {
  type: "Feature";
  geometry: { type: string; coordinates: unknown } | null;
  properties: ServiceProperties;
};

export type Services = { type: "FeatureCollection"; features: ServiceFeature[] };

/** Display-only geometry: the city boundary and context layers (districts, corridors). */
export type GeoCollection = {
  type: "FeatureCollection";
  features: { type: "Feature"; geometry: unknown; properties: Record<string, unknown> }[];
};

export type RunData = {
  entry: RunIndexEntry;
  run: RunInfo;
  quality: Quality;
  /** Service file per source_id (relative to the run folder), loaded on demand. */
  serviceFiles: Record<string, string>;
  /** Services already in memory, keyed by source_id (runs with a single services.geojson). */
  preloaded: Record<string, Services>;
  boundary: GeoCollection | null;
  /** H3 hexagons with demand estimates (Phase 5 onwards). */
  hexagons: GeoCollection | null;
  /** Context layers keyed by source_id. */
  context: Record<string, GeoCollection>;
};

export type SnapshotLookup =
  | { kind: "found"; entry: RunIndexEntry }
  | { kind: "none" }
  | { kind: "ambiguous"; entries: RunIndexEntry[] };

export function isIsoDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`));
}

/** The run that index.json lists as latest for the city (only completed runs become latest). */
export function latestRun(index: RunIndex, city: string): RunIndexEntry | null {
  const id = index.latest[city];
  return (id && index.runs.find((r) => r.run_id === id)) || null;
}

/** Snapshot runs whose run_id starts with the date. More than one is an error, never a guess. */
export function snapshotForDate(index: RunIndex, date: string): SnapshotLookup {
  const entries = index.runs.filter((r) => r.snapshot && r.run_id.startsWith(`${date}-`));
  if (entries.length === 0) return { kind: "none" };
  if (entries.length > 1) return { kind: "ambiguous", entries };
  return { kind: "found", entry: entries[0]! };
}

/** "2026-10-05T13:50:20Z" -> "5 Oct 2026" (UTC, so the date matches the run_id). */
export function formatRunDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(iso));
}

async function fetchJson<T>(path: string): Promise<T> {
  const r = await fetch(`${DATA_BASE}/${path}`);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export function fetchRunIndex(): Promise<RunIndex> {
  return fetchJson<RunIndex>("runs/index.json");
}

/** Run metadata, quality, boundary and context. Service records are loaded per source with
 * fetchServiceFile, so dense layers (bus stops, squares) load only when shown. */
export async function fetchRunData(entry: RunIndexEntry): Promise<RunData> {
  const [run, quality] = await Promise.all([
    fetchJson<RunInfo>(`${entry.path}run.json`),
    fetchJson<Quality>(`${entry.path}quality.json`),
  ]);
  const outputs = run.outputs ?? [];
  const serviceFiles = Object.fromEntries(
    outputs
      .filter((o) => o.startsWith("services/") && o.endsWith(".geojson"))
      .map((o) => [o.slice("services/".length, -".geojson".length), o]),
  );
  // Runs before Phase 4 have one services.geojson for all sources.
  const preloaded: Record<string, Services> = {};
  if (Object.keys(serviceFiles).length === 0) {
    const all = await fetchJson<Services>(`${entry.path}services.geojson`);
    for (const f of all.features)
      (preloaded[f.properties.source_id] ??= {
        type: "FeatureCollection",
        features: [],
      }).features.push(f);
  }
  const contextFiles = outputs.filter((o) => o.startsWith("context/") && o.endsWith(".geojson"));
  const [boundary, hexagons, ...contextData] = await Promise.all([
    outputs.includes("boundary.geojson")
      ? fetchJson<GeoCollection>(`${entry.path}boundary.geojson`)
      : Promise.resolve(null),
    outputs.includes("hexagons.geojson")
      ? fetchJson<GeoCollection>(`${entry.path}hexagons.geojson`)
      : Promise.resolve(null),
    ...contextFiles.map((o) => fetchJson<GeoCollection>(`${entry.path}${o}`)),
  ]);
  const context = Object.fromEntries(
    contextFiles.map((o, i) => [o.slice("context/".length, -".geojson".length), contextData[i]!]),
  );
  return { entry, run, quality, serviceFiles, preloaded, boundary, hexagons, context };
}

export function fetchServiceFile(entry: RunIndexEntry, file: string): Promise<Services> {
  return fetchJson<Services>(`${entry.path}${file}`);
}
