# Chat worker (Cloudflare Workers AI)

The public demo's "Ask a question" panel posts to this Worker. For each
question it:

1. loads the published termbase bundle from GitHub Pages (cached 10 minutes),
2. finds the concepts the question mentions (same rules as `src/tech_amharic/chat.py`),
3. asks **Gemma 4 26B** (`@cf/google/gemma-4-26b-a4b-it`) on Workers AI to answer in Amharic using those terms,
4. returns the answer, the concepts it drew on, and simple checks (Ge'ez script share, which terms were used).

No API key reaches the browser. On the Workers Free plan the model allowance
is 10,000 neurons a day (very roughly 200 answers); after that Workers AI
refuses requests until midnight UTC, there are no charges, and the page shows
a "daily limit reached" message. A per-visitor rate limit (6 questions a
minute) stops one visitor from using the whole allowance.

## One-time setup

1. Create a free account at [dash.cloudflare.com](https://dash.cloudflare.com).
2. Copy your **Account ID** (Workers & Pages overview, right-hand side).
3. Create an **API token**: My Profile → API Tokens → Create Token → template
   **Edit Cloudflare Workers**. Add the permission **Account → Workers AI → Read**
   if the template doesn't include it.
4. In GitHub: repo → Settings → Secrets and variables → Actions → New repository secret:
   - `CLOUDFLARE_API_TOKEN` = the token
   - `CLOUDFLARE_ACCOUNT_ID` = the account ID
5. Re-run the **Chat worker** workflow (Actions tab) or push a change under `worker/`.
   The run's summary shows the Worker URL, e.g. `https://tech-amharic-chat.<you>.workers.dev`.
6. Put that URL plus `/chat` in `site/config.json` as `chatEndpoint`. The Ask panel
   appears on the next Pages deploy.

## Local development

```bash
npm test                 # unit tests, incl. retrieval parity with Python
npx wrangler@4 dev       # runs locally; Workers AI calls use your account
```

Settings live in `wrangler.toml` (`[vars]`): model, bundle URL, allowed
origins, and whether unreviewed terms are used.
