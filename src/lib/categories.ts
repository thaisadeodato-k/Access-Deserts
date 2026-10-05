// Display labels and colours per service category. Colours: Paul Tol's "muted" scheme
// (colour-blind safe). Orange is left out: the site's accent colour is reserved for deserts.

export const CATEGORY_ORDER = [
  "health_ubs",
  "school",
  "cras",
  "park_square",
  "library",
  "culture",
  "metro_train",
  "transit",
] as const;

export const CATEGORY_LABEL: Record<string, string> = {
  health_ubs: "Basic health care",
  school: "Schools and early-childhood education",
  cras: "Social assistance (CRAS)",
  park_square: "Parks and squares",
  library: "Libraries",
  culture: "Culture",
  metro_train: "Metro and train",
  transit: "Bus",
};

export const CATEGORY_COLOR: Record<string, string> = {
  health_ubs: "#332288",
  school: "#AA4499",
  cras: "#882255",
  park_square: "#117733",
  library: "#999933",
  culture: "#CC6677",
  metro_train: "#44AA99",
  transit: "#5B8FA8",
};

export const OTHER_COLOR = "#6b7280";

export const SUBCATEGORY_LABEL: Record<string, string> = {
  primary_secondary: "Primary and secondary",
  early_childhood: "Early childhood (municipal)",
  partner_network: "Early childhood (partner network)",
  ceu: "CEU",
  park: "Park",
  square: "Square",
  cultural_space: "Cultural space",
  museum: "Museum",
  theatre_cinema: "Theatre / cinema",
  metro: "Metro",
  train: "Train",
  bus_stop: "Bus stop",
  bus_terminal: "Bus terminal",
};

// Context layers (display only, never counted).
export const CONTEXT_STYLE: Record<string, { label: string; color: string; width: number }> = {
  boundary: { label: "City boundary", color: "#374151", width: 1.5 },
  sp_geosampa_distrito_municipal: { label: "Districts", color: "#9ca3af", width: 0.6 },
  sp_geosampa_corredor_onibus: { label: "Bus corridors in operation", color: "#a07d1c", width: 2 },
};

export function categoryColor(category: string | null): string {
  return (category && CATEGORY_COLOR[category]) || OTHER_COLOR;
}
