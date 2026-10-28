// Tech-Amharic chat proxy on Cloudflare Workers.
//
// The public demo (GitHub Pages) posts questions here. The Worker finds the
// relevant concepts in the published termbase bundle, asks Gemma 4 on
// Workers AI to answer in Amharic using those terms, and returns the answer
// with its sources. No API key ever reaches the browser.
//
// Free-plan safety: Workers AI stops answering when the 10,000 daily
// neurons are used up (no charges), and a per-visitor rate limit keeps one
// visitor from using the whole allowance.
//
// The system prompt is shared with the Python app:
// src/tech_amharic/chat_prompt.txt (bundled by wrangler as a text module).

import SYSTEM_PROMPT from "../../src/tech_amharic/chat_prompt.txt";
import SUGGEST_PROMPT from "../../src/tech_amharic/suggest_prompt.txt";
import { createHandler } from "./handler.js";

export default createHandler(SYSTEM_PROMPT, fetch, SUGGEST_PROMPT);
