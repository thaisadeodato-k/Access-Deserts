import { createFileRoute } from "@tanstack/react-router";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/proposals")({
  head: () => ({
    meta: [
      { title: "Proposals — Access Deserts" },
      { name: "description", content: "Spatial proposals grounded in the access desert analysis." },
      { property: "og:title", content: "Proposals — Access Deserts" },
      { property: "og:description", content: "Spatial proposals grounded in the data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => (
    <SiteShell>
      <section className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Proposals</h1>
        <div className="mt-6"><Placeholder>[TO BE COMPLETED]</Placeholder></div>
      </section>
    </SiteShell>
  ),
});
