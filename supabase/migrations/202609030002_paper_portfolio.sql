create table if not exists public.paper_option_positions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  underlying text not null check (underlying ~ '^[A-Z][A-Z0-9.-]{0,9}$'),
  contract_symbol text not null,
  option_type text not null check (option_type in ('PUT', 'CALL')),
  strategy text not null,
  opening_action text not null check (opening_action in ('BUY_TO_OPEN', 'SELL_TO_OPEN')),
  quantity integer not null check (quantity > 0),
  multiplier integer not null default 100 check (multiplier = 100),
  strike numeric not null check (strike > 0),
  expiration date not null,
  entry_price numeric not null check (entry_price >= 0),
  entry_bid numeric,
  entry_ask numeric,
  entry_underlying_price numeric,
  current_mark numeric,
  quote_as_of timestamptz,
  status text not null default 'OPEN' check (status in ('OPEN', 'CLOSED', 'EXPIRED_PENDING')),
  exit_price numeric,
  realized_pnl numeric,
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists paper_option_positions_user_status_idx
  on public.paper_option_positions (user_id, status, opened_at desc);
create index if not exists paper_option_positions_user_underlying_idx
  on public.paper_option_positions (user_id, underlying);

alter table public.paper_option_positions enable row level security;
alter table public.paper_option_positions force row level security;

create policy "Users read their paper positions" on public.paper_option_positions
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "Users create their paper positions" on public.paper_option_positions
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Users update their paper positions" on public.paper_option_positions
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

grant select, insert, update on public.paper_option_positions to authenticated;
revoke all on public.paper_option_positions from anon;
