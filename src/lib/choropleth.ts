// Hexagon (area) layers. Sequential colours: viridis (colour-blind safe, light = low, dark = high);
// the site's orange accent stays reserved for deserts.
import type { GeoCollection, HexagonProperties } from "@/lib/runs";

export const SEQUENTIAL = ["#fde725", "#5ec962", "#21918c", "#3b528b", "#440154"];
export const NO_ESTIMATE = "#d1d5db";

export type Choropleth = {
  id: string;
  label: string;
  /** Source and reference, shown under the legend. */
  note: string;
  field: keyof HexagonProperties;
  /** Hexagons where this field is below the minimum are drawn as "no estimate". */
  minCoverage?: { field: keyof HexagonProperties; value: number };
  breaks: number[]; // 4 upper bounds for 5 classes
  classLabels: string[];
};

function quantiles(values: number[], qs: number[]): number[] {
  const v = [...values].sort((a, b) => a - b);
  return qs.map((q) => v[Math.min(v.length - 1, Math.floor(q * v.length))] ?? 0);
}

const fmt = (n: number) => Math.round(n).toLocaleString("en-GB");

export function choropleths(hexagons: GeoCollection | null): Choropleth[] {
  if (!hexagons) return [];
  const props = hexagons.features.map((f) => f.properties as unknown as HexagonProperties);
  const dens = props
    .filter((p) => p.population_est > 0 && p.pop_density_km2 != null)
    .map((p) => p.pop_density_km2 as number);
  const db = quantiles(dens, [0.2, 0.4, 0.6, 0.8]);
  return [
    {
      id: "density",
      label: "Population density",
      note: "People per km² of the hexagon inside the city; IBGE Census 2022, area-weighted from census tracts. Classes are quintiles.",
      field: "pop_density_km2",
      breaks: db,
      classLabels: [
        `< ${fmt(db[0]!)}`,
        `${fmt(db[0]!)}–${fmt(db[1]!)}`,
        `${fmt(db[1]!)}–${fmt(db[2]!)}`,
        `${fmt(db[2]!)}–${fmt(db[3]!)}`,
        `≥ ${fmt(db[3]!)}`,
      ],
    },
    {
      id: "vulnerability",
      label: "Vulnerability (income)",
      note: "1 − percentile rank of household-head income (IBGE Census 2022, V06004); 1 = lowest income. No estimate where less than 50% of the population lives in tracts with published income.",
      field: "vulnerability_score",
      breaks: [0.2, 0.4, 0.6, 0.8],
      classLabels: ["0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1"],
    },
    {
      id: "ipvs",
      label: "IPVS 2022 (Fundação SEADE) — comparison",
      note: "Índice Paulista de Vulnerabilidade Social 2022, Fundação SEADE (via GeoSampa): population-weighted mean group, 1 = very low to 6 = very high vulnerability. Shown for comparison only; not used in the analysis. No estimate where less than 50% of the population lives in classified tracts.",
      field: "comparison_mean",
      minCoverage: { field: "comparison_coverage", value: 0.5 },
      breaks: [2, 3, 4, 5],
      classLabels: ["1–2", "2–3", "3–4", "4–5", "5–6"],
    },
  ];
}
