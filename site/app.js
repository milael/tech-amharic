// Tech-Amharic static demo. Reads data/bundle.json and searches it in the
// browser with the same folded key as src/tech_amharic/normalize.py.
"use strict";

const DOMAINS = {
  "ai-ml": "AI and machine learning",
  security: "Cybersecurity",
  networking: "Networking",
  software: "Software engineering",
  "cloud-devops": "Cloud and DevOps",
  data: "Data and databases",
  hardware: "Hardware",
  general: "General computing",
};
const STATUS_LABEL = {
  preferred: "Preferred",
  admitted: "Admitted",
  proposed: "Proposed",
  changes_requested: "Changes requested",
  deprecated: "Deprecated",
  rejected: "Rejected",
};
const FORMATION_LABEL = {
  native: "New Amharic coinage",
  extension: "Existing word, new meaning",
  loan: "Loanword",
  calque: "Translated part by part",
  abbreviation: "Abbreviation",
  phrase: "Descriptive phrase",
};

// ---- normalization (keep in sync with normalize.py) -------------------------
const ROW_FOLDS = { 0x1210: 0x1200, 0x1280: 0x1200, 0x1220: 0x1230, 0x12d0: 0x12a0, 0x1340: 0x1338 };
const ORDER_FOLDS = { 0x1203: 0x1200, 0x12a3: 0x12a0 };
const DROP = /[\p{P}\p{Z}\p{C}\p{Sk}\p{Sm}]/u;
const isEthiopic = (cp) =>
  (cp >= 0x1200 && cp <= 0x139f) || (cp >= 0x2d80 && cp <= 0x2ddf) || (cp >= 0xab00 && cp <= 0xab2f);

function normKey(text) {
  let out = "";
  for (const ch of text.normalize("NFC").toLowerCase()) {
    if (DROP.test(ch)) continue;
    let cp = ch.codePointAt(0);
    if (isEthiopic(cp)) {
      const row = cp & ~0x7;
      if (row in ROW_FOLDS) cp = ROW_FOLDS[row] + (cp - row);
      if (cp in ORDER_FOLDS) cp = ORDER_FOLDS[cp];
    }
    out += String.fromCodePoint(cp);
  }
  return out;
}

// ---- state ------------------------------------------------------------------
const state = { concepts: [], q: "", domain: "", selected: null };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const headword = (c) =>
  (c.terms.find((t) => t.lang === "en" && t.status === "preferred") || c.terms.find((t) => t.lang === "en") || { text: c.id }).text;
const amTerms = (c) => c.terms.filter((t) => t.lang === "am");
const preferredAm = (c) => amTerms(c).find((t) => t.status === "preferred");

function search() {
  const key = normKey(state.q);
  const scored = [];
  for (const c of state.concepts) {
    if (state.domain && c.domain !== state.domain) continue;
    if (!key) { scored.push([0, headword(c).toLowerCase(), c]); continue; }
    let best = Infinity;
    for (const t of c.terms) {
      const k = t._key;
      if (k === key) best = Math.min(best, 0);
      else if (k.startsWith(key)) best = Math.min(best, 1);
      else if (k.includes(key)) best = Math.min(best, 2);
    }
    if (c._defKey.includes(key) && best === Infinity) best = 3;
    if (best !== Infinity) scored.push([best, headword(c).toLowerCase(), c]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]));
  return scored.map((s) => s[2]);
}

// ---- rendering --------------------------------------------------------------
function renderFilters() {
  const counts = {};
  for (const c of state.concepts) counts[c.domain] = (counts[c.domain] || 0) + 1;
  const buttons = [["", `All (${state.concepts.length})`]].concat(
    Object.entries(DOMAINS).filter(([k]) => counts[k]).map(([k, v]) => [k, `${v} (${counts[k]})`])
  );
  $("filters").innerHTML = buttons
    .map(([k, label]) => `<button type="button" data-domain="${k}" aria-pressed="${state.domain === k}">${esc(label)}</button>`)
    .join("");
}

function renderResults() {
  const list = search();
  $("count").textContent = state.q
    ? `${list.length} ${list.length === 1 ? "match" : "matches"} for “${state.q}”`
    : `${list.length} concepts`;
  if (!list.length) {
    const canSuggest = chatState.suggestEndpoint && SUGGESTABLE.test(state.q);
    $("results").innerHTML = canSuggest
      ? `<li class="empty">“${esc(state.q)}” is not in the glossary yet.
          <button type="button" class="suggest-btn" data-term="${esc(state.q)}">Suggest an Amharic term with AI</button></li>`
      : `<li class="empty">No concept matches “${esc(state.q)}”. Try the English term, or fewer letters.</li>`;
    return list;
  }
  $("results").innerHTML = list
    .map((c) => {
      const pref = preferredAm(c);
      const am = pref ? pref.text : amTerms(c).map((t) => t.text).join(" · ");
      return `<li><a href="#/c/${encodeURIComponent(c.id)}" data-id="${esc(c.id)}"${state.selected === c.id ? ' aria-current="true"' : ""}>
        <span class="en">${esc(headword(c))}</span>
        <span class="dom">${esc(DOMAINS[c.domain] || c.domain)}</span>
        <span class="am" lang="am">${esc(am)}</span></a></li>`;
    })
    .join("");
  return list;
}

function renderDetail(c) {
  const el = $("detail");
  if (!c) {
    el.innerHTML = `<p class="path">Nothing selected</p><h2>Pick a concept</h2><p class="alt">Choose a term from the list to see its Amharic options, status and definition.</p>`;
    return;
  }
  const am = amTerms(c);
  const pref = preferredAm(c);
  const lead = pref || am[0];
  const enAlts = c.terms.filter((t) => t.lang === "en" && t.text !== headword(c)).map((t) => t.text);
  const rows = am
    .map((t) => {
      const src = (t.sources || []).map((s) => esc(s.citation)).join("; ");
      const ai = (t.sources || []).some((s) => AI_SOURCE.test(s.citation || ""));
      return `<tr><td lang="am">${esc(t.text)}${src ? `<div class="src">${src}</div>` : ""}</td>
        <td><span class="badge ${esc(t.status)}">${esc(STATUS_LABEL[t.status] || t.status)}</span>${ai ? ' <span class="badge ai">AI draft</span>' : ""}</td>
        <td>${esc(FORMATION_LABEL[t.formation] || "Not recorded")}</td></tr>`;
    })
    .join("");
  el.innerHTML = `
    <p class="path">${esc(DOMAINS[c.domain] || c.domain)}${c.subdomain ? ` / ${esc(c.subdomain)}` : ""}</p>
    <h2>${esc(headword(c))}</h2>
    ${enAlts.length ? `<p class="alt">Also: ${esc(enAlts.join(", "))}</p>` : '<p class="alt"></p>'}
    ${lead ? `<p class="amharic-hero${pref ? "" : " pending"}" lang="am">${esc(lead.text)}</p>
      <p class="hero-caption">${pref ? "Preferred Amharic term" : "Leading proposal, not yet reviewed"}</p>` : '<p class="hero-caption">No Amharic term proposed yet.</p>'}
    ${c.definition_en ? `<p class="def">${esc(c.definition_en)}</p>` : ""}
    ${c.definition_am ? `<p class="def" lang="am">${esc(c.definition_am)}</p>` : ""}
    ${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}
    ${am.length ? `<table class="terms"><thead><tr><th>Amharic</th><th>Status</th><th>How it was formed</th></tr></thead><tbody>${rows}</tbody></table>` : ""}`;
}

function update({ keepSelection = false } = {}) {
  const list = renderResults();
  if (!keepSelection || !state.concepts.some((c) => c.id === state.selected)) {
    // Select the best match so the detail panel always shows something useful.
    if (state.q && list.length) state.selected = list[0].id;
  }
  renderDetail(state.concepts.find((c) => c.id === state.selected));
  renderResults();
}

function fromHash() {
  const m = location.hash.match(/^#\/c\/(.+)$/);
  if (m) {
    state.selected = decodeURIComponent(m[1]);
    update({ keepSelection: true });
  }
}

// ---- boot -------------------------------------------------------------------
async function boot() {
  try {
    const res = await fetch("data/bundle.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const bundle = await res.json();
    state.concepts = bundle.concepts;
    for (const c of state.concepts) {
      for (const t of c.terms) t._key = normKey(t.text);
      c._defKey = normKey(`${c.definition_en || ""} ${c.definition_am || ""}`);
    }
    const am = state.concepts.flatMap(amTerms);
    const reviewed = am.filter((t) => ["preferred", "admitted", "deprecated"].includes(t.status)).length;
    if (reviewed > 0 && reviewed === am.length) $("notice").hidden = true;
  } catch (err) {
    $("results").innerHTML = `<li class="empty">The term data could not be loaded (${esc(err.message)}). Reload the page to try again.</li>`;
    return;
  }

  const params = new URLSearchParams(location.search);
  state.q = params.get("q") || "";
  $("q").value = state.q;
  state.selected = state.concepts.some((c) => c.id === "encryption") ? "encryption" : state.concepts[0]?.id;

  renderFilters();
  update();
  fromHash();

  $("q").addEventListener("input", (e) => {
    state.q = e.target.value.trim();
    const url = new URL(location.href);
    if (state.q) url.searchParams.set("q", state.q); else url.searchParams.delete("q");
    history.replaceState(null, "", url);
    update();
  });
  $("filters").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.domain = b.dataset.domain;
    renderFilters();
    update();
  });
  $("results").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-id]");
    if (!a) return;
    state.selected = a.dataset.id;
    renderDetail(state.concepts.find((c) => c.id === state.selected));
    renderResults();
    if (window.matchMedia("(max-width: 760px)").matches) $("detail").scrollIntoView({ block: "start" });
  });
  window.addEventListener("hashchange", fromHash);
}

// ---- ask (chat) ---------------------------------------------------------------
const chatState = { endpoint: "", suggestEndpoint: "", history: [], busy: false };
const SUGGESTABLE = /^[A-Za-z][A-Za-z0-9 .+#/&'-]{1,59}$/;
const AI_SOURCE = /^(Seed draft by AI|AI suggestion)/;

// ---- AI term suggestions --------------------------------------------------------
function renderSuggestion(term, data) {
  const el = $("detail");
  if (data.status === "exists") {
    state.selected = data.concept_id;
    renderDetail(state.concepts.find((c) => c.id === data.concept_id));
    return;
  }
  if (data.status === "not_tech_term") {
    el.innerHTML = `<p class="path">AI suggestion</p><h2>${esc(term)}</h2>
      <p class="alt">This does not look like a technology term, so no Amharic term was suggested.</p>`;
    return;
  }
  const s = data.suggestion;
  const rows = s.terms
    .map((t) => `<tr><td lang="am">${esc(t.text)}</td>
      <td><span class="badge proposed">Proposed</span> <span class="badge ai">AI draft</span></td>
      <td>${esc(FORMATION_LABEL[t.formation] || "Not recorded")}</td></tr>`)
    .join("");
  const day = String(s.created_at || "").slice(0, 10);
  el.innerHTML = `
    <p class="path">${esc(DOMAINS[s.domain] || s.domain)} / AI suggestion</p>
    <h2>${esc(s.term)}</h2>
    <p class="amharic-hero pending" lang="am">${esc(s.terms[0].text)}</p>
    <p class="hero-caption">Suggested by AI, not reviewed</p>
    ${s.definition_en ? `<p class="def">${esc(s.definition_en)}</p>` : ""}
    ${s.definition_am ? `<p class="def" lang="am">${esc(s.definition_am)}</p>` : ""}
    <table class="terms"><thead><tr><th>Amharic</th><th>Status</th><th>How it was formed</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note">Generated by Gemma 4${day ? ` on ${esc(day)}` : ""} and saved for reviewers. It will appear in the glossary as a proposed term once added.</p>`;
}

async function requestSuggestion(term) {
  const el = $("detail");
  el.innerHTML = `<p class="path">AI suggestion</p><h2>${esc(term)}</h2><p class="alt">Asking the AI for Amharic options… this can take up to a minute.</p>`;
  if (window.matchMedia("(max-width: 760px)").matches) el.scrollIntoView({ block: "start" });
  try {
    const res = await fetch(chatState.suggestEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ term }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `The suggestion service answered with an error (${res.status}).`);
    renderSuggestion(term, data);
  } catch (err) {
    const msg = err instanceof TypeError ? "The suggestion service could not be reached. Try again shortly." : err.message;
    el.innerHTML = `<p class="path">AI suggestion</p><h2>${esc(term)}</h2><p class="alt">${esc(msg)}</p>`;
  }
}

// Minimal, safe formatting for model answers: escape first, then paragraphs,
// "- " bullets and **bold**.
function formatAnswer(text) {
  const blocks = esc(text).split(/\n{2,}/);
  return blocks
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*•]\s+/.test(l))) {
        return `<ul>${lines.map((l) => `<li>${l.replace(/^\s*[-*•]\s+/, "")}</li>`).join("")}</ul>`;
      }
      return `<p>${lines.join("<br>")}</p>`;
    })
    .join("")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function addMessage(kind, html) {
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.innerHTML = html;
  $("chat-log").append(el);
  return el;
}

function renderSources(result) {
  if (!result.concepts?.length) {
    return `<div class="sources">No glossary entry matched this question.</div>`;
  }
  const used = new Set(result.checks?.terms_used || []);
  const chips = result.concepts
    .map((c) => {
      const label = STATUS_LABEL[c.status] || "No Amharic term";
      return `<a href="#/c/${encodeURIComponent(c.id)}" class="${used.has(c.id) ? "" : "unused"}" title="${esc(label)}${used.has(c.id) ? "" : ", not used in the answer"}">
        ${esc(c.en)}${c.am ? ` <span lang="am">${esc(c.am)}</span>` : ""}</a>`;
    })
    .join("");
  return `<div class="sources">From the glossary: ${chips}</div>`;
}

async function sendQuestion(question) {
  if (chatState.busy || !question.trim()) return;
  chatState.busy = true;
  $("ask-send").disabled = true;
  $("suggestions").hidden = true; // examples only matter before the first question
  const isAm = /[\u1200-\u139f]/u.test(question) ? ' lang="am"' : "";
  addMessage("user", `<div class="who">You</div><div class="body"${isAm}>${esc(question)}</div>`);
  const pending = addMessage("bot pending", `<div class="who">Answer</div><div class="body">Writing an answer…</div>`);
  try {
    const res = await fetch(chatState.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: chatState.history.slice(-6) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `The chat service answered with an error (${res.status}).`);
    pending.className = "msg bot";
    pending.innerHTML = `<div class="who" title="Generated by ${esc(data.model || "a language model")}">Answer</div>
      <div class="body"><div class="answer" lang="am">${formatAnswer(data.answer)}</div>${renderSources(data)}</div>`;
    chatState.history.push({ role: "user", content: question }, { role: "assistant", content: data.answer });
  } catch (err) {
    const msg = err instanceof TypeError ? "The chat service could not be reached. Check your connection and try again." : err.message;
    pending.className = "msg error";
    pending.innerHTML = `<div class="body">${esc(msg)}</div>`;
  } finally {
    chatState.busy = false;
    $("ask-send").disabled = false;
  }
}

async function setupChat() {
  try {
    const res = await fetch("config.json", { cache: "no-cache" });
    const cfg = res.ok ? await res.json() : {};
    chatState.endpoint = cfg.chatEndpoint || "";
    chatState.suggestEndpoint = cfg.suggestEndpoint || "";
  } catch {
    chatState.endpoint = "";
  }
  if (chatState.suggestEndpoint) {
    $("results").addEventListener("click", (e) => {
      const b = e.target.closest(".suggest-btn");
      if (b) requestSuggestion(b.dataset.term);
    });
    if (state.q) renderResults();
  }
  if (!chatState.endpoint) return; // chat stays hidden until a Worker is deployed
  for (const id of ["ask", "nav-ask"]) $(id).hidden = false;
  $("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("ask-input").value.trim();
    $("ask-input").value = "";
    sendQuestion(q);
  });
  $("ask-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("ask-form").requestSubmit();
    }
  });
  $("suggestions").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) sendQuestion(b.textContent.trim());
  });
}

boot();
setupChat();
