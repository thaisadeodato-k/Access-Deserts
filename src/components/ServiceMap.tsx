import { useEffect, useRef, useState } from "react";
import type {
  ExpressionSpecification,
  FilterSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl";
// maplibre-gl 6 loads its worker from a URL relative to its own module, which breaks once Vite
// pre-bundles the package. Vite bundles the worker separately and we hand maplibre its URL.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { CATEGORY_COLOR, CONTEXT_STYLE, OTHER_COLOR, SUBCATEGORY_LABEL } from "@/lib/categories";
import type { GeoCollection, ServiceProperties, Services } from "@/lib/runs";

// Free CARTO Positron basemap (no API key). Its attribution is carried by the style.
const BASEMAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const SERVICES = "services";
const POLY_INCLUDED = "services-poly-included";
const POLY_EXCLUDED = "services-poly-excluded";
const POLY_OUTLINE = "services-poly-outline";
const POLY_OUTLINE_EXCLUDED = "services-poly-outline-excluded";
const POINT_INCLUDED = "services-point-included";
const POINT_EXCLUDED = "services-point-excluded";
const CLICKABLE = [POINT_INCLUDED, POINT_EXCLUDED, POLY_INCLUDED, POLY_EXCLUDED];

type GeoData = Parameters<GeoJSONSource["setData"]>[0];

const categoryColor: ExpressionSpecification = [
  "match",
  ["get", "category"],
  ...Object.entries(CATEGORY_COLOR).flat(),
  OTHER_COLOR,
] as unknown as ExpressionSpecification;

const isPolygon: FilterSpecification = [
  "in",
  ["geometry-type"],
  ["literal", ["Polygon", "MultiPolygon"]],
];
const isPoint: FilterSpecification = ["==", ["geometry-type"], "Point"];

function popupContent(p: ServiceProperties, sourceName: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "space-y-1 text-xs";
  const add = (text: string, className = "") => {
    const n = document.createElement("p");
    n.textContent = text;
    if (className) n.className = className;
    el.appendChild(n);
  };
  add(p.name ?? "(no name in source)", "font-semibold text-sm");
  add(
    sourceName + (p.subcategory ? ` · ${SUBCATEGORY_LABEL[p.subcategory] ?? p.subcategory}` : ""),
    "text-muted-foreground",
  );
  if (p.address) add(p.address);
  if (p.equipment_type) add(`Type: ${p.equipment_type}`);
  if (p.administrative_sphere) add(`Administrative sphere: ${p.administrative_sphere}`);
  add(
    p.included_in_metrics
      ? "Included in metrics"
      : `Excluded from metrics: ${p.exclusion_reason ?? "no reason recorded"}`,
    p.included_in_metrics ? "" : "font-medium",
  );
  if (p.override_reason) add(`Decided by an approved record override: ${p.override_reason}`);
  add(p.id, "font-mono text-[10px] text-muted-foreground break-all");
  return el;
}

function withGeometry(services: Services): Services {
  return { ...services, features: services.features.filter((f) => f.geometry !== null) };
}

/** [minLon, minLat, maxLon, maxLat] of any GeoJSON coordinates. */
function bbox(
  collections: { features: { geometry: unknown }[] }[],
): [number, number, number, number] | null {
  const b = [Infinity, Infinity, -Infinity, -Infinity] as [number, number, number, number];
  const walk = (c: unknown): void => {
    if (!Array.isArray(c)) return;
    if (typeof c[0] === "number") {
      const [x, y] = c as [number, number];
      b[0] = Math.min(b[0], x);
      b[1] = Math.min(b[1], y);
      b[2] = Math.max(b[2], x);
      b[3] = Math.max(b[3], y);
    } else c.forEach(walk);
  };
  for (const col of collections)
    for (const f of col.features)
      walk((f.geometry as { coordinates?: unknown } | null)?.coordinates);
  return Number.isFinite(b[0]) ? b : null;
}

export function ServiceMap({
  services,
  boundary,
  context,
  sourceNames,
  visibleSources,
  visibleContext,
  showExcluded,
  label,
}: {
  services: Services;
  boundary: GeoCollection | null;
  context: Record<string, GeoCollection>;
  sourceNames: Record<string, string>;
  visibleSources: string[];
  visibleContext: string[];
  showExcluded: boolean;
  label: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const names = useRef(sourceNames);
  names.current = sourceNames;
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create the map and its service layers once, in the browser only.
  useEffect(() => {
    let cancelled = false;
    let instance: MapLibreMap | null = null;
    import("maplibre-gl")
      .then((maplibregl) => {
        if (cancelled || !container.current) return;
        maplibregl.setWorkerUrl(workerUrl);
        const m = new maplibregl.Map({
          container: container.current,
          style: BASEMAP_STYLE,
          center: [-46.63, -23.6],
          zoom: 9.5,
        });
        instance = m;
        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
        m.on("load", () => {
          m.addSource(SERVICES, {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          });
          // Polygons (parks, squares): filled when included, white with a dashed outline when excluded.
          m.addLayer({
            id: POLY_INCLUDED,
            type: "fill",
            source: SERVICES,
            filter: isPolygon,
            paint: { "fill-color": categoryColor, "fill-opacity": 0.35 },
          });
          m.addLayer({
            id: POLY_EXCLUDED,
            type: "fill",
            source: SERVICES,
            filter: isPolygon,
            paint: { "fill-color": "#ffffff", "fill-opacity": 0.5 },
          });
          m.addLayer({
            id: POLY_OUTLINE,
            type: "line",
            source: SERVICES,
            filter: isPolygon,
            paint: { "line-color": categoryColor, "line-width": 0.8 },
          });
          m.addLayer({
            id: POLY_OUTLINE_EXCLUDED,
            type: "line",
            source: SERVICES,
            filter: isPolygon,
            paint: { "line-color": categoryColor, "line-width": 1, "line-dasharray": [2, 2] },
          });
          // Points: filled when included, hollow when excluded (shape, not only colour).
          m.addLayer({
            id: POINT_EXCLUDED,
            type: "circle",
            source: SERVICES,
            filter: isPoint,
            paint: {
              "circle-radius": 4.5,
              "circle-color": "#ffffff",
              "circle-stroke-color": categoryColor,
              "circle-stroke-width": 1.75,
            },
          });
          m.addLayer({
            id: POINT_INCLUDED,
            type: "circle",
            source: SERVICES,
            filter: isPoint,
            // Bus stops are dense: draw them under the other categories.
            layout: { "circle-sort-key": ["match", ["get", "subcategory"], "bus_stop", 0, 1] },
            paint: {
              "circle-radius": ["match", ["get", "subcategory"], "bus_stop", 2.5, 4.5],
              "circle-color": categoryColor,
              "circle-stroke-color": "#ffffff",
              "circle-stroke-width": ["match", ["get", "subcategory"], "bus_stop", 0.5, 1],
            },
          });
          for (const id of CLICKABLE) {
            m.on("click", id, (e: MapLayerMouseEvent) => {
              const f = e.features?.[0];
              if (!f) return;
              const p = f.properties as unknown as ServiceProperties;
              new maplibregl.Popup({ maxWidth: "280px" })
                .setLngLat(e.lngLat)
                .setDOMContent(popupContent(p, names.current[p.source_id] ?? p.source_id))
                .addTo(m);
            });
            m.on("mouseenter", id, () => (m.getCanvas().style.cursor = "pointer"));
            m.on("mouseleave", id, () => (m.getCanvas().style.cursor = ""));
          }
          map.current = m;
          setReady(true);
        });
        m.on("error", (e) => console.error("[map]", e.error));
      })
      .catch((e: Error) => setError(e.message));
    return () => {
      cancelled = true;
      instance?.remove();
      map.current = null;
    };
  }, []);

  // Data: services, then context lines drawn below the services; fit the view to the city.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const data = withGeometry(services);
    (m.getSource(SERVICES) as GeoJSONSource).setData(data as unknown as GeoData);
    const lines: [string, GeoCollection][] = [
      ...Object.entries(context),
      ...(boundary ? [["boundary", boundary] as [string, GeoCollection]] : []),
    ];
    for (const [id, col] of lines) {
      const src = `context-${id}`;
      const style = CONTEXT_STYLE[id] ?? { color: OTHER_COLOR, width: 1 };
      if (m.getSource(src)) (m.getSource(src) as GeoJSONSource).setData(col as unknown as GeoData);
      else {
        m.addSource(src, { type: "geojson", data: col as unknown as GeoData });
        m.addLayer(
          {
            id: src,
            type: "line",
            source: src,
            paint: { "line-color": style.color, "line-width": style.width },
          },
          POLY_INCLUDED,
        );
      }
    }
    const b = bbox(boundary ? [boundary] : [data]);
    if (b)
      m.fitBounds(
        [
          [b[0], b[1]],
          [b[2], b[3]],
        ],
        { padding: 30, duration: 0 },
      );
  }, [ready, services, boundary, context]);

  // Visibility: which sources and context layers, and whether excluded records are drawn.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const bySource: FilterSpecification = ["in", ["get", "source_id"], ["literal", visibleSources]];
    const included = (yes: boolean): FilterSpecification => [
      "==",
      ["get", "included_in_metrics"],
      yes,
    ];
    const all = (...parts: FilterSpecification[]) => ["all", ...parts] as FilterSpecification;
    m.setFilter(POINT_INCLUDED, all(isPoint, bySource, included(true)));
    m.setFilter(POINT_EXCLUDED, all(isPoint, bySource, included(false)));
    m.setFilter(POLY_INCLUDED, all(isPolygon, bySource, included(true)));
    m.setFilter(POLY_EXCLUDED, all(isPolygon, bySource, included(false)));
    m.setFilter(POLY_OUTLINE, all(isPolygon, bySource, included(true)));
    m.setFilter(POLY_OUTLINE_EXCLUDED, all(isPolygon, bySource, included(false)));
    for (const id of [POINT_EXCLUDED, POLY_EXCLUDED, POLY_OUTLINE_EXCLUDED])
      m.setLayoutProperty(id, "visibility", showExcluded ? "visible" : "none");
    for (const id of [...Object.keys(context), "boundary"]) {
      if (m.getLayer(`context-${id}`))
        m.setLayoutProperty(
          `context-${id}`,
          "visibility",
          visibleContext.includes(id) ? "visible" : "none",
        );
    }
  }, [ready, visibleSources, visibleContext, showExcluded, context]);

  return (
    <div className="relative h-full min-h-[420px] w-full">
      {/* Inline position: maplibre's stylesheet sets .maplibregl-map { position: relative }. */}
      <div
        ref={container}
        role="region"
        aria-label={label}
        style={{ position: "absolute", inset: 0 }}
      />
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted p-4 text-sm">
          The map could not be loaded: {error}
        </div>
      )}
    </div>
  );
}
