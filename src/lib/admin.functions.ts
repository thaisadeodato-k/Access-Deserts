import { createServerFn } from "@tanstack/react-start";
import { getCookie, setCookie, deleteCookie } from "@tanstack/react-start/server";
import { z } from "zod";

const COOKIE = "ad_admin";
const TERMS = ["ponto", "parada", "onibus", "terminal", "trem", "cptm", "estacao"];

async function tokenFor(key: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`access-deserts-admin:${key}`));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
function safeEq(a: string, b: string) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
async function isAdmin() {
  const key = process.env["ADMIN_KEY"];
  if (!key) return false;
  const c = getCookie(COOKIE);
  return !!c && safeEq(c, await tokenFor(key));
}
async function requireAdmin() {
  if (!(await isAdmin())) throw new Error("Unauthorized");
}
function normalise(s: string) {
  return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}
async function fetchText(url: string, ms = 30000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.text();
  } finally {
    clearTimeout(t);
  }
}

export const adminStatus = createServerFn({ method: "GET" }).handler(async () => ({ admin: await isAdmin() }));

export const adminLogin = createServerFn({ method: "POST" })
  .inputValidator((d) => z.object({ key: z.string().min(1).max(500) }).parse(d))
  .handler(async ({ data }) => {
    const key = process.env["ADMIN_KEY"];
    if (!key) return { ok: false, error: "Admin key is not configured." };
    const ok = safeEq(await tokenFor(data.key), await tokenFor(key));
    if (!ok) return { ok: false, error: "Invalid key." };
    setCookie(COOKIE, await tokenFor(key), { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 8 });
    return { ok: true };
  });

export const adminLogout = createServerFn({ method: "POST" }).handler(async () => {
  deleteCookie(COOKIE, { path: "/" });
  return { ok: true };
});

export const setSourceApproved = createServerFn({ method: "POST" })
  .inputValidator((d) => z.object({ source_id: z.string(), approved: z.boolean() }).parse(d))
  .handler(async ({ data }) => {
    await requireAdmin();
    const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
    const { error } = await supabaseAdmin.from("sources").update({ approved: data.approved, updated_at: new Date().toISOString() }).eq("source_id", data.source_id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export const setCandidateApproved = createServerFn({ method: "POST" })
  .inputValidator((d) => z.object({ id: z.string().uuid(), approved: z.boolean() }).parse(d))
  .handler(async ({ data }) => {
    await requireAdmin();
    const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
    const { error } = await supabaseAdmin.from("discovered_layers").update({ approved: data.approved }).eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

/** GetCapabilities discovery: verifies seeded layers and lists transit candidates. */
export const runDiscovery = createServerFn({ method: "POST" })
  .inputValidator((d) => z.object({ city_code: z.string() }).parse(d))
  .handler(async ({ data }) => {
    await requireAdmin();
    const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
    const { data: srcs, error } = await supabaseAdmin.from("sources").select("*").eq("city_code", data.city_code).eq("protocol", "wfs");
    if (error) throw new Error(error.message);
    const endpoints = [...new Set((srcs ?? []).map((s) => s.endpoint_url))];

    const { data: run } = await supabaseAdmin.from("runs").insert({ city_code: data.city_code, step: "discovery" }).select().single();
    const runId = run!.run_id;
    const log = (level: string, message: string, source_id: string | null = null, details: unknown = null) =>
      supabaseAdmin.from("run_logs").insert({ run_id: runId, city_code: data.city_code, source_id, level, message, details: details as never });

    const summary: Record<string, unknown> = {};
    try {
      for (const ep of endpoints) {
        const capsUrl = `${ep}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities`;
        const xml = await fetchText(capsUrl, 45000);
        const blocks = xml.match(/<(?:wfs:)?FeatureType>[\s\S]*?<\/(?:wfs:)?FeatureType>/g) ?? [];
        const layers = blocks.map((b) => ({
          name: (b.match(/<(?:wfs:)?Name>([^<]*)<\/(?:wfs:)?Name>/) ?? [])[1] ?? "",
          title: (b.match(/<(?:wfs:)?Title>([^<]*)<\/(?:wfs:)?Title>/) ?? [])[1] ?? "",
        })).filter((l) => l.name);
        const names = new Set(layers.map((l) => l.name));
        const now = new Date().toISOString();

        const missing: string[] = [];
        for (const s of (srcs ?? []).filter((x) => x.endpoint_url === ep)) {
          const ok = names.has(s.type_name ?? "");
          if (!ok) missing.push(s.type_name ?? s.source_id);
          await supabaseAdmin.from("sources").update({ verified_in_capabilities: ok, verified_at: now }).eq("source_id", s.source_id);
        }

        const prodam = [...new Set(xml.match(/[a-z0-9.-]*prodam[a-z0-9.-]*/gi) ?? [])];
        if (prodam.length) await log("warning", "Internal-only hostnames (*.prodam) found in capabilities metadata; ignored.", null, { hosts: prodam });

        const candidates = layers
          .map((l) => ({ ...l, matched: TERMS.filter((t) => normalise(`${l.name} ${l.title}`).includes(t)) }))
          .filter((l) => l.matched.length);

        // feature counts, limited concurrency
        const counted: { name: string; title: string; matched: string[]; count: number | null; err: string | null }[] = [];
        let i = 0;
        await Promise.all(Array.from({ length: 6 }, async () => {
          while (i < candidates.length) {
            const c = candidates[i++];
            try {
              const x = await fetchText(`${ep}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=${encodeURIComponent(c.name)}&RESULTTYPE=hits`, 20000);
              const m = x.match(/numberMatched="(\d+)"/);
              counted.push({ ...c, count: m ? Number(m[1]) : null, err: m ? null : "numberMatched not reported" });
            } catch (e) {
              counted.push({ ...c, count: null, err: (e as Error).message });
            }
          }
        }));

        for (const c of counted) {
          await supabaseAdmin.from("discovered_layers").upsert({
            city_code: data.city_code, endpoint_url: ep, layer_name: c.name, title: c.title,
            matched_terms: c.matched, feature_count: c.count, count_error: c.err, discovered_at: now,
          }, { onConflict: "city_code,layer_name", ignoreDuplicates: false });
        }
        summary[ep] = { layers_in_capabilities: layers.length, seeded_missing: missing, candidates: counted.length, prodam_hosts: prodam.length };
        await log("info", `Capabilities: ${layers.length} layers; ${missing.length} seeded layers missing; ${counted.length} candidates.`, null, summary[ep]);
      }
      await supabaseAdmin.from("runs").update({ status: "completed", summary: summary as never, finished_at: new Date().toISOString() }).eq("run_id", runId);
      return { ok: true, summary };
    } catch (e) {
      await log("error", `Discovery failed: ${(e as Error).message}`);
      await supabaseAdmin.from("runs").update({ status: "failed", finished_at: new Date().toISOString() }).eq("run_id", runId);
      return { ok: false, error: (e as Error).message };
    }
  });
