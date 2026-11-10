# Ten-Four Tapes HQ (levelingclips.com)

Ten agents that run the Ten-Four Tapes YouTube channel and Facebook page. $0 stack: Groq free tier,
Supabase free org, GitHub Actions (one hourly job), Vercel Hobby, free Google + Meta APIs.

## The agents

| Agent | Where | When | Job |
|---|---|---|---|
| Research | cloud | daily | Studies top bodycam channels (EWU, Code Blue Cam, Dr Insanity + discovered ones) → playbook |
| Scout | cloud | every 3h | Finds footage leads: agency YouTube channels, DVIDS, news. Scores action 1–10, screens minors, de-dupes incidents |
| Outreach | cloud | weekdays 9am/1pm ET | Sends public records requests from bobbybands888 (cap 10/day, 2/agency/day). Finds agency records emails on official sites |
| Records Tracker | cloud | every 2h | Reads agency replies, catches download links + expiry, flags fee quotes/questions to you, follows up after 10 days |
| Case Desk | cloud | every 6h | Researches who / why / how it ended for every case (agency release + news, every fact sourced). Maker won't script a case without it. Re-checks open cases on posted episodes every 14 days and alerts you with a description update when an outcome lands |
| Maker | cloud | 2×/day | Turns obtained footage into plans: episode + 3 Shorts (Part 1/2/3) + standalone FB Reels, using the playbook |
| Compliance | cloud | hourly | The gate: provenance proof, credit line, no minors, no death on camera, platform policy review |
| Publisher | Mac | every 30 min | Renders with `mac/render.py`, uploads to YouTube + FB Reels (1 Short/day, 3 Reels/day, 2 episodes/week) |
| Analytics | cloud | daily | Pulls our YouTube + Facebook numbers → "what works for us" into the playbook |
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
