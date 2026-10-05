import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import maplibreCss from "maplibre-gl/dist/maplibre-gl.css?url";
import { RunMessage, RunView } from "@/components/RunView";
import { DEFAULT_CITY, fetchRunIndex, latestRun } from "@/lib/runs";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Access Deserts — São Paulo" },
      {
        name: "description",
        content:
          "Where population density and social vulnerability coincide with poor access to public services in São Paulo, with data reliability shown.",
      },
      { property: "og:title", content: "Access Deserts — São Paulo" },
      {
        property: "og:description",
        content:
          "Spatial analysis of access to essential public services, built on open public data.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
    links: [{ rel: "stylesheet", href: maplibreCss }],
  }),
  component: MapPage,
});

function MapPage() {
  const { data: index, error } = useQuery({ queryKey: ["run-index"], queryFn: fetchRunIndex });
  if (error)
    return (
      <RunMessage heading="Map">The runs index could not be loaded: {error.message}</RunMessage>
    );
  if (!index) return <RunMessage heading="Map">Loading…</RunMessage>;
  const entry = latestRun(index, DEFAULT_CITY);
  if (!entry) return <RunMessage heading="Map">No completed run yet.</RunMessage>;
  return <RunView entry={entry} labelFor={(date) => `Live data – last updated ${date}`} />;
}
