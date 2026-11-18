# Ten-Four Tapes HQ (levelingclips.com)

Ten agents that run the Ten-Four Tapes YouTube channel and Facebook page. $0 stack: Groq free tier,
Supabase free org, GitHub Actions (one hourly job), Vercel Hobby, free Google + Meta APIs.

## The agents

| Agent | Where | When | Job |
|---|---|---|---|
| Research | cloud | daily | Studies top bodycam channels (EWU, Code Blue Cam, Dr Insanity + discovered ones) → playbook |
| Scout | cloud | every 3h | Finds footage leads: agency YouTube channels, DVIDS, news. Scores action 1–10 and **on-screen danger 0–10** (shots fired/weapon on officers = 10 … calm stop = 0; never the aftermath). Every agent that picks leads works the most dangerous first. Screens minors, de-dupes incidents |
| Outreach | cloud | weekdays 9am/1pm ET | Sends public records requests from bobbybands888 (cap 10/day, 2/agency/day). Finds agency records emails on official sites |
| Records Tracker | cloud | every 2h | Reads agency replies, catches download links + expiry, flags fee quotes/questions to you, follows up after 10 days |
| Case Desk | cloud | every 6h | Researches who / why / how it ended for every case (agency release + news, every fact sourced). Maker won't script a case without it. Re-checks open cases on posted episodes every 14 days and alerts you with a description update when an outcome lands |
| Maker | cloud | every 6h | Turns obtained footage into plans: episode + 3 Shorts (Part 1/2/3) + standalone FB Reels, using the playbook. Keeps a **2-week backlog** (`backlog_days`): below it, plans up to 5 cases a run, then **re-cut mode** makes new Reels from the footage behind our top Facebook Reels (A grade / 30K+ views): the same moment from another officer's camera, or the next strongest moment, never the winner's clip (max 2 per winner, `recut_mode` = auto/off) |
| Compliance | cloud | hourly | The gate: provenance proof, credit line, no minors, no death on camera, platform policy review |
| Publisher | Mac | every 30 min | Renders with `mac/render.py`, uploads to YouTube + FB Reels (1 Short/day, 3 Reels/day, 2 episodes/week) |
| Analytics | cloud | daily | Pulls our YouTube + Facebook numbers (views, watch time, CTR + impressions when YouTube exposes them, traffic sources, retention drop/spike, subs per 1K, revenue after YPP) → "what works for us" into the playbook; fires breakout and ad-limit alerts |
| Reports | cloud | Fri 8am / 1st Mon | Weekly scoreboard and monthly review (top 3 vs bottom 3 by tag) on the dashboard; run by the Overseer |
| Overseer | cloud | hourly | Health checks, one retry on failure, jam detection, 8am ET daily report email |

Hard rules baked into every agent: no spending (fee quotes go to you, never paid), no comment replies,
no call offers, agency/prosecutor/public-domain footage only, no minors, no death on camera.
Approvals are required on the dashboard until **Nov 23, 2026**, then it goes full auto (change any time).

## Setup (one-time)
1. **Turn off the old HQ jobs** — in the old repo on GitHub: Actions → each workflow → ⋯ → Disable workflow.
2. **Supabase** — new project in the free org → SQL Editor → run `supabase/schema.sql`.
   Authentication → URL Configuration → Site URL `https://levelingclips.com`.
3. **Google Cloud** (signed in as bobbybands888) — new project; enable Gmail API, YouTube Data API v3,
   YouTube Analytics API; OAuth consent screen External → **Publish app** (keeps the token from expiring after 7 days);
   create OAuth client (Desktop) + an API key. Then on the Mac: `python3 mac/get_google_token.py CLIENT_ID CLIENT_SECRET`.
4. **Meta** — developers.facebook.com → create app (Business) → get a long-lived Page token for Ten-Four Tapes
   with pages_manage_posts, pages_read_engagement, pages_show_list, read_insights.
5. **DVIDS** — api key from your DVIDS account.
6. **GitHub** — new private repo `tenfour-hq`, upload this folder, add the secrets listed in `.github/workflows/tick.yml`.
   Optional first: Settings → Variables → `DRY_RUN=1` for a no-send test day.
7. **Vercel** — import the repo, Root Directory `dashboard`, add domain `levelingclips.com` (GoDaddy DNS: A @ → 76.76.21.21,
   CNAME www → cname.vercel-dns.com). Put the Supabase URL + anon key in `dashboard/config.js`.
8. **Mac** — unzip, then in Terminal: `bash ~/Downloads/ownvista-hq-main/mac/install.sh` (after downloading the repo zip from GitHub). It installs everything free (Python 3.12 via uv, Kokoro narrator voice, Inter fonts, ffmpeg), walks you through the keys one at a time (`mac/setup_env.py`), copies the code to `~/TenFourTapes/hq` and schedules the runner every 30 min. Rendering is built in (`mac/render.py`: Groq Whisper transcript + loudness → picks the action → episode / Shorts / Reels). During the approval window every fresh render goes back to Pending, so you approve the exact video before it posts.
9. **YouTube API audit** — until Google approves the app, API uploads land as Private; the Publisher flags each one.
   Request the audit (free) from the YouTube API Services audit form.

## Gleamstone workspace (levelingclips.com/gleamstone)

A separate workspace for Gleamstone Commercial Cleaning: its own page, brand and tabs (Today, Prospects, Outreach,
Quotes, Cleaners, Agents, Settings). The switch at the top of either page flips between Ten-Four Tapes and Gleamstone,
and HQ opens in whichever one you used last. Gleamstone data lives only in `gs_*` tables and `gs_*` settings, and its
agents log as `gs_*`, so nothing crosses over.

| Agent | When | Job |
|---|---|---|
| Prospect Scout | every 6h | Google News for leases, openings and moves in towns within 20 mi of 01890 |
| Map Scout | weekly | OpenStreetMap: dealerships, medical/dental, gyms, offices in range (150 new a week) |
| Contact Finder | every 2h | Finds an email printed on the business's own site. Never guesses addresses |
| Writer | every 2h | Drafts intros (best fit first) and answers to replies you log |
| Sender | hourly, weekdays 8–5 ET | Sends approved email via Brevo (free, 300/day) from bobby@gleamstonecleaning.com, daily cap, auto follow-ups on day 4 and 9, stops on reply/bounce |
| Recruiter | weekly | Writes the cleaner job post (you post it) |
| Brief | 8am ET | Morning summary on the dashboard + emailed to bobby@gleamstonecleaning.com |

Rules: email only, no call offers, no "same crew" promises, no prices in first emails, no spending.
Setup: run `supabase/gleamstone.sql`; add the `BREVO_API_KEY` secret (Brevo account with gleamstonecleaning.com
authenticated); add a mailing address in Gleamstone Settings. Zoho's free plan has no IMAP, so replies are
logged with "Log a reply" on the dashboard.
