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
      "Social assistance: CRAS locations are the CRAS class of the social assistance facilities layer. The layer named after CRAS holds coverage areas, not locations, and is not counted. Because the facilities layer has no unit-name field, a CRAS takes the name of the coverage area that contains it, only when exactly one CRAS lies in exactly one area; these names are marked as derived, and the others stay unnamed.",
      "Records outside the municipal boundary (mostly train stations and intercity bus terminals near the border) are kept and counted, and flagged as outside the boundary.",
      'Bus terminals: intercity ("RODOVIARIO") terminals are excluded ("intercity terminal, not daily access"). Bus corridors are shown for context only, and only those in operation.',
      "City boundary: the union of the 96 municipal districts, checked on every run against the São Paulo municipality polygon of the GeoSampa context layer.",
      "[TO BE COMPLETED: counts per rule from quality.json]",
    ],
  },
  {
    title: "Population, income and vulnerability",
    body: [
      "Population (IBGE Census 2022, total persons per census tract) and income are moved from census tracts to H3 hexagons (resolution 8) in proportion to area. Tract boundaries come from GeoSampa; every run checks that GeoSampa's tract population equals IBGE's.",
      'Income is the mean monthly income of household heads (IBGE variable V06004), averaged over the tracts in each hexagon and weighted by the number of household heads. Values that IBGE suppresses ("X") or leaves blank (".") are treated as missing, never as zero. A hexagon gets no income estimate when less than 50% of its population lives in tracts with published income.',
      "The vulnerability score is 1 minus the percentile rank of hexagon income among populated hexagons with an income estimate: 1 is the lowest income, 0 the highest.",
      "Census income is the primary vulnerability measure instead of the Índice Paulista de Vulnerabilidade Social (IPVS 2022, Fundação SEADE) because the Census covers every Brazilian municipality, so the method can be applied to other cities, while IPVS covers only São Paulo state and leaves 1,426 tracts of the city unclassified. IPVS 2022 is shown as a labelled comparison layer, with the correlation between the two reported in the run data.",
    ],
  },
  { title: "Parameters", body: ["[TO BE COMPLETED: filled automatically from run.json]"] },
  {
    title: "Limitations",
    body: [
      "Edge effect: GeoSampa only covers services inside São Paulo. Areas near the municipal border may appear less served than they are, because nearby services in neighbouring municipalities are missing. The few records outside the boundary that GeoSampa does include (mainly train stations and bus terminals) are kept.",
      "Income bias: IBGE's mean income (V06004) only covers household heads who have an income. Heads without income are left out, so the mean overstates income where many heads have none, typically in the poorest tracts. The number of heads with income is not published by tract, so the mean cannot be corrected.",
      "Area-weighted interpolation: population and income are moved from census tracts to hexagons in proportion to area, which assumes people are spread evenly within each tract. Large tracts that are partly uninhabited (for example reservoirs and protected areas in the far south) spread their population over empty land. Dasymetric interpolation, using land-use data to place people only where they live, is possible future work.",
      "[TO BE COMPLETED]",
    ],
  },
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
