create table if not exists public.dashboard_snapshots (
  id bigint generated always as identity primary key,
  generated_at timestamptz not null,
  research boolean not null default false,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists dashboard_snapshots_research_generated_idx
  on public.dashboard_snapshots (research, generated_at desc);

create table if not exists public.research_runs (
  id bigint generated always as identity primary key,
  symbol text not null check (symbol ~ '^[A-Z][A-Z0-9.-]{0,9}$'),
  question text not null,
  response jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists research_runs_symbol_created_idx
  on public.research_runs (symbol, created_at desc);

alter table public.dashboard_snapshots enable row level security;
alter table public.dashboard_snapshots force row level security;
alter table public.research_runs enable row level security;
alter table public.research_runs force row level security;

revoke all on public.dashboard_snapshots from anon, authenticated;
revoke all on public.research_runs from anon, authenticated;
grant all on public.dashboard_snapshots to service_role;
grant all on public.research_runs to service_role;
grant usage, select on sequence public.dashboard_snapshots_id_seq to service_role;
grant usage, select on sequence public.research_runs_id_seq to service_role;
