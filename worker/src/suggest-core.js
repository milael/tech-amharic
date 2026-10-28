// AI term suggestions: when a glossary search finds nothing, Gemma 4 proposes
// Amharic options for the English term. Every suggestion is labelled as an
// unreviewed AI draft and stored for reviewers. Approved glossary terms are
// passed to the model as examples, so suggestions follow reviewer decisions
// more closely as the approved vocabulary grows.

import { ethiopicRatio, normKey } from "./normalize.js";
import { headword, retrieve } from "./chat-core.js";

export const DOMAINS = ["ai-ml", "security", "networking", "software", "cloud-devops", "data", "hardware", "general"];
export const FORMATIONS = ["native", "extension", "loan", "calque", "abbreviation", "phrase"];
const APPROVED = new Set(["preferred", "admitted"]);
const MAX_EXAMPLES = 12;

export function validateTerm(term) {
  if (typeof term !== "string") throw new RangeError("Send a term to look up.");
  const t = term.trim().replace(/\s+/g, " ");
  if (t.length < 2 || t.length > 60) throw new RangeError("Terms must be 2 to 60 characters.");
  if (!/^[A-Za-z][A-Za-z0-9 .+#/&'-]*$/.test(t)) {
    throw new RangeError("Suggestions work for English technology terms, for example 'kubernetes'.");
  }
  return t;
}

export const storageKey = (term) => `s:${normKey(term)}`;

/** Find a glossary concept whose English or Amharic term equals the input. */
export function findExisting(concepts, term) {
  const key = normKey(term);
  return concepts.find((c) => c.terms.some((t) => normKey(t.text) === key)) || null;
}

/** Approved (reviewed) term pairs to show the model, related ones first. */
export function pickExamples(concepts, term, max = MAX_EXAMPLES) {
  const approved = concepts
    .map((c) => ({ c, am: c.terms.filter((t) => t.lang === "am" && APPROVED.has(t.status)) }))
    .filter((x) => x.am.length);
  if (!approved.length) return [];
  const related = new Set(retrieve(approved.map((x) => x.c), term, max).map((c) => c.id));
  const ordered = [...approved.filter((x) => related.has(x.c.id)), ...approved.filter((x) => !related.has(x.c.id))];
  return ordered.slice(0, max).map(({ c, am }) => ({
    en: headword(c),
    domain: c.domain,
    am: am.map((t) => ({ text: t.text, status: t.status, formation: t.formation ?? null })),
  }));
}

export function buildSuggestMessages(prompt, term, examples) {
  const exampleText = examples.length
    ? examples
        .map((e) => `- ${e.en} [${e.domain}]: ${e.am.map((t) => `${t.text} (${t.status}${t.formation ? `, ${t.formation}` : ""})`).join("; ")}`)
        .join("\n")
    : "(none yet; no terms have been approved)";
  return [
    { role: "system", content: prompt.trim() },
    { role: "system", content: `APPROVED EXAMPLES\n${exampleText}` },
    { role: "user", content: `English term: ${term}` },
  ];
}

/** Pull the first JSON object out of model text (tolerates ```json fences and thinking blocks). */
function extractJson(text) {
  const cleaned = String(text || "").replace(/<think>[\s\S]*?<\/think>/gi, "");
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start < 0 || end <= start) throw new SyntaxError("no JSON object in model output");
  return JSON.parse(cleaned.slice(start, end + 1));
}

const clip = (s, n) => (typeof s === "string" ? s.trim().slice(0, n) : "");

/** Validate and normalise the model's suggestion. Throws on unusable output. */
export function parseSuggestion(text) {
  const raw = extractJson(text);
  if (raw?.error === "not_a_tech_term") return { notTechTerm: true };
  const seen = new Set();
  const terms = (Array.isArray(raw?.terms) ? raw.terms : [])
    .map((t) => ({ text: clip(t?.text, 80), formation: FORMATIONS.includes(t?.formation) ? t.formation : null }))
    .filter((t) => {
      if (!t.text) return false;
      const ok = ethiopicRatio(t.text) >= 0.5 || t.formation === "abbreviation";
      const k = normKey(t.text);
      if (!ok || seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .slice(0, 3);
  if (!terms.length) throw new RangeError("model gave no usable Amharic term");
  const amDef = clip(raw?.definition_am, 400);
  return {
    domain: DOMAINS.includes(raw?.domain) ? raw.domain : "general",
    definition_en: clip(raw?.definition_en, 400),
    definition_am: ethiopicRatio(amDef) >= 0.5 ? amDef : "",
    terms,
  };
}
