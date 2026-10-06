import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import assert from 'node:assert/strict';
const [file, ad] = process.argv.slice(2);
const source = fs.readFileSync(file, 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const pending = [];
let clicked, target;
const node = { parentNode: { insertBefore() {} } };
const context = {
  URL, URLSearchParams, crypto: webcrypto,
  location: { search: '?ad='+ad+'&geo=CO', assign(value) {target=value;} },
  document: {
    createElement() {return {};}, getElementsByTagName() {return [node];},
    getElementById() { return {addEventListener(_event, callback) {clicked=callback;}}; }
  },
  fetch(url, options) {
    const promise = fetch(url, {...options, headers:{...options.headers, Origin:'http://127.0.0.1:8000'}})
      .then(response => {assert.equal(response.status, 202);return response;});
    pending.push(promise);return promise;
  }
};
context.window = context;
vm.runInNewContext(source, context);
clicked();
await Promise.all(pending);
assert.equal(new URL(target).searchParams.get('sck'), ad);
assert.ok(context.fbq.queue.some(args => args[1] === 'InitiateCheckout'));
assert.equal(pending.length, 2);
console.log('Ponte JS OK: visita, CTA, InitiateCheckout e parâmetro no redirecionamento');
