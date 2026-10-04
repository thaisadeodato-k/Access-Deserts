import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { SiteShell } from "@/components/SiteShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  adminStatus, adminLogin, adminLogout, runDiscovery, setSourceApproved, setCandidateApproved,
} from "@/lib/admin.functions";

export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { title: "Admin — Access Deserts" },
      { name: "description", content: "Administration of data sources and pipeline runs." },
      { property: "og:title", content: "Admin — Access Deserts" },
      { property: "og:description", content: "Administration area." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: AdminPage,
});

function AdminPage() {
  const status = useServerFn(adminStatus);
  const { data, refetch } = useQuery({ queryKey: ["admin-status"], queryFn: () => status() });
  return (
    <SiteShell>
      <section className="mx-auto max-w-7xl px-4 py-10">
        <h1 className="text-3xl font-semibold">Admin</h1>
        {data === undefined ? null : data.admin ? <AdminPanel onLogout={() => refetch()} /> : <Login onOk={() => refetch()} />}
      </section>
    </SiteShell>
  );
}

function Login({ onOk }: { onOk: () => void }) {
  const login = useServerFn(adminLogin);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="mt-6 flex max-w-sm flex-col gap-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        const r = await login({ data: { key } });
        setBusy(false);
        if (r.ok) onOk(); else toast.error(r.error);
      }}
    >
      <label htmlFor="k" className="text-sm">Admin key</label>
      <Input id="k" type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
      <Button type="submit" disabled={busy || !key}>Unlock</Button>
    </form>
  );
}

function AdminPanel({ onLogout }: { onLogout: () => void }) {
  const qc = useQueryClient();
  const logout = useServerFn(adminLogout);
  const discover = useServerFn(runDiscovery);
  const approveSrc = useServerFn(setSourceApproved);
  const approveCand = useServerFn(setCandidateApproved);
  const [busy, setBusy] = useState(false);

  const sources = useQuery({ queryKey: ["admin-sources"], queryFn: async () => (await supabase.from("sources").select("*").order("role").order("category")).data ?? [] });
  const cands = useQuery({ queryKey: ["admin-cands"], queryFn: async () => (await supabase.from("discovered_layers").select("*").order("layer_name")).data ?? [] });
  const logs = useQuery({ queryKey: ["admin-logs"], queryFn: async () => (await supabase.from("run_logs").select("*").order("created_at", { ascending: false }).limit(20)).data ?? [] });
  const refresh = () => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("admin-") && q.queryKey[0] !== "admin-status" });

  return (
    <div className="mt-6 space-y-10">
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={async () => {
          setBusy(true);
          const r = await discover({ data: { city_code: "sp" } });
          setBusy(false);
          if (r.ok) toast.success("Discovery completed"); else toast.error(`Discovery failed: ${r.error}`);
          refresh();
        }}>{busy ? "Running discovery…" : "Run GetCapabilities discovery (São Paulo)"}</Button>
        <Button variant="outline" onClick={async () => { await logout(); onLogout(); }}>Lock</Button>
      </div>

      <div>
        <h2 className="text-xl font-semibold">Sources</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground"><tr className="border-b border-border">
              <th className="py-2 pr-3">Layer</th><th className="pr-3">Name</th><th className="pr-3">Role</th><th className="pr-3">Category</th><th className="pr-3">In capabilities</th><th>Approved</th>
            </tr></thead>
            <tbody>
              {sources.data?.map((s) => (
                <tr key={s.source_id} className="border-b border-border">
                  <td className="py-2 pr-3 font-mono text-xs">{s.type_name}</td>
                  <td className="pr-3">{s.name}</td>
                  <td className="pr-3">{s.role}</td>
                  <td className="pr-3">{s.category ?? "—"}{s.subcategory ? ` / ${s.subcategory}` : ""}</td>
                  <td className="pr-3">{s.verified_in_capabilities === null ? "not checked" : s.verified_in_capabilities ? "yes" : "NOT FOUND"}</td>
                  <td><Switch aria-label={`Approve ${s.name}`} checked={s.approved} onCheckedChange={async (v) => { await approveSrc({ data: { source_id: s.source_id, approved: v } }); refresh(); }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold">Candidate layers (bus stops, terminals, train stations)</h2>
        <p className="mt-1 text-sm text-muted-foreground">Matched in layer name/title by: ponto, parada, onibus, terminal, trem, cptm, estacao. Not used until approved and mapped to a source.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground"><tr className="border-b border-border">
              <th className="py-2 pr-3">Layer</th><th className="pr-3">Title</th><th className="pr-3">Matched</th><th className="pr-3">Features</th><th>Approved</th>
            </tr></thead>
            <tbody>
              {cands.data?.length === 0 && <tr><td colSpan={5} className="py-3 text-muted-foreground">Run discovery to list candidates.</td></tr>}
              {cands.data?.map((c) => (
                <tr key={c.id} className="border-b border-border">
                  <td className="py-2 pr-3 font-mono text-xs">{c.layer_name}</td>
                  <td className="pr-3">{c.title}</td>
                  <td className="pr-3 text-xs">{c.matched_terms.join(", ")}</td>
                  <td className="pr-3">{c.feature_count ?? <span className="text-destructive">{c.count_error}</span>}</td>
                  <td><Switch aria-label={`Approve ${c.layer_name}`} checked={c.approved} onCheckedChange={async (v) => { await approveCand({ data: { id: c.id, approved: v } }); refresh(); }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold">Recent logs</h2>
        <ul className="mt-3 space-y-1 font-mono text-xs">
          {logs.data?.map((l) => (
            <li key={l.id}><span className={l.level === "error" ? "text-destructive" : l.level === "warning" ? "text-accent" : "text-muted-foreground"}>[{l.level}]</span> {new Date(l.created_at).toISOString()} {l.message}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
