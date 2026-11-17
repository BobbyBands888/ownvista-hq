-- Gleamstone workspace for HQ. Run once in the same Supabase project as Ten-Four Tapes (SQL Editor → paste → Run).
-- Safe to re-run. Every Gleamstone table starts with gs_ so it never mixes with Ten-Four Tapes data.

create extension if not exists pgcrypto;

-- businesses we might clean for
create table if not exists gs_prospects (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  name text not null,
  category text,                                   -- office | medical | dealership | showroom | retail | gym | warehouse | other
  address text,
  town text,
  lat numeric,
  lon numeric,
  distance_mi numeric,
  website text,
  email text,
  email_source text,                               -- page the address was printed on
  contact_name text,
  source text not null default 'manual',          -- lease_news | map | manual
  source_url text,
  signal text,                                     -- why now, e.g. "signed a 6,000 sf lease at 10 Main St"
  signal_date date,
  sqft int,
  fit_score int,                                   -- 1-10
  status text not null default 'new',             -- new | no_email | drafted | contacted | replied | interested | quoted | won | lost | do_not_contact
  enrich_tries int not null default 0,
  last_contact_at timestamptz,
  notes text
);
create unique index if not exists gs_prospects_name_town on gs_prospects (lower(name), lower(coalesce(town,'')));
create index if not exists gs_prospects_status on gs_prospects (status, fit_score desc);

-- every email in and out
create table if not exists gs_emails (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  prospect_id uuid references gs_prospects(id) on delete cascade,
  cleaner_id uuid,
  direction text not null default 'out',          -- out | in
  kind text not null default 'intro',             -- intro | followup | reply | quote | inbound
  step int not null default 0,                     -- 0 intro, 1 first follow-up, 2 second follow-up
  to_email text,
  subject text,
  body text,
  approval_status text not null default 'pending', -- pending | approved | rejected
  status text not null default 'draft',           -- draft | sent | failed | bounced | cancelled | logged
  send_after timestamptz,
  sent_at timestamptz,
  provider_id text,
  note text
);
create index if not exists gs_emails_queue on gs_emails (status, approval_status, send_after);

-- quotes built on the dashboard
create table if not exists gs_quotes (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  prospect_id uuid references gs_prospects(id) on delete set null,
  business_name text,
  space_type text,
  sqft int,
  visits_per_week int,
  restrooms int,
  extras jsonb,
  per_visit numeric,
  monthly numeric,
  notes text,
  status text not null default 'draft'            -- draft | sent | accepted | declined
);

-- people who could do the cleaning
create table if not exists gs_cleaners (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  name text not null,
  email text,
  phone text,
  towns text,
  availability text,
  has_car boolean,
  experience text,
  source text,
  status text not null default 'lead',            -- lead | contacted | interview | ready | active | passed
  notes text
);

-- Gleamstone settings (shared settings table, gs_ keys)
insert into settings (key, value) values
  ('gs_home_zip', '"01890"'),
  ('gs_home_lat', '42.4526'),
  ('gs_home_lon', '-71.1373'),
  ('gs_radius_mi', '20'),
  ('gs_daily_cap', '15'),
  ('gs_followup_days', '[4, 9]'),
  ('gs_approvals', 'true'),
  ('gs_sending_paused', 'false'),
  ('gs_mailing_address', '""'),
  ('gs_excluded', '["Lawless Chrysler Dodge Jeep Ram"]'),
  ('gs_rates', '{"hourly":45,"min_visit":85,"restroom_min":15,"disc3":5,"disc5":10,"office":2500,"medical":1800,"dealership":3500,"showroom":3500,"retail":2500,"gym":2000,"warehouse":5000,"other":2500}')
on conflict (key) do nothing;

-- same lock as the rest of HQ: only Bobby's login can read or write from the dashboard
do $$
declare t text;
begin
  foreach t in array array['gs_prospects','gs_emails','gs_quotes','gs_cleaners']
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
