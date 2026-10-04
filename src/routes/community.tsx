import { createFileRoute } from "@tanstack/react-router";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/community")({
  head: () => ({
    meta: [
      { title: "Community validation — Access Deserts" },
      { name: "description", content: "Summaries of conversations used to check the map against local knowledge." },
      { property: "og:title", content: "Community validation — Access Deserts" },
      { property: "og:description", content: "Checking the map against local knowledge." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => (
    <SiteShell>
      <section className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Community validation</h1>
        <div className="mt-6"><Placeholder>[TO BE COMPLETED]</Placeholder></div>
      </section>
    </SiteShell>
  ),
});
