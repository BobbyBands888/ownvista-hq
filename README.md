# Ownvista HQ

A small world of AI agents that works Bobby's businesses on a schedule, drafts his email, researches the web,
proposes growth ideas and new businesses, runs Villa Cinema end to end, and gets measurably better from his edits.
Runs on free tiers; the only paid spend is Villa Cinema video generation, capped in the database.

- **Agents:** Node 20+, zero npm dependencies, one hourly GitHub Actions job (`.github/workflows/hq.yml`, minute :07).
- **Database:** Supabase free tier, row-level security on every table (only bobbybands888@gmail.com), agents use the secret key.
- **Dashboard:** static site on Vercel at levelingclips.com (magic-link login). Customer pages at films.villacinema.com.
- **AI:** Groq free tier behind `agents/lib/llm.js` (`LLM_PROVIDER=groq|anthropic`).

Setup: **[docs/SETUP.md](docs/SETUP.md)**.

## Agents

| Agent | When (America/New_York) | What it does |
|---|---|---|
| Villa Outreach | hourly 6am–11pm | Zoho inbox (bounces, unsubscribes, complaints, replies), Stripe payments, follow-ups, first emails, prospect discovery |
| Operator | hourly, 24/7 | Gmail → drafts in the thread (never sends), flags money/contract/legal-tax/complaint/press/pricing, records what Bobby sent, works agent tasks, builds growth-idea assets |
| Villa Studio | hourly when an order is in production | photo pick (vision) → MiniMax-H3 768P clips → vision QA (≤2 retries/clip) → 2K regeneration for paid → ffmpeg film → review → delivery |
| Researcher (+ Hunter) | every 3 hours | public feeds + approved searches → relevant knowledge (business tags, usefulness 1–5); retires useless sources; Hunter extracts demand signals in 6 lanes |
| Strategist | daily 7am | ≤3 growth ideas, ≤3 agent tasks, ≤3 new research queries |
| Scout | Mon + Thu 8am | ≤3 new businesses scored 0–100 with real source links; launch kit for #1 |
| Analyst | daily 9am | one-page business cases with unit economics and a $0–25 experiment |
| Builder | hourly, 24/7 when work exists | assets for approved ideas/experiments (no accounts, no payments, no publishing) |
| Judge | Sundays 6pm | scale / continue / kill per running experiment, with numbers |
| Learner | hourly, 24/7 (grades the day at 11pm) | edits + feedback → playbook rules (dedupe, consolidate past 40, version history), grades drafts, self-review, daily metrics |
| Economist | daily 11pm | P&L per agent (revenue share − shadow cost), runway vs real bills, weekly survival pressure per lane, writes the budgets agents already obey (token shares, image cap, minutes per run), closes crew probation |
| Architect | Sundays 7pm | retires crew that doesn't pay, clones a proven agent where an earning lane is bottlenecked, designs one new crew member (data, not code) — both deploy automatically on probation |

The router runs every due agent inside one job and catches up after delayed or dropped GitHub schedule runs.
Manual runs: Actions → Ownvista HQ → Run workflow → pick an agent, `villa_preflight`, `villa_test_email`,
`villa_test_order` or `captest`.

## Guardrails and where they are enforced

| Rule | Enforced by |
|---|---|
| Gmail is drafts only | `agents/lib/gmail.js` allowlist (send paths refused before `fetch`); `test/no-send.test.js` runs before every job |
| Only Villa Cinema sends, only from hello@villacinema.com | `agents/lib/sendgate.js` is the only send code (test-enforced) and asks the database first |
| Send caps: 20 first emails/day with 5→20 warm-up over 14 days, one follow-up after 4+ days, no third touch, role addresses only, per-country switch (US only on), suppression list, unsubscribe footer + physical address, 60/day safety cap | `vc_reserve_send()` in Postgres |
| Auto-pause on >5% bounces or any complaint | `vc_record_bounce()` / `vc_pause()`; Bobby resumes from Needs you |
| Spend: $20 per paid film (incl. 2K upgrade + retries, upgrade reserved up front), $25/week samples, $150/month backstop, flag Bobby on refusal | `vc_reserve_spend()` in Postgres; every MiniMax call requires a reservation id |
| No other spending, no accounts, no publishing | no code paths exist; paid-API grep test; experiments needing money or accounts go to Needs you |
| No phone-call offers, no Nashville Buys vendor pricing, no legal/tax/RE advice, businesses never cross-mentioned | `checkCopy()` in `agents/lib/guard.js` on every draft/asset/email, plus the playbook |
| Prompt-injection defense | every system prompt starts with `systemPrompt()`; all email/web text is wrapped by `untrusted()` |
| Economy moves effort, never permissions | `agents/economist.js` writes budgets only; protected agents (Operator, Learner, Launcher, Villa Outreach, Economist, Architect, Paper Trader) never drop below base; no shutdowns while total revenue is $0 |
| Architect crew can't send, spend, publish, sign up or trade | crew are rows in `crew_specs`: clones run an existing module, new ones run `agents/spawned.js` (5 proposal-only blocks); `validateSpec()` + `test/economy.test.js` run before every job; 14-day probation, Stop button on the Economy page |
| robots.txt, public pages only | `agents/lib/robots.js` checks before every fetch (RFC 9309) |

## How it gets better

1. The Operator saves each draft with the playbook version it used.
2. When Bobby sends, the Operator stores his final text and the word-level edit distance.
3. Nightly, the Learner turns edits, "Correct the voice" notes, idea feedback and rejections into playbook rules,
   consolidates past 40, snapshots a version, grades the day's drafts and writes a self-review every agent reads next day.
4. World → "Is it getting better?" shows edit distance, % sent unedited, draft grade and ideas approved, last 7 days vs the 7 before.

## Free-tier limits (verified 2026-09-30)

| Service | Limit | How we stay under it |
|---|---|---|
| Groq `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` | 30 RPM, 1K RPD, 8K TPM, 200K TPD each | 150K tokens/day per model + per-agent shares in `kv.llm_caps`; 7K TPM pacing; 429 backoff; agents stop with status `capped` |
| Supabase Free | 500 MB DB, 1 GB storage, 50 MB/file, 5 GB egress, pauses after 7 idle days | films encoded < 45 MB, photos deleted at delivery, films after 30 days; hourly traffic keeps it awake |
| GitHub Actions (private) | 2,000 min/month, each job rounded up to a minute | one job per hour, 20-min timeout, minutes logged per run and shown on World |
| Vercel | Pro plan | — |

## Changes from the original spec (and why)

- `llama-3.1-8b-instant` is no longer on Groq's free plan → bulk work uses `openai/gpt-oss-20b`.
- Google News RSS and Reddit RSS are **disallowed by their robots.txt** → starter sources are 20 verified publisher feeds + hnrss.org;
  search-query sources wait (paused) until Bobby approves a search API. Proposal: Tavily free plan (1,000/month, no card).
- Zoho via its **REST API** (Bobby's choice) instead of SMTP/IMAP. hello@villacinema.com needs a paid Zoho plan (preflight checks).
- 2K upgrade is `POST /v2/video_regeneration` (available on the direct API). Real price is $0.05/s output **plus** $0.05/s for the
  input video, so $0.10/s; a 10-clip paid film costs about $9 including the upgrade.
- HEIC uploads are not accepted (the vision model can't read them); phones convert to JPEG on upload.
- Villa Cinema price is **$149 per film, one-time**, set by the Actions variable `VC_PRICE_USD` (default 149). Replies,
  sample deliveries and the playbook use it; Villa emails that mention any other dollar amount are blocked; Stripe payments
  for a different amount are flagged. Free samples for prospects who reply with interest are unchanged.
- `Outreach on` gates only cold first emails and follow-ups; replies, order emails and deliveries keep working. Pause stops everything.

## Layout

```
agents/            run.js (entry), router.js, one file per agent, lab/ (Hunter, Analyst, Builder, Judge), villa/ (Outreach, Studio)
agents/lib/        llm, db, storage, gmail (drafts-only), zoho (read-only), sendgate (the only sender), spend, minimax,
                   stripe (read-only), search, feeds, robots, guard, ffmpeg, pricing, context, text, time, log, env
api/               Vercel Functions: upload-url (signed photo uploads), unsubscribe
dashboard/         index.html + js/ (World, Needs you, Email, Villa, Lab, Ideas, Tasks, Knowledge, Sources, Playbook),
                   films.html + upload.html (films.villacinema.com)
supabase/schema.sql  the one SQL block (schema, RLS, functions, seed)
test/              offline tests (run before every job); live-tests/caps.js (dispatch "captest")
scripts/           build-config.js (Vercel), zoho-token.js (one-time Zoho refresh token), rls-check.js (post-setup RLS proof)
```

## Local commands

```bash
npm test
```

```bash
node agents/run.js --plan
```
