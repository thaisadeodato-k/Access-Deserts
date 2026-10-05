import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

const NAV = [
  { to: "/", label: "Map" },
  { to: "/reliability", label: "Reliability" },
  { to: "/method", label: "Method" },
  { to: "/community", label: "Community validation" },
  { to: "/proposals", label: "Proposals" },
] as const;

export function SiteShell({ children, runDate }: { children: ReactNode; runDate?: string | null }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-baseline gap-x-8 gap-y-2 px-4 py-3">
          <Link to="/" className="font-serif text-xl font-semibold">
            Access Deserts
          </Link>
          <nav aria-label="Main" className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {NAV.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                activeOptions={{ exact: n.to === "/" }}
                className="text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring data-[status=active]:text-foreground data-[status=active]:underline data-[status=active]:decoration-accent data-[status=active]:underline-offset-4"
              >
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-border bg-card">
        <div className="mx-auto max-w-7xl px-4 py-4 text-xs text-muted-foreground">
          Data: GeoSampa – Prefeitura de São Paulo (SMUL/Geoinfo); IBGE – Censo Demográfico 2022; OpenStreetMap
          contributors (when used). Run date: {runDate ?? "no completed run yet"}.
        </div>
      </footer>
    </div>
  );
}

export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-border bg-muted/50 p-4 text-sm text-muted-foreground">
      {children}
    </div>
  );
}
