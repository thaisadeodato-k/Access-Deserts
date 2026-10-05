import { useMemo, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { SiteShell, Placeholder } from "@/components/SiteShell";
import { EXCLUDED_STROKE, INCLUDED_COLOR, ServiceMap } from "@/components/ServiceMap";
import {
  fetchRunData,
  formatRunDate,
  type QualitySource,
  type RunData,
  type RunIndexEntry,
} from "@/lib/runs";

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
  const layers = useMemo(() => {
    const sourceIds = new Set(data.services.features.map((f) => f.properties.source_id));
    return data.quality.sources.filter((s) => sourceIds.has(s.source_id));
  }, [data]);
  const [visible, setVisible] = useState<string[]>(() => layers.map((s) => s.source_id));
  const [showExcluded, setShowExcluded] = useState(true);
  const toggle = (id: string, on: boolean) =>
    setVisible((v) => (on ? [...v, id] : v.filter((x) => x !== id)));

  return (
    <SiteShell runDate={runDate}>
      <section className="mx-auto max-w-7xl px-4 pt-6">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
        <h1 className="mt-1 text-2xl font-semibold">Map — {data.run.city_name}</h1>
        <p className="mt-1 font-mono text-xs text-muted-foreground">Run {data.run.run_id}</p>
      </section>
      <section className="mx-auto grid max-w-7xl gap-4 px-4 py-4 lg:grid-cols-[1fr_340px]">
        <div className="h-[70vh] overflow-hidden rounded border border-border">
          <ServiceMap
            services={data.services}
            visibleSources={visible}
            showExcluded={showExcluded}
            label={`Map of service locations in ${data.run.city_name}, run ${data.run.run_id}`}
          />
        </div>
        <aside className="space-y-4 text-sm" aria-label="Map layers">
          <h2 className="text-lg font-semibold">Layers</h2>
          {layers.map((s) => (
            <LayerCard
              key={s.source_id}
              source={s}
              data={data}
              checked={visible.includes(s.source_id)}
              onChange={(on) => toggle(s.source_id, on)}
            />
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

function LayerCard({
  source,
  data,
  checked,
  onChange,
}: {
  source: QualitySource;
  data: RunData;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  const records = data.services.features.filter((f) => f.properties.source_id === source.source_id);
  const noGeometry = records.filter((f) => f.geometry === null).length;
  const highlighted = source.findings.filter((f) => f.highlight);
  return (
    <div className="rounded border border-border bg-card p-3">
      <label className="flex items-start gap-2 font-medium">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-foreground"
        />
        {source.name}
      </label>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">Records</dt>
        <dd>{source.record_count}</dd>
        <dt className="text-muted-foreground">Included</dt>
        <dd>{source.inclusion.included_in_metrics}</dd>
        <dt className="text-muted-foreground">Excluded</dt>
        <dd>{source.inclusion.excluded_from_metrics}</dd>
        <dt className="text-muted-foreground">No coordinates</dt>
        <dd>{noGeometry} (not drawn)</dd>
        <dt className="text-muted-foreground">Fetched</dt>
        <dd>{formatRunDate(source.fetched_at)}</dd>
      </dl>
      <div className="mt-3 border-t border-border pt-2 text-xs">
        <p>
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
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="space-y-1 text-xs">
      <h3 className="font-sans font-medium">Legend</h3>
      <p className="flex items-center gap-2">
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5" fill={INCLUDED_COLOR} stroke="#fff" strokeWidth="1" />
        </svg>
        Included in metrics
      </p>
      <p className="flex items-center gap-2">
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5" fill="#fff" stroke={EXCLUDED_STROKE} strokeWidth="1.75" />
        </svg>
        Excluded from metrics (click a point for the reason)
      </p>
    </div>
  );
}
