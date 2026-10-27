import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { checkAnswer, cleanAnswer, cleanHistory, retrieve, termbaseBlock } from "../src/chat-core.js";
import { createHandler, resetBundleCache } from "../src/handler.js";
import { normKey } from "../src/normalize.js";

const root = new URL("../../", import.meta.url);
const fixtures = JSON.parse(readFileSync(new URL("tests/fixtures/retrieval_cases.json", root), "utf8"));
const PROMPT = readFileSync(new URL("src/tech_amharic/chat_prompt.txt", root), "utf8");
const ORIGIN = "https://milael.github.io";

// ------------------------------------------------------------ parity with Python

for (const c of fixtures.cases) {
  test(`retrieval matches Python: ${c.question}`, () => {
    assert.deepEqual(retrieve(fixtures.concepts, c.question).map((x) => x.id), c.expected);
  });
}

test("normKey folds homophones like Python", () => {
  assert.equal(normKey("ምሥጠራ"), normKey("ምስጠራ"));
  assert.equal(normKey("ሐሳብ"), normKey("ሀሳብ"));
  assert.equal(normKey("ድረ-ገጽ"), normKey("ድረ ገጽ"));
  assert.notEqual(normKey("ሰ"), normKey("ሸ"));
});

test("termbase block, history and answer checks", () => {
  const enc = fixtures.concepts.find((c) => c.id === "encryption");
  assert.match(termbaseBlock([enc]), /ምስጠራ \[proposed\]/);
  assert.match(termbaseBlock([]), /no matching entries/);
  const hist = cleanHistory([{ role: "system", content: "x" }, { role: "user", content: "hi" }]);
  assert.deepEqual(hist, [{ role: "user", content: "hi" }]);
  assert.equal(cleanAnswer("<think>x</think> ሀ"), "ሀ");
  assert.deepEqual(checkAnswer("ምሥጠራ ነው", [enc]).terms_used, ["encryption"]);
});

// ------------------------------------------------------------ request handling

function makeEnv({ aiResult, aiError, allow = true } = {}) {
  const calls = [];
  return {
    calls,
    env: {
      ALLOWED_ORIGINS: ORIGIN,
      BUNDLE_URL: "https://example.test/bundle.json",
      INCLUDE_UNREVIEWED: "true",
      RATE_LIMITER: { limit: async () => ({ success: allow }) },
      AI: {
        run: async (model, input) => {
          calls.push({ model, input });
          if (aiError) throw aiError;
          return aiResult ?? { response: "ምስጠራ (encryption) መረጃን ይጠብቃል።" };
        },
      },
    },
  };
}

const fakeFetch = async () =>
  new Response(JSON.stringify({ schema: "tech-amharic-bundle/1", concepts: fixtures.concepts }), { status: 200 });

function post(body, origin = ORIGIN) {
  return new Request("https://worker.test/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin, "CF-Connecting-IP": "1.2.3.4" },
    body: JSON.stringify(body),
  });
}

test("answers with sources and checks", async () => {
  resetBundleCache();
  const { env, calls } = makeEnv();
  const res = await createHandler(PROMPT, fakeFetch).fetch(post({ question: "ምስጠራ ምንድን ነው?" }), env);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const body = await res.json();
  assert.equal(body.concepts[0].id, "encryption");
  assert.deepEqual(body.checks.terms_used, ["encryption"]);
  assert.equal(calls[0].model, "@cf/google/gemma-4-26b-a4b-it");
  assert.match(calls[0].input.messages[1].content, /^TERMBASE/);
});

test("accepts OpenAI-style model output", async () => {
  resetBundleCache();
  const { env } = makeEnv({ aiResult: { choices: [{ message: { content: "ሀርድዌር ነው።" } }] } });
  const res = await createHandler(PROMPT, fakeFetch).fetch(post({ question: "What is hardware?" }), env);
  assert.equal((await res.json()).answer, "ሀርድዌር ነው።");
});

test("rejects other origins, bad input and rate-limited visitors", async () => {
  resetBundleCache();
  const h = createHandler(PROMPT, fakeFetch);
  assert.equal((await h.fetch(post({ question: "x" }, "https://evil.test"), makeEnv().env)).status, 403);
  assert.equal((await h.fetch(post({ question: "" }), makeEnv().env)).status, 400);
  assert.equal((await h.fetch(post({ question: "a".repeat(501) }), makeEnv().env)).status, 400);
  assert.equal((await h.fetch(post({ question: "What is AI?" }), makeEnv({ allow: false }).env)).status, 429);
});

test("explains the daily free limit instead of failing silently", async () => {
  resetBundleCache();
  const { env } = makeEnv({ aiError: new Error("4006: you have used up your daily free allocation of 10,000 neurons") });
  const res = await createHandler(PROMPT, fakeFetch).fetch(post({ question: "What is AI?" }), env);
  assert.equal(res.status, 429);
  assert.equal((await res.json()).error, "daily_limit");
});

test("preflight and health", async () => {
  const h = createHandler(PROMPT, fakeFetch);
  const pre = await h.fetch(new Request("https://worker.test/chat", { method: "OPTIONS", headers: { Origin: ORIGIN } }), makeEnv().env);
  assert.equal(pre.status, 204);
  const health = await h.fetch(new Request("https://worker.test/health"), makeEnv().env);
  assert.equal((await health.json()).ok, true);
});

test("joins content parts and explains empty answers", async () => {
  resetBundleCache();
  const parts = makeEnv({ aiResult: { choices: [{ message: { content: [{ type: "text", text: "ሀ" }, { type: "text", text: "ለ" }] } }] } });
  const ok = await createHandler(PROMPT, fakeFetch).fetch(post({ question: "What is AI?" }), parts.env);
  assert.equal((await ok.json()).answer, "ሀለ");
  const empty = makeEnv({ aiResult: { choices: [{ finish_reason: "length", message: { content: null, reasoning_content: "long hidden plan" } }] } });
  const res = await createHandler(PROMPT, fakeFetch).fetch(post({ question: "What is AI?" }), empty.env);
  const body = await res.json();
  assert.equal(res.status, 502);
  assert.equal(body.shape.finish_reason, "length");
  assert.equal(body.shape.reasoning_chars, 16);
  assert.ok(!JSON.stringify(body).includes("long hidden plan"));
});
