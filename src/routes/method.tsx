import { createFileRoute } from "@tanstack/react-router";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/method")({
  head: () => ({
    meta: [
      { title: "Method — Access Deserts" },
      {
        name: "description",
        content: "Parameters, rules and limitations of the access desert analysis.",
      },
      { property: "og:title", content: "Method — Access Deserts" },
      { property: "og:description", content: "How access deserts are computed." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MethodPage,
});

// Placeholder list. Parameters and counts will be filled from run.json / quality.json (Phase 8).
const SECTIONS = [
  { title: "Research question", body: ["[TO BE COMPLETED]"] },
  {
    title: "Record inclusion rules",
    body: [
      'Only services that are public, free at the point of use and currently existing are counted. No source record is removed: every record stays in the published data with an included_in_metrics flag and, when excluded, an exclusion reason. Rules are configured per source in pipeline/config/sources.yaml. Records without coordinates are excluded ("missing coordinates").',
      'Basic health units: units run by a private provider are excluded ("private provider"); units with type "SEM TIPO" are excluded ("missing type, needs review"). Exclusion takes precedence, so the two state-run units without a type stay excluded.',
      'Early-childhood education: partner crèches (type "CR.P.CONV") are included, as a separate subcategory (partner network).',
      'Libraries, museums, cultural spaces, theatres and cinemas: privately run venues are excluded ("private provider"). Theatres and cinemas are listed per room; rooms at the same address are one venue, and each venue is counted once.',
      'Parks: parks marked as proposed are excluded ("planned, not built").',
      "Social assistance: CRAS locations are the CRAS class of the social assistance facilities layer. The layer named after CRAS holds coverage areas, not locations, and is not used.",
      'Bus terminals: intercity ("RODOVIARIO") terminals are excluded ("intercity terminal, not daily access"). Bus corridors are shown for context only, and only those in operation.',
      "City boundary: the union of the 96 municipal districts, checked on every run against the São Paulo municipality polygon of the GeoSampa context layer.",
      "[TO BE COMPLETED: counts per rule from quality.json]",
    ],
  },
  { title: "Parameters", body: ["[TO BE COMPLETED: filled automatically from run.json]"] },
  { title: "Limitations", body: ["[TO BE COMPLETED]"] },
  { title: "Tools", body: ["[TO BE COMPLETED]"] },
];

function MethodPage() {
  return (
    <SiteShell>
      <section className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Method</h1>
        {SECTIONS.map((s) => (
          <div key={s.title} className="mt-8">
            <h2 className="text-xl font-semibold">{s.title}</h2>
            <div className="mt-3 space-y-2">
              {s.body.map((t) =>
                t.startsWith("[TO BE COMPLETED") ? (
                  <Placeholder key={t}>{t}</Placeholder>
                ) : (
                  <p key={t} className="text-sm leading-relaxed">
                    {t}
                  </p>
                ),
              )}
            </div>
          </div>
        ))}
      </section>
    </SiteShell>
  );
}
