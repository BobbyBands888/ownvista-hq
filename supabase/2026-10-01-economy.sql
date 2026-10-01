-- Economy + Architect (Oct 1, 2026). Safe to run more than once.

-- 1. Daily P&L per agent (shadow cost = what usage would cost on paid tiers + Bobby's time; never billed).
create table if not exists public.agent_pnl (
  day date not null,
  agent text not null,
  lane text,
  tokens int not null default 0,
  images int not null default 0,
  minutes numeric not null default 0,
  approvals int not null default 0,
  revenue numeric not null default 0,
  shadow_cost numeric not null default 0,
  net numeric not null default 0,
  primary key (day, agent)
);

-- 2. Crew the Architect deploys. Data only: a clone runs an existing agent, a new one runs agents/spawned.js.
create table if not exists public.crew_specs (
  id text primary key check (id ~ '^x_[a-z0-9_]{3,30}$'),
  kind text not null check (kind in ('clone','new')),
  base text,
  name text not null,
  lane text not null,
  mission text not null,
  blocks text[] not null default '{}',
  reads text[] not null default '{}',
  schedule jsonb not null default '{}',
  token_budget int not null default 8000,
  expected_money text,
  kill_metric jsonb not null default '{}',
  why text,
  status text not null default 'probation' check (status in ('probation','active','retired')),
  probation_ends date,
  stats jsonb not null default '{}',
  created_by text not null default 'architect',
  created_at timestamptz not null default now(),
  retired_at timestamptz,
  retire_reason text
);
create index if not exists crew_specs_status_idx on public.crew_specs (status);

-- 3. Row-level security: Bobby only (agents use the service role).
do $$
declare t text;
begin
  foreach t in array array['agent_pnl','crew_specs'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists bobby_all on public.%I', t);
    execute format('create policy bobby_all on public.%I for all to authenticated using (public.is_bobby()) with check (public.is_bobby())', t);
  end loop;
end $$;

-- 4. The two new crew members.
insert into public.agents (id, name, description, schedule, sort) values
  ('economist', 'Economist', 'Keeps the books: P&L per agent, runway vs real bills, moves budget toward lanes that earn. Budgets only, never permissions.', 'Daily 11pm ET (books, budgets)', 14),
  ('architect', 'Architect', 'Clones proven agents where a paying lane is bottlenecked, designs new crew on probation, retires what does not pay.', 'Sundays 7pm ET (shapes the crew)', 15)
on conflict (id) do update set name = excluded.name, description = excluded.description, schedule = excluded.schedule, sort = excluded.sort;

-- 5. Settings (edit on the Economy page). Bills start at $0: Bobby fills in what he really pays.
insert into public.kv (key, value) values
  ('economy_rules', '{}'),
  ('economy_burn', '[{"name":"Vercel","usd_month":0},{"name":"Domains (levelingclips, villacinema, nashvillebuys)","usd_month":0},{"name":"Zoho Mail","usd_month":0},{"name":"Supabase","usd_month":0},{"name":"Groq / Cloudflare / GitHub (free tiers)","usd_month":0}]')
on conflict (key) do nothing;

-- 6. Researcher briefs: findings routed to the agents that can use them (added Oct 1, after the first block).
create table if not exists public.agent_briefs (
  id uuid primary key default gen_random_uuid(),
  agent text not null,
  knowledge_id uuid not null references public.knowledge(id) on delete cascade,
  note text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '7 days',
  unique (agent, knowledge_id)
);
create index if not exists agent_briefs_agent_idx on public.agent_briefs (agent, created_at desc);
alter table public.agent_briefs enable row level security;
drop policy if exists bobby_all on public.agent_briefs;
create policy bobby_all on public.agent_briefs for all to authenticated using (public.is_bobby()) with check (public.is_bobby());
update public.agents set schedule = 'Hourly, 24/7 (learns and briefs the crew)' where id = 'researcher';
update public.agents set schedule = 'Hourly check for new gaps; full crew review Sundays 7pm ET' where id = 'architect';
