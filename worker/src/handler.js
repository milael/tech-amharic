// Request handling for the Tech-Amharic chat Worker (see index.js).
//
// The public demo (GitHub Pages) posts questions here. The Worker finds the
// relevant concepts in the published termbase bundle, asks Gemma 4 on
// Workers AI to answer in Amharic using those terms, and returns the answer
// with its sources. No API key ever reaches the browser.
//
// Free-plan safety: Workers AI stops answering when the 10,000 daily
// neurons are used up (no charges), and a per-visitor rate limit keeps one
// visitor from using the whole allowance.

import {
  buildMessages,
  checkAnswer,
  cleanAnswer,
  conceptSummary,
  retrieve,
  validateQuestion,
} from "./chat-core.js";

const DEFAULT_MODEL = "@cf/google/gemma-4-26b-a4b-it";
const BUNDLE_TTL_MS = 10 * 60 * 1000;
const MAX_BODY_BYTES = 16_000;
const PUBLISHED = new Set(["preferred", "admitted", "deprecated"]);

let bundleCache = { at: 0, concepts: null };

function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const headers = { Vary: "Origin", "X-Content-Type-Options": "nosniff" };
  if (origin && allowed.includes(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
    headers["Access-Control-Allow-Headers"] = "Content-Type";
    headers["Access-Control-Max-Age"] = "86400";
  }
  return { headers, allowed: Boolean(headers["Access-Control-Allow-Origin"]) };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function loadConcepts(env, fetchImpl) {
  const now = Date.now();
  if (bundleCache.concepts && now - bundleCache.at < BUNDLE_TTL_MS) return bundleCache.concepts;
  const res = await fetchImpl(env.BUNDLE_URL, { cf: { cacheTtl: 600, cacheEverything: true } });
  if (!res.ok) throw new Error(`bundle HTTP ${res.status}`);
  const bundle = await res.json();
  const includeUnreviewed = env.INCLUDE_UNREVIEWED === "true";
  const concepts = bundle.concepts
    .map((c) => ({ ...c, terms: includeUnreviewed ? c.terms : c.terms.filter((t) => t.lang === "en" || PUBLISHED.has(t.status)) }))
    .filter((c) => c.terms.some((t) => t.lang === "am"));
  bundleCache = { at: now, concepts };
  return concepts;
}

function modelText(out) {
  if (typeof out === "string") return out;
  if (typeof out?.response === "string") return out.response;
  return out?.choices?.[0]?.message?.content ?? "";
}

const isQuotaError = (err) => /4006|neuron|daily|allocation|quota/i.test(String(err?.message || err));

export function createHandler(SYSTEM_PROMPT, fetchImpl = fetch) {
  return {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    const { headers, allowed } = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: allowed ? 204 : 403, headers });
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({ ok: true, model: env.MODEL || DEFAULT_MODEL }, 200, headers);
    }
    if (url.pathname !== "/chat" || request.method !== "POST") {
      return json({ error: "not_found", detail: "Use POST /chat." }, 404, headers);
    }
    if (!allowed) return json({ error: "forbidden_origin", detail: "This site may not use the chat." }, 403, headers);
    if (Number(request.headers.get("Content-Length") || 0) > MAX_BODY_BYTES) {
      return json({ error: "too_large", detail: "Request body too large." }, 413, headers);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    if (env.RATE_LIMITER) {
      const { success } = await env.RATE_LIMITER.limit({ key: `chat:${ip}` });
      if (!success) {
        return json({ error: "rate_limited", detail: "Too many questions. Wait a minute and try again." }, 429, headers);
      }
    }

    let question;
    let history;
    try {
      const body = await request.json();
      question = validateQuestion(body?.question);
      history = body?.history;
    } catch (err) {
      const detail = err instanceof RangeError ? err.message : "Send JSON like {\"question\": \"...\"}.";
      return json({ error: "bad_request", detail }, 400, headers);
    }

    let concepts;
    try {
      concepts = await loadConcepts(env, fetchImpl);
    } catch (err) {
      console.error("bundle load failed", String(err));
      return json({ error: "termbase_unavailable", detail: "The termbase could not be loaded. Try again shortly." }, 503, headers);
    }

    const found = retrieve(concepts, question);
    const messages = buildMessages(SYSTEM_PROMPT, question, found, history);
    const model = env.MODEL || DEFAULT_MODEL;
    let answer;
    try {
      const out = await env.AI.run(model, { messages, max_tokens: 700, temperature: 0.3 });
      answer = cleanAnswer(modelText(out));
    } catch (err) {
      if (isQuotaError(err)) {
        return json(
          { error: "daily_limit", detail: "የዛሬው ነፃ የጥያቄ ገደብ ተሞልቷል። ነገ እንደገና ይሞክሩ። (Today's free limit is used up. Try again tomorrow.)" },
          429,
          headers,
        );
      }
      console.error("model call failed", String(err));
      return json({ error: "model_error", detail: "The language model did not answer. Try again shortly." }, 502, headers);
    }
    if (!answer) return json({ error: "empty_answer", detail: "The model returned no answer. Try rephrasing." }, 502, headers);

    return json(
      { answer, concepts: found.map(conceptSummary), checks: checkAnswer(answer, found), model },
      200,
      headers,
    );
  },
};
}

export function resetBundleCache() {
  bundleCache = { at: 0, concepts: null };
}
