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
import {
  buildSuggestMessages,
  findExisting,
  parseSuggestion,
  pickExamples,
  storageKey,
  validateTerm,
} from "./suggest-core.js";
import { MAX_PER_TARGET, alreadyListed, proposalKey, resolveTarget, targetKey, validateProposal } from "./propose-core.js";

const DEFAULT_MODEL = "@cf/google/gemma-4-26b-a4b-it";
const BUNDLE_TTL_MS = 10 * 60 * 1000;
const MAX_BODY_BYTES = 16_000;
const PUBLISHED = new Set(["preferred", "admitted", "deprecated"]);

let bundleCache = { at: 0, concepts: null, all: null };

function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const headers = { Vary: "Origin", "X-Content-Type-Options": "nosniff" };
  if (origin && allowed.includes(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
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

async function loadConcepts(env, fetchImpl, { all = false } = {}) {
  const now = Date.now();
  if (bundleCache.concepts && now - bundleCache.at < BUNDLE_TTL_MS) return all ? bundleCache.all : bundleCache.concepts;
  const res = await fetchImpl(env.BUNDLE_URL, { cf: { cacheTtl: 600, cacheEverything: true } });
  if (!res.ok) throw new Error(`bundle HTTP ${res.status}`);
  const bundle = await res.json();
  const includeUnreviewed = env.INCLUDE_UNREVIEWED === "true";
  const concepts = bundle.concepts
    .map((c) => ({ ...c, terms: includeUnreviewed ? c.terms : c.terms.filter((t) => t.lang === "en" || PUBLISHED.has(t.status)) }))
    .filter((c) => c.terms.some((t) => t.lang === "am"));
  bundleCache = { at: now, concepts, all: bundle.concepts };
  return all ? bundle.concepts : concepts;
}

function partsText(content) {
  // Some models return content as [{type: "text", text: "..."}, ...].
  if (Array.isArray(content)) return content.map((p) => (typeof p === "string" ? p : p?.text ?? "")).join("");
  return typeof content === "string" ? content : "";
}

function modelText(out) {
  if (typeof out === "string") return out;
  if (typeof out?.response === "string") return out.response;
  return partsText(out?.choices?.[0]?.message?.content);
}

// Field names, sizes and finish reason only (never content), to diagnose an
// empty answer without exposing the model's reasoning.
function outputShape(out) {
  const choice = out?.choices?.[0];
  const message = choice?.message || {};
  return {
    keys: out && typeof out === "object" ? Object.keys(out) : typeof out,
    message_keys: Object.keys(message),
    finish_reason: choice?.finish_reason ?? out?.finish_reason ?? null,
    content_chars: partsText(message.content).length,
    reasoning_chars: String(message.reasoning_content ?? message.reasoning ?? "").length,
    usage: out?.usage ?? null,
  };
}

const isQuotaError = (err) => /4006|neuron|daily|allocation|quota/i.test(String(err?.message || err));

const DAILY_LIMIT_DETAIL =
  "የዛሬው ነፃ የጥያቄ ገደብ ተሞልቷል። ነገ እንደገና ይሞክሩ። (Today's free limit is used up. Try again tomorrow.)";

async function listKV(env, prefix, keep = () => true) {
  const out = [];
  let cursor;
  do {
    const page = await env.SUGGESTIONS.list({ prefix, cursor });
    for (const k of page.keys) {
      const value = await env.SUGGESTIONS.get(k.name, "json");
      if (value && keep(value)) out.push(value);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out.sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
}

const listSuggestions = (env) => listKV(env, "s:", (v) => !v.notTechTerm);
const listProposals = (env, prefix = "p:") => listKV(env, prefix);

export function createHandler(SYSTEM_PROMPT, fetchImpl = fetch, SUGGEST_PROMPT = "") {
  async function suggest(request, env, headers) {
    let term;
    try {
      term = validateTerm((await request.json())?.term);
    } catch (err) {
      const detail = err instanceof RangeError ? err.message : 'Send JSON like {"term": "kubernetes"}.';
      return json({ error: "bad_request", detail }, 400, headers);
    }
    let concepts;
    try {
      concepts = await loadConcepts(env, fetchImpl);
    } catch (err) {
      console.error("bundle load failed", String(err));
      return json({ error: "termbase_unavailable", detail: "The glossary could not be loaded. Try again shortly." }, 503, headers);
    }
    const existing = findExisting(concepts, term);
    if (existing) return json({ status: "exists", concept_id: existing.id }, 200, headers);

    const key = storageKey(term);
    const cached = env.SUGGESTIONS ? await env.SUGGESTIONS.get(key, "json") : null;
    if (cached) return json({ status: cached.notTechTerm ? "not_tech_term" : "cached", suggestion: cached }, 200, headers);

    const examples = pickExamples(concepts, term);
    const model = env.MODEL || DEFAULT_MODEL;
    let parsed;
    try {
      const out = await env.AI.run(model, {
        messages: buildSuggestMessages(SUGGEST_PROMPT, term, examples),
        max_tokens: Number(env.MAX_TOKENS || 2048),
        temperature: 0.2,
      });
      parsed = parseSuggestion(modelText(out));
    } catch (err) {
      if (isQuotaError(err)) return json({ error: "daily_limit", detail: DAILY_LIMIT_DETAIL }, 429, headers);
      console.error("suggestion failed", String(err));
      return json({ error: "suggestion_failed", detail: "The model could not suggest a term. Try again shortly." }, 502, headers);
    }
    const record = parsed.notTechTerm
      ? { term, notTechTerm: true, model, created_at: new Date().toISOString() }
      : { term, ...parsed, model, examples_used: examples.length, created_at: new Date().toISOString() };
    let stored = false;
    if (env.SUGGESTIONS) {
      await env.SUGGESTIONS.put(key, JSON.stringify(record));
      stored = true;
    }
    return json({ status: parsed.notTechTerm ? "not_tech_term" : "generated", suggestion: record, stored }, 200, headers);
  }

  async function propose(request, env, headers) {
    let proposal;
    try {
      proposal = validateProposal(await request.json());
    } catch (err) {
      const detail = err instanceof RangeError ? err.message : 'Send JSON like {"concept_id": "load-balancer", "text": "ጭነት አመጣጣኝ"}.';
      return json({ error: "bad_request", detail }, 400, headers);
    }
    if (!env.SUGGESTIONS) return json({ error: "unavailable", detail: "Proposals are switched off." }, 503, headers);
    let concepts;
    try {
      concepts = await loadConcepts(env, fetchImpl, { all: true });
    } catch (err) {
      console.error("bundle load failed", String(err));
      return json({ error: "termbase_unavailable", detail: "The glossary could not be loaded. Try again shortly." }, 503, headers);
    }
    const target = await resolveTarget(concepts, proposal, env.SUGGESTIONS);
    if (!target) return json({ error: "unknown_target", detail: "That term is not in the glossary." }, 404, headers);
    if (alreadyListed(target, proposal.text)) {
      return json({ status: "already_listed", detail: "That term is already listed. Thanks!" }, 200, headers);
    }
    const key = proposalKey(proposal);
    const prior = await env.SUGGESTIONS.get(key, "json");
    if (prior) {
      // Same term proposed again: count it, which tells reviewers it has support.
      const updated = { ...prior, count: (prior.count || 1) + 1, last_at: new Date().toISOString() };
      await env.SUGGESTIONS.put(key, JSON.stringify(updated));
      return json({ status: "counted", proposal: publicView(updated) }, 200, headers);
    }
    const siblings = await env.SUGGESTIONS.list({ prefix: `p:${targetKey(proposal)}:` });
    if (siblings.keys.length >= MAX_PER_TARGET) {
      return json({ error: "too_many", detail: "This term already has many proposals waiting for review." }, 429, headers);
    }
    const record = { ...proposal, count: 1, created_at: new Date().toISOString() };
    await env.SUGGESTIONS.put(key, JSON.stringify(record));
    return json({ status: "stored", proposal: publicView(record) }, 200, headers);
  }

  return {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    const { headers, allowed } = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: allowed ? 204 : 403, headers });
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({ ok: true, model: env.MODEL || DEFAULT_MODEL }, 200, headers);
    }
    // Public read of stored AI suggestions, for `tam admin pull-suggestions`.
    if (request.method === "GET" && url.pathname === "/suggestions") {
      if (!env.SUGGESTIONS) return json({ count: 0, suggestions: [] }, 200, headers);
      const suggestions = await listSuggestions(env);
      const proposals = await listProposals(env);
      return json({ count: suggestions.length, suggestions, proposals }, 200, headers);
    }
    // Pending visitor proposals for one concept (shown on its card).
    if (request.method === "GET" && url.pathname === "/proposals") {
      const id = url.searchParams.get("concept") || "";
      if (!env.SUGGESTIONS || !/^[a-z0-9-]{1,80}$/.test(id)) return json({ proposals: [] }, 200, headers);
      const proposals = (await listProposals(env, `p:c:${id}:`)).map(publicView);
      return json({ proposals }, 200, headers);
    }
    const route = request.method === "POST" ? url.pathname : null;
    if (route !== "/chat" && route !== "/suggest" && route !== "/propose") {
      return json({ error: "not_found", detail: "Use POST /chat, /suggest or /propose." }, 404, headers);
    }
    if (!allowed) return json({ error: "forbidden_origin", detail: "This site may not use the chat." }, 403, headers);
    if (Number(request.headers.get("Content-Length") || 0) > MAX_BODY_BYTES) {
      return json({ error: "too_large", detail: "Request body too large." }, 413, headers);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    if (env.RATE_LIMITER) {
      const { success } = await env.RATE_LIMITER.limit({ key: `${route}:${ip}` });
      if (!success) {
        return json({ error: "rate_limited", detail: "Too many requests. Wait a minute and try again." }, 429, headers);
      }
    }
    if (route === "/suggest") return suggest(request, env, headers);
    if (route === "/propose") return propose(request, env, headers);

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
    let shape;
    try {
      const maxTokens = Number(env.MAX_TOKENS || 2048);
      const out = await env.AI.run(model, { messages, max_tokens: maxTokens, temperature: 0.3 });
      answer = cleanAnswer(modelText(out));
      if (!answer) shape = outputShape(out);
    } catch (err) {
      if (isQuotaError(err)) {
        return json({ error: "daily_limit", detail: DAILY_LIMIT_DETAIL }, 429, headers);
      }
      console.error("model call failed", String(err));
      return json({ error: "model_error", detail: "The language model did not answer. Try again shortly." }, 502, headers);
    }
    if (!answer) {
      console.error("empty answer", JSON.stringify(shape));
      return json({ error: "empty_answer", detail: "The model returned no answer. Try rephrasing.", shape }, 502, headers);
    }

    return json(
      { answer, concepts: found.map(conceptSummary), checks: checkAnswer(answer, found), model },
      200,
      headers,
    );
  },
};
}

export function resetBundleCache() {
  bundleCache = { at: 0, concepts: null, all: null };
}

// What the page may show: never the visitor's note or name in listings.
function publicView(p) {
  return { text: p.text, formation: p.formation ?? null, count: p.count || 1, created_at: p.created_at };
}
