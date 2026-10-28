import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createHandler, resetBundleCache } from "../src/handler.js";
import { buildSuggestMessages, parseSuggestion, pickExamples, validateTerm } from "../src/suggest-core.js";

const root = new URL("../../", import.meta.url);
const fixtures = JSON.parse(readFileSync(new URL("tests/fixtures/retrieval_cases.json", root), "utf8"));
const CHAT = readFileSync(new URL("src/tech_amharic/chat_prompt.txt", root), "utf8");
const SUGGEST = readFileSync(new URL("src/tech_amharic/suggest_prompt.txt", root), "utf8");
const ORIGIN = "https://milael.github.io";

const GOOD = JSON.stringify({
  domain: "cloud-devops",
  definition_en: "An open-source system that runs and manages containers across many machines.",
  definition_am: "ኮንቴይነሮችን በብዙ ማሽኖች ላይ የሚያስተዳድር ክፍት ምንጭ ሥርዓት ነው።",
  terms: [
    { text: "ኩበርኔትስ", formation: "loan" },
    { text: "ኩበርኔትስ", formation: "loan" }, // duplicate dropped
    { text: "kubernetes", formation: "loan" }, // Latin script dropped
  ],
});

// ------------------------------------------------------------ pure logic

test("term validation", () => {
  assert.equal(validateTerm("  zero   trust "), "zero trust");
  assert.equal(validateTerm("C++"), "C++");
  for (const bad of ["", "a", "x".repeat(61), "ምስጠራ", "<script>"]) assert.throws(() => validateTerm(bad), RangeError);
});

test("parses model JSON, keeps only usable Amharic terms", () => {
  const s = parseSuggestion("<think>plan</think>```json\n" + GOOD + "\n```");
  assert.equal(s.domain, "cloud-devops");
  assert.deepEqual(s.terms, [{ text: "ኩበርኔትስ", formation: "loan" }]);
  assert.match(s.definition_am, /ሥርዓት/);
  assert.deepEqual(parseSuggestion('{"error":"not_a_tech_term"}'), { notTechTerm: true });
  assert.throws(() => parseSuggestion("no json here"));
  assert.throws(() => parseSuggestion('{"terms":[{"text":"latin only"}]}'));
  assert.equal(parseSuggestion('{"domain":"cooking","terms":[{"text":"ሀለ","formation":"made-up"}]}').domain, "general");
});

test("only approved terms become examples, related ones first", () => {
  const concepts = structuredClone(fixtures.concepts);
  assert.deepEqual(pickExamples(concepts, "encryption key"), []); // fixtures are all proposed
  const enc = concepts.find((c) => c.id === "encryption");
  enc.terms.find((t) => t.lang === "am").status = "preferred";
  const fw = concepts.find((c) => c.id === "firewall");
  fw.terms.find((t) => t.lang === "am").status = "admitted";
  const ex = pickExamples(concepts, "encryption key");
  assert.deepEqual(ex.map((e) => e.en), ["encryption", "firewall"]);
  assert.ok(ex.every((e) => e.am.every((t) => ["preferred", "admitted"].includes(t.status))));
  const msgs = buildSuggestMessages(SUGGEST, "encryption key", ex);
  assert.match(msgs[1].content, /ምስጠራ \(preferred/);
  assert.match(buildSuggestMessages(SUGGEST, "x", [])[1].content, /none yet/);
});

// ------------------------------------------------------------ endpoint

function fakeKV() {
  const store = new Map();
  return {
    store,
    get: async (k, type) => (store.has(k) ? (type === "json" ? JSON.parse(store.get(k)) : store.get(k)) : null),
    put: async (k, v) => void store.set(k, v),
    list: async ({ prefix }) => ({ keys: [...store.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })), list_complete: true }),
  };
}

function env(aiText, kv = fakeKV()) {
  const calls = [];
  return {
    calls,
    kv,
    env: {
      ALLOWED_ORIGINS: ORIGIN,
      BUNDLE_URL: "x",
      INCLUDE_UNREVIEWED: "true",
      SUGGESTIONS: kv,
      RATE_LIMITER: { limit: async () => ({ success: true }) },
      AI: { run: async (model, input) => (calls.push(input), { response: aiText }) },
    },
  };
}

const fakeFetch = async () => new Response(JSON.stringify({ schema: "tech-amharic-bundle/1", concepts: fixtures.concepts }));
const post = (term, origin = ORIGIN) =>
  new Request("https://w.test/suggest", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ term }) });
const handler = () => createHandler(CHAT, fakeFetch, SUGGEST);

test("generates, stores, then serves from cache without calling the model again", async () => {
  resetBundleCache();
  const e = env(GOOD);
  const first = await (await handler().fetch(post("Kubernetes"), e.env)).json();
  assert.equal(first.status, "generated");
  assert.equal(first.stored, true);
  assert.equal(first.suggestion.terms[0].text, "ኩበርኔትስ");
  assert.equal(first.suggestion.model, "@cf/google/gemma-4-26b-a4b-it");
  const second = await (await handler().fetch(post("kubernetes"), e.env)).json();
  assert.equal(second.status, "cached");
  assert.equal(e.calls.length, 1);
  const list = await (await handler().fetch(new Request("https://w.test/suggestions"), e.env)).json();
  assert.equal(list.count, 1);
});

test("existing glossary terms are not regenerated", async () => {
  resetBundleCache();
  const e = env(GOOD);
  const res = await (await handler().fetch(post("Encryption"), e.env)).json();
  assert.deepEqual(res, { status: "exists", concept_id: "encryption" });
  assert.equal(e.calls.length, 0);
});

test("non-technical input is remembered and hidden from the list", async () => {
  resetBundleCache();
  const e = env('{"error":"not_a_tech_term"}');
  assert.equal((await (await handler().fetch(post("banana bread"), e.env)).json()).status, "not_tech_term");
  assert.equal((await (await handler().fetch(post("banana bread"), e.env)).json()).status, "not_tech_term");
  assert.equal(e.calls.length, 1);
  const list = await (await handler().fetch(new Request("https://w.test/suggestions"), e.env)).json();
  assert.equal(list.count, 0);
});

test("unusable model output and foreign origins are rejected", async () => {
  resetBundleCache();
  assert.equal((await handler().fetch(post("kubernetes"), env("sorry, no").env)).status, 502);
  assert.equal((await handler().fetch(post("kubernetes", "https://evil.test"), env(GOOD).env)).status, 403);
  assert.equal((await handler().fetch(post("ምስጠራ"), env(GOOD).env)).status, 400);
});
