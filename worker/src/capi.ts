/** Optional measurement only. No CAPI credentials or version defaults. */
export interface CapiEnv {
  CAPI_ENABLED?: string;
  CAPI_TOKEN?: string;
  PIXEL_ID?: string;
  GRAPH_VERSION?: string;
  ALLOWED_ORIGIN: string;
}
export async function sendCheckout(event: Record<string, unknown>, request: Request,
  env: CapiEnv, transport: typeof fetch = fetch): Promise<boolean> {
  if (env.CAPI_ENABLED !== "true" || !env.CAPI_TOKEN || !env.PIXEL_ID || !env.GRAPH_VERSION) return false;
  if (!/^\d+$/.test(env.PIXEL_ID) || !/^v\d+\.\d+$/.test(env.GRAPH_VERSION)) return false;
  if (event.kind !== "checkout_click" || event.test === true || typeof event.event_id !== "string" ||
    event.event_id !== event.id || !/^[A-Za-z0-9:_-]{1,128}$/.test(event.event_id)) return false;
  const time = Date.parse(String(event.ts));
  const ip = request.headers.get("CF-Connecting-IP");
  const agent = request.headers.get("User-Agent");
  if (!Number.isFinite(time) || !ip || !agent) return false;
  try {
    const source = new URL(request.headers.get("Referer") || env.ALLOWED_ORIGIN);
    if (source.origin !== new URL(env.ALLOWED_ORIGIN).origin || !["http:","https:"].includes(source.protocol)) return false;
    source.search = ""; source.hash = ""; source.username = ""; source.password = "";
    const response = await transport(`https://graph.facebook.com/${env.GRAPH_VERSION}/${env.PIXEL_ID}/events`, {
      method: "POST", headers: { "Content-Type":"application/json", Authorization:`Bearer ${env.CAPI_TOKEN}` },
      signal: AbortSignal.timeout(2000), body: JSON.stringify({ data:[{
        event_name:"InitiateCheckout", event_id:event.event_id, event_time:Math.floor(time/1000),
        action_source:"website", event_source_url:source.toString(),
        user_data:{ client_ip_address:ip, client_user_agent:agent }
      }] })
    });
    return response.ok;
  } catch { return false; }
}
