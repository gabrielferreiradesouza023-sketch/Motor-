import { sendCheckout, type CapiEnv } from "./capi.ts";
export interface Env extends CapiEnv {
  DB: D1Database;
  ALLOWED_ORIGIN: string;
  SALE_TOKEN?: string;
  SYNC_TOKEN?: string;
}

const identifier = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9:_-]{1,128}$/.test(value);
const timestamp = (value: unknown): value is string =>
  typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

export function validateEvent(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object") throw new Error("invalid event");
  const v = value as Record<string, unknown>;
  if (!identifier(v.id) || !identifier(v.ad_id) || !["view", "checkout_click"].includes(String(v.kind)) ||
    typeof v.geo !== "string" || !/^[A-Z]{2}$/.test(v.geo) || !timestamp(v.ts) ||
    Object.keys(v).some(k => !["id","ad_id","kind","geo","ts","test","event_id"].includes(k)) ||
    ("test" in v && v.test !== true) ||
    ("event_id" in v && (!identifier(v.event_id) || v.event_id !== v.id || v.kind !== "checkout_click"))) throw new Error("invalid event");
  return v;
}

export function validateSale(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object") throw new Error("invalid sale");
  const v = value as Record<string, unknown>;
  if (!identifier(v.id) || !identifier(v.hotmart_tx_id) || !timestamp(v.ts) ||
    !Number.isSafeInteger(v.commission_cents) || Number(v.commission_cents) < 0 ||
    !["approved", "refunded", "chargeback"].includes(String(v.status)) ||
    (v.tracking_param !== null && !identifier(v.tracking_param)) ||
    Object.keys(v).sort().join() !== "commission_cents,hotmart_tx_id,id,status,tracking_param,ts") {
    throw new Error("invalid sale");
  }
  return { ...v, source: "webhook", matched_entity_id: null };
}

async function equal(a: string, b: string): Promise<boolean> {
  const digest = async (s: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  const [x, y] = await Promise.all([digest(a), digest(b)]);
  let difference = 0;
  for (let i = 0; i < x.length; i++) difference |= x[i] ^ y[i];
  return difference === 0;
}

function json(body: unknown, status = 200, origin?: string): Response {
  return new Response(JSON.stringify(body), { status, headers: {
    "Content-Type": "application/json", "Cache-Control": "no-store",
    ...(origin ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" } : {})
  }});
}

export default {
  async fetch(request: Request, env: Env, ctx?: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    if (request.method === "OPTIONS" && url.pathname === "/event") {
      if (origin !== env.ALLOWED_ORIGIN) return json({ error: "origin" }, 403);
      return new Response(null, { status: 204, headers: {
        "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Content-Type",
        "Vary": "Origin"
      }});
    }
    if (request.method === "GET" && url.pathname === "/health") {
      await env.DB.prepare("SELECT COUNT(*) FROM events").first();
      return json({ status: "ok" });
    }
    if (request.method === "GET" && url.pathname === "/export") {
      if (!env.SYNC_TOKEN) return json({ error: "not configured" }, 503);
      if (!await equal(request.headers.get("Authorization") || "", "Bearer " + env.SYNC_TOKEN)) return json({ error: "auth" }, 401);
      const event = Number(url.searchParams.get("after_event") || 0);
      const sale = Number(url.searchParams.get("after_sale") || 0);
      const limit = Number(url.searchParams.get("limit") || 100);
      if (![event, sale].every(n => Number.isSafeInteger(n) && n >= 0) || !Number.isInteger(limit) || limit < 1 || limit > 500) return json({ error: "cursor" }, 400);
      const [events, sales] = await Promise.all([
        env.DB.prepare("SELECT seq,body FROM events WHERE seq>? ORDER BY seq LIMIT ?").bind(event, limit).all<{seq:number;body:string}>(),
        env.DB.prepare("SELECT seq,body FROM sales WHERE seq>? ORDER BY seq LIMIT ?").bind(sale, limit).all<{seq:number;body:string}>()
      ]);
      return json({ events: events.results.map(r => ({ cursor:r.seq, ...JSON.parse(r.body) })),
        sales: sales.results.map(r => ({ cursor:r.seq, ...JSON.parse(r.body) })),
        more: events.results.length === limit || sales.results.length === limit });
    }
    if (request.method !== "POST" || !["/event", "/sale"].includes(url.pathname)) return json({ error: "not found" }, 404);
    if (url.pathname === "/event" && origin !== env.ALLOWED_ORIGIN) return json({ error: "origin" }, 403);
    if (url.pathname === "/sale") {
      if (!env.SALE_TOKEN) return json({ error: "not configured" }, 503);
      if (!await equal(request.headers.get("X-Hotmart-Hottok") || "", env.SALE_TOKEN)) return json({ error: "auth" }, 401);
    }
    const key = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(request.headers.get("CF-Connecting-IP") || "local"));
    const keyText = Array.from(new Uint8Array(key), b => b.toString(16).padStart(2,"0")).join("");
    const bucket = Math.floor(Date.now()/60000);
    const row = await env.DB.prepare("INSERT INTO rate_buckets VALUES (?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET count=count+1 RETURNING count").bind(keyText,bucket).first<{count:number}>();
    await env.DB.prepare("DELETE FROM rate_buckets WHERE bucket<?").bind(bucket-2).run();
    if (row && row.count > 60) return json({ error: "rate limit" }, 429, origin || undefined);
    let value: Record<string, unknown>;
    try {
      const text = await request.text();
      if (text.length > 32000) return json({ error: "too large" }, 413);
      value = url.pathname === "/event" ? validateEvent(JSON.parse(text)) : validateSale(JSON.parse(text));
    } catch { return json({ error: "invalid payload" }, 400, origin || undefined); }
    const table = url.pathname === "/event" ? "events" : "sales";
    // Sales é uma sequência de eventos: refund tem novo id e o mesmo hotmart_tx_id.
    const inserted = await env.DB.prepare(`INSERT OR IGNORE INTO ${table}(id,body) VALUES (?,?)`).bind(value.id,JSON.stringify(value)).run();
    if (table === "events" && inserted.meta.changes === 1) {
      const delivery = sendCheckout(value, request, env);
      if (ctx) ctx.waitUntil(delivery); else await delivery;
    }
    return json({ status: "accepted" }, 202, origin || undefined);
  }
};
