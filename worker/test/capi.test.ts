import { test } from "node:test";
import assert from "node:assert/strict";
import { sendCheckout, type CapiEnv } from "../src/capi.ts";
import worker, { validateEvent, type Env } from "../src/index.ts";
const event = {id:"click1",event_id:"click1",kind:"checkout_click",ad_id:"ad1",geo:"CO",ts:"2026-10-05T12:00:00Z"};
const env: CapiEnv = { CAPI_ENABLED:"true",CAPI_TOKEN:"synthetic-only",PIXEL_ID:"123",GRAPH_VERSION:"v99.0",ALLOWED_ORIGIN:"https://example.com" };
const request = (headers: Record<string,string> = {}) => new Request("https://worker.example/event",{method:"POST",headers:{Origin:env.ALLOWED_ORIGIN,"CF-Connecting-IP":"192.0.2.1","User-Agent":"synthetic-agent",Referer:"https://example.com/bridge?private=query#secret",...headers},body:JSON.stringify(event)});
const forbidden = (async () => { throw new Error("unexpected network"); }) as typeof fetch;
test("CAPI disabled, incomplete or invalid config never calls transport", async () => {
  for (const patch of [{CAPI_ENABLED:"false"},{CAPI_ENABLED:undefined},{CAPI_TOKEN:undefined},{PIXEL_ID:undefined},{GRAPH_VERSION:undefined},{PIXEL_ID:"abc"},{GRAPH_VERSION:"invented"}])
    assert.equal(await sendCheckout(event,request(),{...env,...patch},forbidden),false);
});
test("old bodies, synthetic events and invalid IDs are not sent", async () => {
  for(const patch of [{kind:"view"},{test:true},{event_id:undefined},{event_id:12},{event_id:"other"},{id:"bad!",event_id:"bad!"},{ts:"invalid"}])
    assert.equal(await sendCheckout({...event,...patch},request(),env,forbidden),false);
  for (const headers of [{"CF-Connecting-IP":""},{"User-Agent":""},{Referer:"https://evil.example"},{Referer:"invalid"}])
    assert.equal(await sendCheckout(event,request(headers as unknown as Record<string,string>),env,forbidden),false);
});
test("payload matches independent reference and removes query personal data", async () => {
  let calls=0;
  const mock = (async (url: unknown, init: RequestInit) => {
    calls++;
    assert.equal(url,"https://graph.facebook.com/v99.0/123/events");
    assert.deepEqual(JSON.parse(String(init.body)),{data:[{event_name:"InitiateCheckout",event_id:"click1",event_time:1791201600,action_source:"website",event_source_url:"https://example.com/bridge",user_data:{client_ip_address:"192.0.2.1",client_user_agent:"synthetic-agent"}}]});
    assert.ok(init.signal);
    return new Response("{}",{status:200});
  }) as typeof fetch;
  assert.equal(await sendCheckout(event,request(),env,mock),true); assert.equal(calls,1);
  assert.equal(await sendCheckout(event,request({Referer:""}),env,(async()=>new Response()) as typeof fetch),true);
  assert.equal(await sendCheckout(event,request(),{...env,ALLOWED_ORIGIN:"mailto:x"},forbidden),false);
});
for (const status of [400,500]) test(`HTTP ${status} returns false`, async()=>{
  assert.equal(await sendCheckout(event,request(),env,(async()=>new Response("",{status})) as typeof fetch),false);
});
test("timeout remains a failed measurement",async()=>{
  assert.equal(await sendCheckout(event,request(),env,(async()=>{throw new DOMException("timeout","TimeoutError");}) as typeof fetch),false);
});
test("strict optional nonce retains old payload compatibility",()=>{
  const {event_id,...old}=event;
  assert.deepEqual(validateEvent(old),old);
  assert.deepEqual(validateEvent(event),event);
  for(const patch of [{event_id:"other"},{event_id:12},{event_id:"click1",kind:"view"},{extra:1}]) assert.throws(()=>validateEvent({...event,...patch}));
});
test("D1 persists first, replay sends once, HTTP and timeout failures preserve 202",async(t)=>{
  let stored=false, calls=0;
  const DB={prepare(sql: string){return {bind(){return this;},async first(){return {count:1};},async run(){if(sql.startsWith("INSERT OR IGNORE")){const changes=stored?0:1;stored=true;return {meta:{changes}};}return {meta:{changes:1}};}};}} as unknown as D1Database;
  t.mock.method(globalThis,"fetch",async()=>{assert.equal(stored,true);calls++;return new Response("",{status:500});});
  assert.equal((await worker.fetch(request(),{...env,DB} as Env)).status,202);
  assert.equal((await worker.fetch(request(),{...env,DB} as Env)).status,202);
  assert.equal(calls,1);
  stored=false; t.mock.method(globalThis,"fetch",async()=>{throw new DOMException("timeout","TimeoutError");});
  assert.equal((await worker.fetch(request(),{...env,DB} as Env)).status,202);
  assert.equal(stored,true);
  stored=false;
  const promises: Promise<unknown>[]=[];
  assert.equal((await worker.fetch(request(),{...env,DB} as Env,{waitUntil(p:Promise<unknown>){promises.push(p);}} as ExecutionContext)).status,202);
  await Promise.all(promises);
});
