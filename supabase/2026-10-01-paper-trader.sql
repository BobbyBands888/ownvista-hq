-- Paper Trader (Oct 1, 2026). PAPER MONEY ONLY. Safe to run more than once.

-- 1. Every simulated trade, including picks the risk rules rejected (status 'rejected').
create table if not exists public.pt_trades (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  setup text,
  kind text not null default 'stock' check (kind in ('stock','call','put')),
  contract jsonb,
  qty numeric,
  entry_price numeric,
  entry_underlying numeric,
  entry_at timestamptz,
  entry_day date,
  stop numeric,
  target numeric,
  bearish boolean not null default false,
  hold_days int,
  cost_usd numeric,
  risk_usd numeric,
  confidence int,
  thesis text,
  signals jsonb,
  mark_price numeric,
  marked_at timestamptz,
  mfe numeric default 0,
  mae numeric default 0,
  exit_price numeric,
  exit_underlying numeric,
  exit_at timestamptz,
  exit_reason text,
  pnl numeric,
  r_multiple numeric,
  status text not null default 'open' check (status in ('open','closed','rejected')),
  reject_reason text,
  review jsonb,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists pt_trades_status_idx on public.pt_trades (status, entry_at desc);
create index if not exists pt_trades_day_idx on public.pt_trades (entry_day);

-- 2. Lessons the trader writes after its mistakes and reads before every pick.
create table if not exists public.pt_lessons (
  id uuid primary key default gen_random_uuid(),
  lesson text not null,
  setup text,
  mistake text,
  evidence text,
  hits int not null default 1,
  origin text not null default 'postmortem',
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists pt_lessons_active_idx on public.pt_lessons (active, created_at desc);

-- 3. Daily equity vs just holding SPY.
create table if not exists public.pt_equity (
  day date primary key,
  equity numeric not null,
  cash numeric not null,
  positions_value numeric not null default 0,
  open_count int not null default 0,
  spy_close numeric,
  bench_equity numeric,
  drawdown numeric,
  created_at timestamptz not null default now()
);

-- 4. Row-level security: Bobby only (agents use the service role).
do $$
declare t text;
begin
  foreach t in array array['pt_trades','pt_lessons','pt_equity'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists bobby_all on public.%I', t);
    execute format('create policy bobby_all on public.%I for all to authenticated using (public.is_bobby()) with check (public.is_bobby())', t);
  end loop;
end $$;

-- 5. The new crew member.
insert into public.agents (id, name, description, schedule, sort) values
  ('paper_trader', 'Paper Trader', 'Simulated stock, penny-stock and options trades with hard risk rules; learns from every closed trade. Paper money only, never a real order.', 'Weekdays hourly 10am–4pm ET (paper money)', 13)
on conflict (id) do update set name = excluded.name, description = excluded.description, schedule = excluded.schedule, sort = excluded.sort;
