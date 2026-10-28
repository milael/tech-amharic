import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createHandler, resetBundleCache } from "../src/handler.js";
import { proposalKey, validateProposal } from "../src/propose-core.js";

const root = new URL("../../", import.meta.url);
const fixtures = JSON.parse(readFileSync(new URL("tests/fixtures/retrieval_cases.json", root), "utf8"));
const ORIGIN = "https://milael.github.io";

function fakeKV() {
  const store = new Map();
  return {
    store,
    get: async (k, type) => (store.has(k) ? (type === "json" ? JSON.parse(store.get(k)) : store.get(k)) : null),
    put: async (k, v) => void store.set(k, v),
    list: async ({ prefix }) => ({ keys: [...store.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })), list_complete: true }),
  };
}

const env = (kv = fakeKV()) => ({
  ALLOWED_ORIGINS: ORIGIN,
  BUNDLE_URL: "x",
  INCLUDE_UNREVIEWED: "false", // proposals must still find unreviewed concepts
  SUGGESTIONS: kv,
  RATE_LIMITER: { limit: async () => ({ success: true }) },
});
const fakeFetch = async () => new Response(JSON.stringify({ schema: "tech-amharic-bundle/1", concepts: fixtures.concepts }));
const handler = () => createHandler("chat", fakeFetch, "suggest");
const post = (body, origin = ORIGIN) =>
  new Request("https://w.test/propose", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify(body) });
const call = async (body, e) => {
  const res = await handler().fetch(post(body), e);
  return { code: res.status, body: await res.json() };
};

test("proposal validation", () => {
  const p = validateProposal({ concept_id: "firewall", text: "  የእሳት   ግድግዳ ", note: "used at work", name: "Mili" });
  assert.equal(p.text, "የእሳት ግድግዳ");
  assert.equal(p.name, "Mili");
  for (const bad of [
    { concept_id: "firewall", text: "firewall" }, // Latin
    { concept_id: "firewall", text: "ሀ" }, // too short
    { concept_id: "firewall", text: "<b>ምስጠራ</b>" },
    { concept_id: "firewall", text: "ምስጠራ", note: "see https://spam.test" },
    { concept_id: "firewall", text: "ምስጠራ", formation: "invented" },
    { concept_id: "Bad Id", text: "ምስጠራ" },
    { text: "ምስጠራ" }, // no target
  ]) {
    assert.throws(() => validateProposal(bad), RangeError, JSON.stringify(bad));
  }
  // Folded spellings share a key, so variants count as the same proposal.
  assert.equal(proposalKey({ concept_id: "x", text: "ሐሳብ" }), proposalKey({ concept_id: "x", text: "ሀሳብ" }));
});

test("stores, counts repeats, lists for import and per concept", async () => {
  resetBundleCache();
  const kv = fakeKV();
  const e = env(kv);
  const first = await call({ concept_id: "firewall", text: "የእሳት መከላከያ ግድግዳ", name: "Abebe", note: "common at banks" }, e);
  assert.equal(first.body.status, "stored");
  const again = await call({ concept_id: "firewall", text: "የእሳት መከላከያ ግድግዳ" }, e);
  assert.equal(again.body.status, "counted");
  assert.equal(again.body.proposal.count, 2);

  const all = await (await handler().fetch(new Request("https://w.test/suggestions"), e)).json();
  assert.equal(all.proposals.length, 1);
  assert.equal(all.proposals[0].name, "Abebe");

  const card = await (await handler().fetch(new Request("https://w.test/proposals?concept=firewall"), e)).json();
  assert.deepEqual(Object.keys(card.proposals[0]).sort(), ["count", "created_at", "formation", "text"]);
});

test("existing terms, unknown concepts and foreign origins", async () => {
  resetBundleCache();
  const e = env();
  const fw = fixtures.concepts.find((c) => c.id === "firewall");
  const listed = fw.terms.find((t) => t.lang === "am").text;
  assert.equal((await call({ concept_id: "firewall", text: listed }, e)).body.status, "already_listed");
  assert.equal((await call({ concept_id: "no-such-thing", text: "ምስጠራ" }, e)).code, 404);
  assert.equal((await call({ term: "kubernetes", text: "ኩበርኔትስ" }, e)).code, 404); // no stored AI suggestion
  assert.equal((await handler().fetch(post({ concept_id: "firewall", text: "ምስጠራ" }, "https://evil.test"), e)).status, 403);
});

test("proposals for a stored AI suggestion", async () => {
  resetBundleCache();
  const kv = fakeKV();
  await kv.put("s:kubernetes", JSON.stringify({ term: "kubernetes", terms: [{ text: "ኩበርኔትስ" }], created_at: "2026-10-28" }));
  const e = env(kv);
  assert.equal((await call({ term: "Kubernetes", text: "ኩበርኔትስ" }, e)).body.status, "already_listed");
  assert.equal((await call({ term: "Kubernetes", text: "የኮንቴይነር አስተዳዳሪ" }, e)).body.status, "stored");
});

test("caps proposals per concept", async () => {
  resetBundleCache();
  const kv = fakeKV();
  for (let i = 0; i < 20; i++) await kv.put(`p:c:firewall:x${i}`, "{}");
  assert.equal((await call({ concept_id: "firewall", text: "አዲስ ቃል" }, env(kv))).code, 429);
});
