-- Ten-Four Tapes HQ — full schema. Run once in a NEW Supabase project (free org).
-- Safe to re-run: everything uses IF NOT EXISTS / ON CONFLICT.

create extension if not exists pgcrypto;

-- ---------- core tables ----------
create table if not exists agent_runs (
  id uuid primary key default gen_random_uuid(),
  agent text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',          -- running | ok | error | skipped
  summary text,
  error text
);
create index if not exists agent_runs_agent_idx on agent_runs (agent, started_at desc);

create table if not exists alerts (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  agent text not null,
  level text not null default 'info',               -- info | warn | urgent
  message text not null,
  resolved boolean not null default false
);

create table if not exists settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

-- ---------- research ----------
create table if not exists competitor_channels (
  channel_id text primary key,
  title text,
  handle text,
  subscribers bigint,
  total_views bigint,
  video_count int,
  is_seed boolean not null default false,
  last_checked timestamptz,
  notes text
);

create table if not exists competitor_videos (
  video_id text primary key,
  channel_id text references competitor_channels(channel_id) on delete cascade,
  title text,
  published_at timestamptz,
  duration_s int,
  views bigint,
  likes bigint,
  comments bigint,
  views_per_day numeric,
  checked_at timestamptz not null default now()
);
create index if not exists competitor_videos_vpd_idx on competitor_videos (views_per_day desc);

create table if not exists playbook (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  source text not null,                              -- research | analytics
  category text not null,                            -- title | length | hook | topic | format | thumbnail | cadence | other
  insight text not null,
  evidence jsonb,
  active boolean not null default true
);

-- ---------- footage pipeline ----------
create table if not exists agencies (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  state text,
  records_email text,                                -- only verified addresses; outreach skips agencies without one
  portal_url text,                                   -- GovQA/NextRequest etc. (manual)
  releases_bodycam boolean,
  notes text,
  last_request_at timestamptz
);

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  title text not null,
  agency_name text,
  state text,
  incident_date date,
  summary text,
  source_url text unique,
  source_type text not null,                         -- agency_release | prosecutor_release | dvids_public_domain | news_tip
  action_score int,                                  -- 1-10, how much real action on screen
  category text,                                     -- enforcement | case_story | rescue | other
  involves_minor boolean,
  status text not null default 'new',                -- new | queued_request | requested | obtained | rejected | used | skipped
  notes text
);
create index if not exists leads_status_idx on leads (status, action_score desc);

create table if not exists records_requests (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  lead_id uuid references leads(id) on delete set null,
  agency_id uuid references agencies(id) on delete set null,
  to_email text,
  subject text,
  body text,
  sent_at timestamptz,
  gmail_thread_id text,
  status text not null default 'draft',              -- draft | sent | acknowledged | fee_quoted | clarify | denied | fulfilled | closed
  followups int not null default 0,
  last_activity_at timestamptz,
  fee_quote text,
  download_links jsonb,
  notes text
);
create index if not exists records_requests_status_idx on records_requests (status);

-- ---------- content ----------
create table if not exists content (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  lead_id uuid references leads(id) on delete set null,
  kind text not null,                                -- episode | short | reel
  parent_id uuid references content(id) on delete cascade,  -- shorts/reels point at their episode
  part int,
  case_name text,
  title text,
  description text,
  tags text[],
  script jsonb,
  source_type text,
  source_credit text,
  source_urls text[],
  compliance_status text not null default 'pending', -- pending | pass | fail
  compliance_notes text,
  approval_status text not null default 'pending',   -- pending | approved | rejected | not_required
  status text not null default 'scripted',           -- scripted | rendered | posted | failed
  media_path text,                                   -- path on Bobby's Mac after render
  youtube_id text,
  facebook_id text,
  publish_note text,
  posted_at timestamptz,
  scheduled_for timestamptz
);
create index if not exists content_queue_idx on content (status, compliance_status, approval_status);
-- Scorecard: every post graded once at 48h (A-D vs the same format's history)
alter table content add column if not exists score_grade text;      -- A | B | C | D | ? (no metrics)
alter table content add column if not exists score_views bigint;    -- views at ~48h
alter table content add column if not exists scored_at timestamptz;
alter table content add column if not exists score_note text;

create table if not exists metrics (
  id uuid primary key default gen_random_uuid(),
  captured_on date not null default current_date,
  platform text not null,                            -- youtube | facebook
  external_id text not null,                         -- video id / reel id / 'channel' / 'page'
  content_id uuid references content(id) on delete set null,
  views bigint,
  likes bigint,
  comments bigint,
  shares bigint,
  watch_minutes numeric,
  followers bigint,
  raw jsonb,
  unique (captured_on, platform, external_id)
);

-- ---------- default settings ----------
insert into settings (key, value) values
  ('approval_required_until', '"2026-11-23"'),
  ('outreach_daily_cap', '10'),
  ('followup_after_days', '10'),
  ('max_followups', '3'),
  ('signature_name', '"Bobby Cipro"'),
  ('channel_name', '"Ten-Four Tapes"'),
  ('youtube_channel_handle', '"@tenfourtapes"'),
  ('facebook_page', '"tenfourtapes"'),
  ('posting_paused', 'false'),
  ('reels_per_day', '3'),
  ('shorts_per_day', '3'),
  ('episodes_per_week', '2')
on conflict (key) do nothing;

insert into agencies (name, state, releases_bodycam, notes) values
  ('Volusia County Sheriff''s Office', 'FL', true, 'Posts bodycam to YouTube/Facebook; request raw files'),
  ('Marion County Sheriff''s Office', 'FL', true, 'Posts bodycam to YouTube/Facebook; request raw files'),
  ('Office of the State Attorney, 9th Circuit', 'FL', true, 'Source of Sarah Boone records')
on conflict (name) do nothing;

insert into competitor_channels (channel_id, title, is_seed) values
  ('seed:Explore With Us', 'Explore With Us', true),
  ('seed:Code Blue Cam', 'Code Blue Cam', true),
  ('seed:Dr Insanity', 'Dr Insanity', true)
on conflict (channel_id) do nothing;

-- ---------- security: only Bobby's login can read/write from the dashboard ----------
do $$
declare t text;
begin
  foreach t in array array['agent_runs','alerts','settings','competitor_channels','competitor_videos',
                           'playbook','agencies','leads','records_requests','content','metrics']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists owner_all on %I', t);
    execute format($p$create policy owner_all on %I for all to authenticated
                     using ((auth.jwt() ->> 'email') = 'bobbybands888@gmail.com')
                     with check ((auth.jwt() ->> 'email') = 'bobbybands888@gmail.com')$p$, t);
    execute format('grant select, insert, update, delete on %I to authenticated', t);
    execute format('grant all on %I to service_role', t);
  end loop;
end $$;
