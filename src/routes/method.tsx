import { createFileRoute } from "@tanstack/react-router";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/method")({
  head: () => ({
    meta: [
      { title: "Method — Access Deserts" },
      { name: "description", content: "Parameters, rules and limitations of the access desert analysis." },
      { property: "og:title", content: "Method — Access Deserts" },
      { property: "og:description", content: "How access deserts are computed." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => (
    <SiteShell>
      <section className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Method</h1>
        <div className="mt-6"><Placeholder>[TO BE COMPLETED]</Placeholder></div>
      </section>
    </SiteShell>
  ),
});
