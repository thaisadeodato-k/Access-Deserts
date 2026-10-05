import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import maplibreCss from "maplibre-gl/dist/maplibre-gl.css?url";
import { RunMessage, RunView } from "@/components/RunView";
import { fetchRunIndex, isIsoDate, snapshotForDate } from "@/lib/runs";

// A run marked `snapshot: true` in runs/index.json, served by the date in its run_id.
// Its data files never change; this route only reads them.
export const Route = createFileRoute("/snapshot/$date")({
  head: ({ params }) => ({
    meta: [
      { title: `Snapshot ${params.date} — Access Deserts` },
      { name: "description", content: `Access Deserts, frozen data snapshot of ${params.date}.` },
      { property: "og:title", content: `Snapshot ${params.date} — Access Deserts` },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
    links: [{ rel: "stylesheet", href: maplibreCss }],
  }),
  component: SnapshotPage,
});

function SnapshotPage() {
  const { date } = Route.useParams();
  const { data: index, error } = useQuery({ queryKey: ["run-index"], queryFn: fetchRunIndex });
  const heading = `Snapshot ${date}`;
  if (!isIsoDate(date))
    return <RunMessage heading={heading}>Not a valid date (expected YYYY-MM-DD).</RunMessage>;
  if (error)
    return (
      <RunMessage heading={heading}>The runs index could not be loaded: {error.message}</RunMessage>
    );
  if (!index) return <RunMessage heading={heading}>Loading…</RunMessage>;
  const found = snapshotForDate(index, date);
  if (found.kind === "none")
    return <RunMessage heading={heading}>No snapshot exists for {date}.</RunMessage>;
  if (found.kind === "ambiguous")
    return (
      <RunMessage heading={heading}>
        More than one snapshot is marked for {date} ({found.entries.map((e) => e.run_id).join(", ")}
        ). This is a data error: only one snapshot per date is allowed.
      </RunMessage>
    );
  return <RunView entry={found.entry} labelFor={(d) => `Snapshot – data from ${d}`} />;
}
