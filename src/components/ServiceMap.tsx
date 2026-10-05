import { useEffect, useRef, useState } from "react";
import type {
  FilterSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl";
// maplibre-gl 6 loads its worker from a URL relative to its own module, which breaks once Vite
// pre-bundles the package. Vite bundles the worker separately and we hand maplibre its URL.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { ServiceProperties, Services } from "@/lib/runs";

// Free CARTO Positron basemap (no API key). Its attribution is carried by the style.
const BASEMAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

// Included and excluded records differ by shape (filled vs hollow), not only colour.
export const INCLUDED_COLOR = "#1f5f7a";
export const EXCLUDED_STROKE = "#4b5563";

const SOURCE = "services";
const INCLUDED = "services-included";
const EXCLUDED = "services-excluded";

function popupContent(p: ServiceProperties): HTMLElement {
  const el = document.createElement("div");
  el.className = "space-y-1 text-xs";
  const add = (tag: string, text: string, className = "") => {
    const n = document.createElement(tag);
    n.textContent = text;
    if (className) n.className = className;
    el.appendChild(n);
  };
  add("p", p.name ?? "(no name in source)", "font-semibold text-sm");
  if (p.address) add("p", p.address);
  if (p.equipment_type) add("p", `Type: ${p.equipment_type}`);
  if (p.administrative_sphere) add("p", `Administrative sphere: ${p.administrative_sphere}`);
  add(
    "p",
    p.included_in_metrics
      ? "Included in metrics"
      : `Excluded from metrics: ${p.exclusion_reason ?? "no reason recorded"}`,
    p.included_in_metrics ? "" : "font-medium",
  );
  if (p.override_reason) add("p", `Decided by an approved record override: ${p.override_reason}`);
  add("p", p.id, "font-mono text-[10px] text-muted-foreground break-all");
  return el;
}

function withGeometry(services: Services): Services {
  return { ...services, features: services.features.filter((f) => f.geometry !== null) };
}

export function ServiceMap({
  services,
  visibleSources,
  showExcluded,
  label,
}: {
  services: Services;
  visibleSources: string[];
  showExcluded: boolean;
  label: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create the map once, in the browser only.
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
          m.addSource(SOURCE, {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          });
          m.addLayer({
            id: EXCLUDED,
            type: "circle",
            source: SOURCE,
            filter: ["==", ["get", "included_in_metrics"], false],
            paint: {
              "circle-radius": 5,
              "circle-color": "#ffffff",
              "circle-stroke-color": EXCLUDED_STROKE,
              "circle-stroke-width": 1.75,
            },
          });
          m.addLayer({
            id: INCLUDED,
            type: "circle",
            source: SOURCE,
            filter: ["==", ["get", "included_in_metrics"], true],
            paint: {
              "circle-radius": 4.5,
              "circle-color": INCLUDED_COLOR,
              "circle-stroke-color": "#ffffff",
              "circle-stroke-width": 1,
            },
          });
          for (const id of [INCLUDED, EXCLUDED]) {
            m.on("click", id, (e: MapLayerMouseEvent) => {
              const f = e.features?.[0];
              if (!f) return;
              new maplibregl.Popup({ maxWidth: "280px" })
                .setLngLat(e.lngLat)
                .setDOMContent(popupContent(f.properties as unknown as ServiceProperties))
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

  // Data: replace the source and fit the view to the points.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const data = withGeometry(services);
    (m.getSource(SOURCE) as GeoJSONSource).setData(
      data as unknown as Parameters<GeoJSONSource["setData"]>[0],
    );
    const coords = data.features
      .filter((f) => f.geometry?.type === "Point")
      .map((f) => f.geometry!.coordinates as [number, number]);
    if (coords.length) {
      const lons = coords.map((c) => c[0]);
      const lats = coords.map((c) => c[1]);
      m.fitBounds(
        [
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ],
        { padding: 40, duration: 0 },
      );
    }
  }, [ready, services]);

  // Visibility: which sources, and whether excluded records are drawn.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const filter = (included: boolean): FilterSpecification => [
      "all",
      ["==", ["get", "included_in_metrics"], included],
      ["in", ["get", "source_id"], ["literal", visibleSources]],
    ];
    m.setFilter(INCLUDED, filter(true));
    m.setFilter(EXCLUDED, filter(false));
    m.setLayoutProperty(EXCLUDED, "visibility", showExcluded ? "visible" : "none");
  }, [ready, visibleSources, showExcluded]);

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
