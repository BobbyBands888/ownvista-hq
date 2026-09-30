-- Launcher + Asset Studio (Sep 30, 2026). Safe to run more than once.

-- 1. Launches: one public page + Stripe Payment Link per approved idea.
create table if not exists public.launches (
  id uuid primary key default gen_random_uuid(),
  idea_id uuid references public.ideas(id) on delete set null,
  experiment_id uuid references public.experiments(id) on delete set null,
  slug text not null unique,
  title text not null,
  price_usd numeric,
  stripe_product_id text,
  stripe_price_id text,
  payment_link_id text,
  payment_link_url text,
  page_html text,
  product_asset_id uuid references public.assets(id) on delete set null,
  delivery_token text,
  status text not null default 'draft' check (status in ('draft','needs_bobby','waiting_key','live','killed')),
  goal_sales int not null default 5,
  sales int not null default 0,
  revenue numeric not null default 0,
  note text,
  created_at timestamptz not null default now(),
  launched_at timestamptz,
  killed_at timestamptz
);
create index if not exists launches_status_idx on public.launches (status);
-- (re-runs) make sure later columns exist
alter table public.launches add column if not exists product_asset_id uuid references public.assets(id) on delete set null;
alter table public.launches add column if not exists delivery_token text;

-- 2. Asset packs made by the Asset Studio (itch.io first).
create table if not exists public.asset_packs (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  theme text,
  style text,
  platform text not null default 'itchio',
  status text not null default 'planned' check (status in ('planned','generating','packaging','ready','published','rejected','killed')),
  items jsonb not null default '[]',
  page_copy text,
  tags text[] not null default '{}',
  price_usd numeric not null default 3,
  preview_path text,
  zip_path text,
  itch_url text,
  itch_game_id bigint,
  views int not null default 0,
  downloads int not null default 0,
  sales int not null default 0,
  revenue numeric not null default 0,
  images_made int not null default 0,
  feedback text,
  created_at timestamptz not null default now(),
  ready_at timestamptz,
  published_at timestamptz
);
create index if not exists asset_packs_status_idx on public.asset_packs (status, created_at desc);

-- 3. Ledger rows from Stripe/itch carry a unique reference so a sale is never counted twice.
alter table public.ledger add column if not exists ref text;
create unique index if not exists ledger_ref_key on public.ledger (ref) where ref is not null;

-- 4. Row-level security: Bobby only (agents use the service role).
do $$
declare t text;
begin
  foreach t in array array['launches','asset_packs'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists bobby_all on public.%I', t);
    execute format('create policy bobby_all on public.%I for all to authenticated using (public.is_bobby()) with check (public.is_bobby())', t);
  end loop;
end $$;

-- 5. Private storage for packs (zips up to 50 MB, previews and item PNGs).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('asset-packs', 'asset-packs', false, 52428800, array['image/png','image/jpeg','application/zip','text/plain'])
on conflict (id) do nothing;
drop policy if exists bobby_asset_objects on storage.objects;
create policy bobby_asset_objects on storage.objects for all to authenticated
  using (bucket_id = 'asset-packs' and public.is_bobby())
  with check (bucket_id = 'asset-packs' and public.is_bobby());

-- 6. The two new crew members.
insert into public.agents (id, name, description, schedule, sort) values
  ('launcher', 'Launcher', 'Turns approved ideas into live pages with a Stripe Payment Link, tracks sales, kills what misses its goal', 'Hourly, 24/7', 11),
  ('asset_studio', 'Asset Studio', 'Researches itch.io best sellers, makes game asset packs on the free image allowance, packages them for Bobby to publish', 'Hourly, 24/7 (free daily image allowance)', 12)
on conflict (id) do update set name = excluded.name, description = excluded.description, schedule = excluded.schedule, sort = excluded.sort;

-- 7. Default goals (change any time in the kv table).
insert into public.kv (key, value) values
  ('launch_rules', '{"goal_sales": 5, "days": 14}'),
  ('asset_rules', '{"images_per_day": 100, "items_per_pack": 16, "max_waiting": 3, "goal_sales": 5, "days": 30}')
on conflict (key) do nothing;
