# Ownvista HQ — setup (Bobby does these steps himself)

About 90 minutes end to end. Never paste a key into chat, email or code: keys go only into
GitHub Actions secrets, Vercel environment variables, or your password manager.

Checklist:

- [ ] 1. Supabase project + one SQL paste + RLS check + your login user
- [ ] 2. Groq API key
- [ ] 3. GitHub private repo + push the code
- [ ] 4. Gmail (Google Cloud Internal OAuth client + refresh token)
- [ ] 5. GitHub Actions secrets and variables
- [ ] 6. Vercel project + levelingclips.com + films.villacinema.com
- [ ] 7. GoDaddy DNS records
- [ ] 8. Villa Cinema: Zoho, SPF/DKIM/DMARC, Stripe, MiniMax, music, footer address
- [ ] 9. First runs ("Done means")

---

## 1. Supabase (free plan)

1. Go to **supabase.com** → **Start your project** → sign up with **bobbybands888@gmail.com**
   (this must be your Supabase account email: the free built-in email only sends magic links to project team members).
2. **New project** → Organization: your personal org → Name `ownvista-hq` → Database password: generate one and save it
   in your password manager → Region: **East US (North Virginia)** → Plan: **Free** → **Create new project**. Wait ~2 minutes.
   (Free plan allows 2 active projects. If you already have 2, pause one first.)
3. Left sidebar → **SQL Editor** → **New query**. On your Mac run this to copy the whole schema:

   ```bash
   pbcopy < ~/Documents/ownvista-hq/supabase/schema.sql
   ```

   Paste into the editor (Cmd+V) → **Run**. You should see "Success. No rows returned". It is safe to run again.
4. **Prove the lock works (RLS check).** Get three values from **Project Settings** → **API Keys**
   (and **Data API** for the URL): Project URL, **Publishable key** (`sb_publishable_…`), **Secret key** (`sb_secret_…`,
   click **Reveal**). Then run:

   ```bash
   cd ~/Documents/ownvista-hq && node scripts/rls-check.js
   ```

   Paste the three values when asked (keys are hidden while you type and never saved). It proves:
   (a) the publishable/anon key reads **zero rows** from all 30 tables and can't write, call agent functions or touch
   storage; (b) a throwaway signed-in user who isn't you also reads zero rows and changes nothing; (c) the secret key can
   write and read every table and bucket. It plants a marked canary row in every table first so "zero rows" is real,
   then deletes the canaries, test files and the throwaway user. It must end with **"N/N checks passed"**.
   If anything fails, stop and send me the FAIL lines (never the keys).
5. **Authentication** → **Users** → **Add user** → **Create new user** → email `bobbybands888@gmail.com`,
   any strong password (you won't use it), tick **Auto Confirm User** → **Create user**.
6. **Authentication** → **Sign In / Providers** → **Email** stays enabled → turn **OFF** "Allow new users to sign up" → **Save**.
7. **Authentication** → **URL Configuration** → Site URL `https://levelingclips.com` → **Redirect URLs** → **Add URL** →
   `https://levelingclips.com/**` → **Save**.
8. Keep these three values for later:
   - **Project URL** → `https://xxxx.supabase.co`
   - **Publishable key** (`sb_publishable_…`) → Vercel only
   - **Secret key** (`sb_secret_…`) → GitHub secret + Vercel only. Treat it like a password.

   Clear your terminal after the RLS check (Cmd+K).

## 2. Groq (free tier)

1. **console.groq.com** → sign up.
2. **Settings** → **Data Controls** → turn on **Zero Data Retention**.
3. **API Keys** → **Create API Key** → name `ownvista-hq` → copy it straight into GitHub (step 5).

Verified 2026-09-30: `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and `qwen/qwen3.8-27b` (vision) are on the free plan at
30 requests/min, 1,000/day, 8,000 tokens/min, 200,000 tokens/day each. The agents cap themselves at 150,000 tokens/day per model.

## 3. GitHub private repo

1. **github.com/new** → Owner `BobbyBands888` → name `ownvista-hq` → **Private** → do not add a README → **Create repository**.
2. In Terminal:

   ```bash
   cd ~/Documents/ownvista-hq && git remote add origin https://github.com/BobbyBands888/ownvista-hq.git && git push -u origin main
   ```

Private repo minutes: 2,000/month free. The World view shows the month's total.

## 4. Gmail — drafts only (Google Cloud, on the nashvillebuys.com Workspace)

1. Sign in to **console.cloud.google.com** as **hello@nashvillebuys.com** (or your Workspace admin).
2. Project picker → **New project** → name `ownvista-hq` → Organization `nashvillebuys.com` → **Create**.
3. **APIs & Services** → **Library** → search **Gmail API** → **Enable**.
4. **APIs & Services** → **OAuth consent screen** (Google Auth Platform) → **Get started** → App name `Ownvista HQ`,
   support email hello@nashvillebuys.com → Audience: **Internal** → contact email → **Create**.
5. **Data Access** → **Add or remove scopes** → paste `https://www.googleapis.com/auth/gmail.modify` → **Update** → **Save**.
6. **Clients** → **Create client** → Application type **Web application** → name `ownvista-hq` →
   Authorized redirect URIs → **Add URI** → `https://developers.google.com/oauthplayground` → **Create**.
   Keep the Client ID and Client secret open.
7. Open **developers.google.com/oauthplayground** → gear icon (top right) → tick **Use your own OAuth credentials** →
   paste Client ID and Client secret → close.
8. Left side, "Input your own scopes": `https://www.googleapis.com/auth/gmail.modify` → **Authorize APIs** →
   sign in as **hello@nashvillebuys.com** → **Allow**.
9. **Exchange authorization code for tokens** → copy the **Refresh token** into GitHub (step 5). Internal apps' refresh
   tokens don't expire after 7 days.
10. Gmail → Settings → **Accounts** → "Send mail as": make sure **hello@getownvista.com** and **quotes@getownvista.com**
    are listed, so drafts for Follow-Up mail show the right From address.

Why this is safe: `gmail.modify` technically allows sending, so the code is the lock. `agents/lib/gmail.js` refuses any
request that isn't on a short drafting allowlist, and `test/no-send.test.js` runs before every job and fails it if any
send-capable Gmail code appears.

## 5. GitHub Actions secrets and variables

Repo → **Settings** → **Secrets and variables** → **Actions**.

**Secrets** tab → **New repository secret** for each:

| Secret | Value |
|---|---|
| `SUPABASE_URL` | Project URL from 1.8 |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret key `sb_secret_…` from 1.8 |
| `GROQ_API_KEY` | from 2.3 |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | from 4.6 |
| `GMAIL_REFRESH_TOKEN` | from 4.9 |
| `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET` / `ZOHO_REFRESH_TOKEN` | from 8.2 |
| `MINIMAX_API_KEY` | from 8.5 |
| `STRIPE_RESTRICTED_KEY` | from 8.4 (`rk_live_…`) |
| `VC_PAYMENT_LINK` | your Payment Link URL (`https://buy.stripe.com/…`) |
| `VC_PAYMENT_LINK_ID` | optional: `plink_…` so only that link's payments count |
| `TAVILY_API_KEY` | **only after you approve web search** (see 8.7) |
| `ANTHROPIC_API_KEY` | optional, only if you switch `LLM_PROVIDER` to `anthropic` |

**Variables** tab (optional; defaults in brackets): `LLM_PROVIDER` [groq], `GMAIL_USER` [hello@nashvillebuys.com],
`GMAIL_ALIASES` [hello@getownvista.com,quotes@getownvista.com], `ZOHO_DC` [com], `ZOHO_FROM` [hello@villacinema.com],
`VC_DKIM_SELECTORS` [zmail,zoho,default].

## 6. Vercel

1. **vercel.com/new** → **Import** `BobbyBands888/ownvista-hq` (grant Vercel access to that repo if asked).
2. Framework preset: **Other**. Leave build settings as they are (`vercel.json` sets them).
3. **Environment Variables**: `SUPABASE_URL`, `SUPABASE_ANON_KEY` (= the **publishable** key), `SUPABASE_SERVICE_ROLE_KEY`
   (= the **secret** key; only the upload/unsubscribe functions use it, server-side) → **Deploy**.
4. Project → **Settings** → **Domains** → add `levelingclips.com` (accept adding `www.levelingclips.com` redirecting to it),
   then add `films.villacinema.com`. Vercel shows the exact DNS values for each; use those in step 7.

## 7. DNS

**levelingclips.com at GoDaddy:** GoDaddy → **My Products** → levelingclips.com → **DNS** → **Manage DNS**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `76.76.21.21` (or the A value Vercel shows) | 1 hour |
| CNAME | `www` | the CNAME value Vercel shows (e.g. `xxxx.vercel-dns-017.com`) | 1 hour |

Delete any other `A`/`AAAA` records on `@` and GoDaddy "Parked"/forwarding. Don't touch MX records.

**films.villacinema.com** (at whichever DNS host villacinema.com uses): CNAME `films` → the value Vercel shows.

Vercel's Domains page turns green within minutes to an hour. HTTPS is automatic.

## 8. Villa Cinema

1. **Zoho plan check.** Zoho Mail Admin Console → **Subscription**. The Forever Free plan excludes IMAP/POP and
   doesn't reliably include API access; hello@villacinema.com needs **Mail Lite or higher**. The preflight (step 9)
   calls the Zoho API and reports clearly if the plan blocks it.
2. **Zoho API client:** **api-console.zoho.com** → **Add Client** → **Self Client** → **Create**. Copy Client ID + Secret.
   Tab **Generate Code** → Scope `ZohoMail.messages.ALL,ZohoMail.accounts.READ,ZohoMail.folders.READ` → Time **10 minutes**
   → description `ownvista-hq` → **Create** → choose the villacinema.com account → copy the code. Within 10 minutes run:

   ```bash
   cd ~/Documents/ownvista-hq && node scripts/zoho-token.js
   ```

   Paste the three values when asked; it prints the refresh token → GitHub secret `ZOHO_REFRESH_TOKEN`.
   If your Zoho account is on the EU/IN/AU data center, answer that at the first prompt and set variable `ZOHO_DC`.
3. **SPF, DKIM, DMARC for villacinema.com** (Zoho Admin → **Domains** → villacinema.com → **Email Configuration**):
   - SPF: TXT `@` → exactly the value Zoho shows (contains `include:zohomail.com` or `include:zoho.com`)
   - DKIM: **Add** selector (e.g. `zmail`) → publish the TXT at `zmail._domainkey` → **Verify**
   - DMARC: TXT `_dmarc` → `v=DMARC1; p=none; rua=mailto:hello@villacinema.com`

   The preflight checks all three through public DNS. If you used a DKIM selector other than zmail/zoho/default,
   set variable `VC_DKIM_SELECTORS`.
4. **Stripe:** Product catalog → **+ Add product** "Villa Cinema film" with your price → **Payment Links** → **New** →
   that product → **Create link** → copy the URL → secret `VC_PAYMENT_LINK` (and the `plink_…` id → `VC_PAYMENT_LINK_ID`).
   **Developers** → **API keys** → **Create restricted key** → name `ownvista-hq read` → **Checkout Sessions: Read**,
   everything else **None** → **Create** → secret `STRIPE_RESTRICTED_KEY`. The agents can only read completed payments.
5. **MiniMax:** **platform.minimax.io** → sign up → **Billing** → pay-as-you-go → top up a prepaid balance of at most
   **$150** (a prepaid balance is a hard ceiling; set any monthly limit the console offers to $150 too) → **API Keys** →
   create → secret `MINIMAX_API_KEY`. Verified prices 2026-09-30: MiniMax-H3 768P $0.08/s; 2K regeneration $0.05/s output
   + $0.05/s input video. The code caps spend at $20 per paid film (incl. 2K upgrade and retries), $25/week for samples,
   $150/month overall, enforced by the database.
6. **Dashboard → Villa Cinema:**
   - Footer mailing address (required by CAN-SPAM; nothing sends without it).
   - Upload 2–5 **royalty-free/CC0 music tracks** you have a license for, plus a `.txt` license note for each.
   - Upload 8–12 **sample property photos** you have rights to (for the test order).
   - Countries: only United States is on. US regions: Hawaii, Florida, USVI, Puerto Rico, US mountain resorts.
7. **Web search (prospect discovery) — needs your approval.** Proposal: **Tavily** free plan, 1,000 credits/month,
   no credit card (verified 2026-09-30). Brave's free tier ended in Feb 2026 and needs a card; Google Programmable Search
   is closed to new customers. To approve: sign up at **tavily.com** → copy API key → secret `TAVILY_API_KEY` → dashboard
   → Villa Cinema → tick "Web search approved". Until then, add public directory pages or prospects by hand in the Villa view.

## 9. First runs ("Done means")

GitHub → repo → **Actions** → **Ownvista HQ** → **Run workflow** → pick the agent → **Run workflow**.

1. `captest` — tries to exceed every spend and send cap against your real database; all must be refused. It cleans up after itself.
2. `villa_preflight` — must say "preflight passed" (dashboard → Villa → Preflight details).
3. `researcher`, `strategist`, `scout`, `analyst`, `operator`, `builder`, `judge`, `learner`, `villa_outreach`, `villa_studio` — one each.
4. Send a test email from any personal address to **hello@nashvillebuys.com**. Within the hour a draft appears in the thread
   (Gmail → Drafts) and in the dashboard's Email view.
5. `villa_test_email` — sends one first-touch sample email to bobbybands888@gmail.com only.
6. `villa_test_order` — creates a test order from your sample photos. Then run `villa_studio` (or wait for the hourly runs)
   until the film is in **Needs you** → watch it → **Approve & deliver** → it arrives at bobbybands888@gmail.com.
   The Villa view's Spend table shows every charge.
7. Open **https://levelingclips.com** → magic link → World shows all 10 agents healthy.
8. When you're ready for real outreach: dashboard → Villa Cinema → tick **Outreach on**. Warm-up starts at 5 first emails/day
   and reaches 20/day after two weeks; sending runs Mon–Fri 9am–5pm ET.

## Turning things off

- Stop cold outreach: dashboard → Villa Cinema → untick **Outreach on** (first emails and follow-ups stop; replies to
  people who wrote in, order emails and film deliveries continue).
- Stop all Villa sending: the system auto-pauses everything on bounces over 5% or any complaint; you resume from Needs you.
- Pause one agent: Supabase → Table editor → `agents` → set `enabled` to false.
- Stop everything: GitHub → Actions → Ownvista HQ → **…** → **Disable workflow**.
