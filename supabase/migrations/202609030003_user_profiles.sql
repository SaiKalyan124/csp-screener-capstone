create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  mode text not null default 'guided' check (mode in ('guided', 'custom')),
  risk_level text not null default 'medium' check (risk_level in ('low', 'medium', 'high')),
  available_capital numeric not null default 50000 check (available_capital >= 1000),
  dte_min integer not null default 20 check (dte_min between 1 and 365),
  dte_max integer not null default 35 check (dte_max between 1 and 365 and dte_max >= dte_min),
  delta_min numeric not null default 0.20 check (delta_min > 0 and delta_min < 1),
  delta_max numeric not null default 0.30 check (delta_max > 0 and delta_max < 1 and delta_max >= delta_min),
  max_allocation_pct numeric not null default 30 check (max_allocation_pct between 5 and 100),
  max_spread_pct numeric not null default 20 check (max_spread_pct between 1 and 100),
  avoid_earnings boolean not null default true,
  updated_at timestamptz not null default now()
);

alter table public.user_profiles enable row level security;
alter table public.user_profiles force row level security;

create policy "Users read their own profile"
on public.user_profiles for select to authenticated
using ((select auth.uid()) = user_id);

create policy "Users create their own profile"
on public.user_profiles for insert to authenticated
with check ((select auth.uid()) = user_id);

create policy "Users update their own profile"
on public.user_profiles for update to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

grant select, insert, update on public.user_profiles to authenticated;
revoke all on public.user_profiles from anon;
