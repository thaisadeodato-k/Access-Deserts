import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { SiteShell, Placeholder } from "@/components/SiteShell";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Access Deserts — São Paulo" },
      { name: "description", content: "Where population density and social vulnerability coincide with poor access to public services in São Paulo, with data reliability shown." },
      { property: "og:title", content: "Access Deserts — São Paulo" },
      { property: "og:description", content: "Spatial analysis of access to essential public services, built on open public data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MapPage,
});

function MapPage() {
  const { data: sources } = useQuery({
    queryKey: ["sources-count"],
    queryFn: async () => {
      const { data } = await supabase.from("sources").select("source_id, approved, role");
      return data ?? [];
    },
  });
  const approved = sources?.filter((s) => s.approved).length ?? 0;
  return (
    <SiteShell>
      <section className="mx-auto max-w-7xl px-4 py-10">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">Live data – no completed run yet</p>
        <h1 className="mt-2 text-3xl font-semibold">Map</h1>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          The map will appear once the first data run completes (Phase 2). Sources configured: {sources?.length ?? "…"}; approved
          for use: {approved}.
        </p>
        <div className="mt-6"><Placeholder>Map not yet available.</Placeholder></div>
      </section>
    </SiteShell>
  );
}
