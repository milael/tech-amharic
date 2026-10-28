// Visitor proposals: anyone on the demo can suggest a better Amharic term for
// a glossary concept (or for an AI suggestion that has not been imported
// yet). Proposals are stored for reviewers and imported weekly as *proposed*
// terms labelled "proposed by a demo visitor". Nothing here approves anything.

import { ethiopicRatio, normKey } from "./normalize.js";
import { FORMATIONS, storageKey, validateTerm } from "./suggest-core.js";

export const MAX_PER_TARGET = 20;

const CONCEPT_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// Ge'ez (incl. supplements), digits, spaces and light punctuation only.
const TERM_CHARS = /^[ሀ-᎟ⶀ-⷟꬀-꬯A-Za-z0-9 ./()-]+$/u;
const NAME_CHARS = /^[\p{L}\p{M} .'-]+$/u;
const LINKY = /https?:|www\.|<|>/i;

const squash = (s) => String(s ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().replace(/\s+/g, " ");

/** Check a proposal body. Throws RangeError with a reader-facing message. */
export function validateProposal(body) {
  if (!body || typeof body !== "object") throw new RangeError("Send a proposal as JSON.");
  const text = squash(body.text);
  if (text.length < 2 || text.length > 60) throw new RangeError("The Amharic term must be 2 to 60 characters.");
  if (!TERM_CHARS.test(text) || ethiopicRatio(text) < 0.8) {
    throw new RangeError("Write the term in Ge'ez script (ፊደል), for example ጭነት አመጣጣኝ.");
  }
  const formation = body.formation ? String(body.formation) : null;
  if (formation && !FORMATIONS.includes(formation)) throw new RangeError("Unknown formation.");
  const note = squash(body.note);
  if (note.length > 280) throw new RangeError("Keep the note under 280 characters.");
  const name = squash(body.name);
  if (name.length > 40 || (name && !NAME_CHARS.test(name))) throw new RangeError("Names may only contain letters, up to 40.");
  if (LINKY.test(note) || LINKY.test(name)) throw new RangeError("Links are not allowed.");

  let target;
  if (body.concept_id) {
    const id = String(body.concept_id);
    if (!CONCEPT_ID.test(id) || id.length > 80) throw new RangeError("Unknown concept.");
    target = { concept_id: id };
  } else if (body.term) {
    target = { term: validateTerm(body.term) };
  } else {
    throw new RangeError("Say which concept the term is for.");
  }
  return { ...target, text, formation, note: note || null, name: name || null };
}

export const targetKey = (p) => (p.concept_id ? `c:${p.concept_id}` : `t:${normKey(p.term)}`);
export const proposalKey = (p) => `p:${targetKey(p)}:${normKey(p.text)}`;

/**
 * Find what the proposal is for: a glossary concept, or a stored AI suggestion.
 * Returns {label, existing: [term texts]} or null.
 */
export async function resolveTarget(concepts, proposal, kv) {
  if (proposal.concept_id) {
    const c = concepts.find((x) => x.id === proposal.concept_id);
    return c ? { existing: c.terms.map((t) => t.text) } : null;
  }
  const s = kv ? await kv.get(storageKey(proposal.term), "json") : null;
  if (!s || s.notTechTerm) return null;
  return { existing: [s.term, ...(s.terms || []).map((t) => t.text)] };
}

export const alreadyListed = (target, text) => target.existing.some((t) => normKey(t) === normKey(text));
