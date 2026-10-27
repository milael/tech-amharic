// JS port of src/tech_amharic/chat.py (retrieval, prompt, answer checks).
// tests/fixtures/retrieval_cases.json is run against both implementations.

import { ethiopicRatio, isEthiopicCodePoint, normKey } from "./normalize.js";

export const MAX_QUESTION_CHARS = 500;
export const MAX_HISTORY_MESSAGES = 6;
export const MAX_HISTORY_CHARS = 1500;
export const DEFAULT_TOP_K = 5;

const WORD = /[\p{L}\p{N}_ሀ-᎟ⶀ-⷟꬀-꬯]+/gu;
const STATUS_RANK = { preferred: 0, admitted: 1, proposed: 2 };

const isEthiopicKey = (key) => [...key].some((ch) => isEthiopicCodePoint(ch.codePointAt(0)));

function singular(key) {
  if (!isEthiopicKey(key) && [...key].length > 3 && key.endsWith("s") && !key.endsWith("ss")) {
    return key.slice(0, -1);
  }
  return key;
}

function ngrams(keys, maxN = 4) {
  const out = new Set();
  for (let n = 1; n <= maxN; n++) {
    for (let i = 0; i + n <= keys.length; i++) out.add(keys.slice(i, i + n).join(""));
  }
  return out;
}

function isAcronym(text) {
  const letters = [...text].filter((ch) => /\p{L}/u.test(ch));
  return letters.length > 0 && letters.length <= 5 && letters.every((ch) => /[A-Z]/.test(ch));
}

export function parseQuery(question) {
  const words = String(question).match(WORD) || [];
  const keys = words.map(normKey).filter(Boolean);
  const grams = new Set([...ngrams(keys), ...ngrams(keys.map(singular))]);
  const bases = words.map((w) => (w.endsWith("s") && w.length > 2 ? w.slice(0, -1) : w));
  const acronyms = new Set([...words, ...bases].filter(isAcronym));
  return { grams, folded: normKey(question), acronyms };
}

export function scoreConcept(concept, query) {
  let score = 0;
  for (const term of concept.terms) {
    const key = normKey(term.text);
    if (!key) continue;
    if (isAcronym(term.text)) {
      if (query.acronyms.has(term.text)) score += 3;
    } else if (query.grams.has(key) || query.grams.has(singular(key))) {
      score += 3;
    } else if (isEthiopicKey(key) && [...key].length >= 2 && query.folded.includes(key)) {
      score += 2;
    }
  }
  return score;
}

export function retrieve(concepts, question, k = DEFAULT_TOP_K) {
  const query = parseQuery(question);
  return concepts
    .map((c) => [scoreConcept(c, query), c.id, c])
    .filter(([s]) => s > 0)
    .sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0))
    .slice(0, k)
    .map(([, , c]) => c);
}

export function headword(c) {
  const en = c.terms.filter((t) => t.lang === "en");
  return (en.find((t) => t.status === "preferred") || en[0] || { text: c.id }).text;
}

function amTermsRanked(c) {
  return c.terms
    .filter((t) => t.lang === "am" && t.status in STATUS_RANK)
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
}

export function termbaseBlock(concepts) {
  if (!concepts.length) {
    return "TERMBASE\n(no matching entries; answer from general knowledge and say that no reviewed term was found)";
  }
  const lines = ["TERMBASE"];
  for (const c of concepts) {
    const terms = amTermsRanked(c).map((t) => `${t.text} [${t.status}]`).join(", ") || "(none yet)";
    lines.push(`- ${headword(c)}: ${terms}`);
    if (c.definition_en) lines.push(`  definition: ${c.definition_en}`);
    if (c.definition_am) lines.push(`  ትርጉም: ${c.definition_am}`);
  }
  return lines.join("\n");
}

export function cleanHistory(history) {
  if (!Array.isArray(history)) return [];
  return history
    .slice(-MAX_HISTORY_MESSAGES)
    .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.trim().slice(0, MAX_HISTORY_CHARS) }));
}

export function buildMessages(systemPrompt, question, concepts, history) {
  return [
    { role: "system", content: systemPrompt.trim() },
    { role: "system", content: termbaseBlock(concepts) },
    ...cleanHistory(history),
    { role: "user", content: question.trim().slice(0, MAX_QUESTION_CHARS) },
  ];
}

export function cleanAnswer(text) {
  return String(text || "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}

export function checkAnswer(answer, concepts) {
  const folded = normKey(answer);
  const used = [];
  const missing = [];
  for (const c of concepts) {
    const hit = amTermsRanked(c).some((t) => {
      const k = normKey(t.text);
      return k && folded.includes(k);
    });
    (hit ? used : missing).push(c.id);
  }
  return { ethiopic_ratio: Math.round(ethiopicRatio(answer) * 1000) / 1000, terms_used: used, terms_missing: missing };
}

export function conceptSummary(c) {
  const ranked = amTermsRanked(c);
  return { id: c.id, en: headword(c), am: ranked[0]?.text ?? null, status: ranked[0]?.status ?? null };
}

export function validateQuestion(question) {
  if (typeof question !== "string" || !question.trim()) throw new RangeError("Ask a question first.");
  if (question.length > MAX_QUESTION_CHARS) throw new RangeError(`Keep questions under ${MAX_QUESTION_CHARS} characters.`);
  return question.trim();
}
