import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { validateEvent, validateSale } from "../src/index.ts";
import type { Env } from "../src/index.ts";

const event = { id:"test-id", kind:"view", ad_id:"ad1", geo:"CO", ts:"2026-10-05T12:00:00Z" };

test("event and sale strict payloads", () => {
  assert.deepEqual(validateEvent(event), event);
  assert.throws(() => validateEvent({ ...event, geo:"XX<script>" }));
  assert.throws(() => validateEvent({ ...event, extra:1 }));
  const sale = { id:"sale1", hotmart_tx_id:"tx1", ts:event.ts, commission_cents:5000,
    status:"approved", tracking_param:"ad1" };
  assert.equal(validateSale(sale).source, "webhook");
  assert.throws(() => validateSale({ ...sale, commission_cents:50.5 }));
});

test("wrong origin and absent sale secret denied before D1", async () => {
  const env = { ALLOWED_ORIGIN:"https://example.com" } as Env;
  assert.equal((await worker.fetch(new Request("https://worker.example/event", {
    method:"POST", headers:{Origin:"https://evil.example"} }), env)).status, 403);
  assert.equal((await worker.fetch(new Request("https://worker.example/sale", {method:"POST"}), env)).status, 503);
});

test("synthetic marker is explicit true; normal wire shape preserved", () => {
  assert.deepEqual(validateEvent(event), event);
  assert.deepEqual(validateEvent({ ...event, test:true }), { ...event, test:true });
  for (const test of [false, null, 1, "true"]) {
    assert.throws(() => validateEvent({ ...event, test }));
  }
  assert.throws(() => validateEvent({ ...event, test:true, extra:1 }));
});
