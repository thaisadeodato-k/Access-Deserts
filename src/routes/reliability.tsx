import { createFileRoute } from "@tanstack/react-router";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/reliability")({
  head: () => ({
    meta: [
      { title: "Reliability — Access Deserts" },
      { name: "description", content: "Automatic quality and provenance metrics for every data source and run." },
      { property: "og:title", content: "Reliability — Access Deserts" },
      { property: "og:description", content: "Data quality and provenance per source and run." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => (
    <SiteShell>
      <section className="mx-auto max-w-4xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Reliability</h1>
        <div className="mt-6"><Placeholder>Source cards appear after the first data run (Phase 2 onward).</Placeholder></div>
      </section>
    </SiteShell>
  ),
});
