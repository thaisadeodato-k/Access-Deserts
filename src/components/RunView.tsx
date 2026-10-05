import { useMemo, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQueries, useQuery } from "@tanstack/react-query";
import { SiteShell, Placeholder } from "@/components/SiteShell";
import { ServiceMap } from "@/components/ServiceMap";
import { CATEGORY_LABEL, CATEGORY_ORDER, CONTEXT_STYLE, categoryColor } from "@/lib/categories";
import {
  fetchRunData,
  fetchServiceFile,
  formatRunDate,
  type QualitySource,
  type RunData,
  type RunIndexEntry,
  type ServiceFeature,
  type Services,
} from "@/lib/runs";

// Heavy layers (sources.yaml map_initially_hidden) start hidden and are downloaded only when
// switched on. Runs without that flag fall back to a record-count threshold.
const DENSE_LAYER = 5000;

function startsVisible(s: QualitySource): boolean {
  return s.map_initially_visible ?? s.record_count <= DENSE_LAYER;
}

/** Page frame for states without run data (loading, not found, errors). */
export function RunMessage({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <SiteShell>
      <section className="mx-auto max-w-7xl px-4 py-10">
        <h1 className="text-3xl font-semibold">{heading}</h1>
        <div className="mt-6">
          <Placeholder>{children}</Placeholder>
        </div>
      </section>
    </SiteShell>
  );
}

/** Map and side panel for one run. `labelFor` builds the provenance label from the run date. */
export function RunView({
  entry,
  labelFor,
}: {
  entry: RunIndexEntry;
  labelFor: (date: string) => string;
}) {
  const { data, error } = useQuery({
    queryKey: ["run", entry.run_id],
    queryFn: () => fetchRunData(entry),
    staleTime: Infinity,
  });
  if (error)
    return <RunMessage heading="Map">Run data could not be loaded: {error.message}</RunMessage>;
  if (!data) return <RunMessage heading="Map">Loading run data…</RunMessage>;
  return <RunLoaded data={data} label={labelFor(formatRunDate(data.run.finished_at))} />;
}

function RunLoaded({ data, label }: { data: RunData; label: string }) {
  const runDate = formatRunDate(data.run.finished_at);
  const layers = useMemo(
    () =>
      data.quality.sources.filter(
        (s) => s.source_id in data.serviceFiles || s.source_id in data.preloaded,
      ),
    [data],
  );
  const groups = useMemo(() => {
    const cats = [...new Set(layers.map((s) => s.category ?? "other"))].sort(
      (a, b) =>
        (CATEGORY_ORDER as readonly string[]).indexOf(a) -
        (CATEGORY_ORDER as readonly string[]).indexOf(b),
    );
    return cats.map((c) => ({
      category: c,
      sources: layers.filter((s) => (s.category ?? "other") === c),
    }));
  }, [layers]);
  const contextIds = useMemo(
    () => [...(data.boundary ? ["boundary"] : []), ...Object.keys(data.context)],
    [data],
  );
  const sourceNames = useMemo(
    () => Object.fromEntries(data.quality.sources.map((s) => [s.source_id, s.name])),
    [data],
  );
  const [visible, setVisible] = useState<string[]>(() =>
    layers.filter(startsVisible).map((s) => s.source_id),
  );
  // Service files are downloaded the first time their layer is shown, then kept in the cache.
  const toLoad = visible.filter((id) => data.serviceFiles[id] && !data.preloaded[id]);
  const loaded = useQueries({
    queries: toLoad.map((id) => ({
      queryKey: ["services", data.entry.run_id, id],
      queryFn: () => fetchServiceFile(data.entry, data.serviceFiles[id]!),
      staleTime: Infinity,
    })),
    combine: (results) => ({
      byId: Object.fromEntries(
        results.flatMap((r, i) => (r.data ? [[toLoad[i]!, r.data] as const] : [])),
      ) as Record<string, Services>,
      pending: toLoad.filter((_, i) => results[i]?.isPending),
      failed: toLoad.filter((_, i) => results[i]?.isError),
    }),
  });
  const loadedKey = Object.keys(loaded.byId).sort().join(",");
  const services = useMemo<Services>(() => {
    const features: ServiceFeature[] = [];
    for (const col of [...Object.values(data.preloaded), ...Object.values(loaded.byId)])
      features.push(...col.features);
    return { type: "FeatureCollection", features };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadedKey tracks loaded.byId
  }, [data, loadedKey]);
  const [visibleContext, setVisibleContext] = useState<string[]>(() =>
    contextIds.filter((id) => id !== "sp_geosampa_corredor_onibus"),
  );
  const [showExcluded, setShowExcluded] = useState(true);
  const toggleIn = (set: typeof setVisible) => (id: string, on: boolean) =>
    set((v) => (on ? [...v, id] : v.filter((x) => x !== id)));

  return (
    <SiteShell runDate={runDate}>
      <section className="mx-auto max-w-7xl px-4 pt-6">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
        <h1 className="mt-1 text-2xl font-semibold">Map — {data.run.city_name}</h1>
        <p className="mt-1 font-mono text-xs text-muted-foreground">Run {data.run.run_id}</p>
      </section>
      <section className="mx-auto grid max-w-7xl gap-4 px-4 py-4 lg:grid-cols-[1fr_360px]">
        <div className="h-[75vh] overflow-hidden rounded border border-border">
          <ServiceMap
            services={services}
            boundary={data.boundary}
            context={data.context}
            sourceNames={sourceNames}
            visibleSources={visible}
            visibleContext={visibleContext}
            showExcluded={showExcluded}
            label={`Map of service locations in ${data.run.city_name}, run ${data.run.run_id}`}
          />
        </div>
        <aside
          className="space-y-4 text-sm lg:max-h-[75vh] lg:overflow-y-auto"
          aria-label="Map layers"
        >
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Layers</h2>
            <span className="text-xs text-muted-foreground">included / records</span>
          </div>
          {groups.map((g) => (
            <div key={g.category}>
              <h3 className="flex items-center gap-2 font-sans text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <Swatch color={categoryColor(g.category)} />
                {CATEGORY_LABEL[g.category] ?? g.category}
              </h3>
              <ul className="mt-1 space-y-1">
                {g.sources.map((s) => (
                  <LayerRow
                    key={s.source_id}
                    source={s}
                    checked={visible.includes(s.source_id)}
                    status={
                      loaded.failed.includes(s.source_id)
                        ? "could not be loaded"
                        : loaded.pending.includes(s.source_id)
                          ? "loading…"
                          : null
                    }
                    onChange={(on) => toggleIn(setVisible)(s.source_id, on)}
                  />
                ))}
              </ul>
            </div>
          ))}
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showExcluded}
              onChange={(e) => setShowExcluded(e.target.checked)}
              className="h-4 w-4 accent-foreground"
            />
            Show records excluded from metrics
          </label>
          {contextIds.length > 0 && (
            <div>
              <h3 className="font-sans text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Context (not counted)
              </h3>
              <ul className="mt-1 space-y-1">
                {contextIds.map((id) => (
                  <li key={id}>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={visibleContext.includes(id)}
                        onChange={(e) => toggleIn(setVisibleContext)(id, e.target.checked)}
                        className="h-4 w-4 accent-foreground"
                      />
                      <span
                        aria-hidden="true"
                        className="inline-block h-0.5 w-4"
                        style={{ backgroundColor: CONTEXT_STYLE[id]?.color ?? "#6b7280" }}
                      />
                      {CONTEXT_STYLE[id]?.label ?? sourceNames[id] ?? id}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Legend />
          <p className="text-xs text-muted-foreground">
            Access metrics, population and desert areas are not computed yet (later phases). This
            map shows source records only.
          </p>
        </aside>
      </section>
    </SiteShell>
  );
}

function Swatch({ color, hollow = false }: { color: string; hollow?: boolean }) {
  return (
    <svg width="12" height="12" aria-hidden="true" className="shrink-0">
      <circle
        cx="6"
        cy="6"
        r="4.5"
        fill={hollow ? "#fff" : color}
        stroke={hollow ? color : "#fff"}
        strokeWidth={hollow ? 1.75 : 1}
      />
    </svg>
  );
}

function LayerRow({
  source,
  checked,
  status,
  onChange,
}: {
  source: QualitySource;
  checked: boolean;
  status: string | null;
  onChange: (on: boolean) => void;
}) {
  const noGeometry = Math.round(
    ((source.pct_missing_coordinates ?? 0) * source.record_count) / 100,
  );
  const highlighted = source.findings.filter((f) => f.highlight);
  const reasons = Object.entries(source.inclusion.excluded_by_reason ?? {});
  return (
    <li className="rounded border border-border bg-card">
      <div className="flex items-start gap-2 px-2 py-1.5">
        <input
          id={`layer-${source.source_id}`}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-foreground"
        />
        <label htmlFor={`layer-${source.source_id}`} className="flex-1">
          {source.name}
          {status && <span className="ml-1 text-xs text-muted-foreground">({status})</span>}
        </label>
        <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
          {source.inclusion.included_in_metrics.toLocaleString("en-GB")} /{" "}
          {source.record_count.toLocaleString("en-GB")}
        </span>
      </div>
      <details className="border-t border-border px-2 py-1 text-xs">
        <summary className="cursor-pointer text-muted-foreground">Details and reliability</summary>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {reasons.map(([reason, n]) => (
            <FragmentRow key={reason} term={`Excluded: ${reason}`} value={n} />
          ))}
          <FragmentRow term="No coordinates" value={`${noGeometry} (not drawn)`} />
          {source.pct_outside_city_boundary != null && (
            <FragmentRow
              term="Outside city boundary"
              value={`${source.pct_outside_city_boundary}%`}
            />
          )}
          <FragmentRow term="Fetched" value={formatRunDate(source.fetched_at)} />
        </dl>
        <p className="mt-2">
          <span className="font-medium">Reliability:</span>{" "}
          {source.confidence ?? "confidence rating not yet computed"}
        </p>
        {highlighted.map((f) => (
          <p key={f.text} className="mt-1">
            {f.text}
          </p>
        ))}
        <Link
          to="/reliability"
          hash={source.source_id}
          className="mt-1 inline-block underline underline-offset-2 hover:text-foreground"
        >
          Quality card
        </Link>
        <p className="mt-1 text-muted-foreground">
          {source.publisher} · <span className="font-mono">{source.layer}</span>
        </p>
      </details>
    </li>
  );
}

function FragmentRow({ term, value }: { term: string; value: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd>{value}</dd>
    </>
  );
}

function Legend() {
  return (
    <div className="space-y-1 text-xs">
      <h3 className="font-sans font-medium">Legend</h3>
      <p className="flex items-center gap-2">
        <Swatch color="#4b5563" />
        Included in metrics (colour = category)
      </p>
      <p className="flex items-center gap-2">
        <Swatch color="#4b5563" hollow />
        Excluded from metrics (click a point or area for the reason)
      </p>
      <p>Parks and squares are drawn as areas; excluded areas have a dashed outline.</p>
    </div>
  );
}
