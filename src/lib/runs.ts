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
};

export type QualityFinding = {
  highlight: boolean;
  field: string;
  label: string;
  pct_empty: number;
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
  findings: QualityFinding[];
  inclusion: { included_in_metrics: number; excluded_from_metrics: number };
  confidence: string | null;
};

export type Quality = {
  run_id: string;
  city_code: string;
  generated_at: string;
  sources: QualitySource[];
};

export type ServiceProperties = {
  id: string;
  source_id: string;
  name: string | null;
  category: string | null;
  subcategory: string | null;
  geometry_type: string | null;
  address: string | null;
  included_in_metrics: boolean;
  exclusion_reason: string | null;
};

export type ServiceFeature = {
  type: "Feature";
  geometry: { type: string; coordinates: unknown } | null;
  properties: ServiceProperties;
};

export type Services = { type: "FeatureCollection"; features: ServiceFeature[] };

export type RunData = { entry: RunIndexEntry; run: RunInfo; quality: Quality; services: Services };

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

export async function fetchRunData(entry: RunIndexEntry): Promise<RunData> {
  const [run, quality, services] = await Promise.all([
    fetchJson<RunInfo>(`${entry.path}run.json`),
    fetchJson<Quality>(`${entry.path}quality.json`),
    fetchJson<Services>(`${entry.path}services.geojson`),
  ]);
  return { entry, run, quality, services };
}
