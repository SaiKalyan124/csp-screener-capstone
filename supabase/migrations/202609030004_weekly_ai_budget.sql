create table if not exists public.ai_weekly_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  week_start date not null,
  estimated_cost_usd numeric(8,4) not null default 0 check (estimated_cost_usd >= 0),
  request_count integer not null default 0 check (request_count >= 0),
  updated_at timestamptz not null default now(),
  primary key (user_id, week_start)
);

alter table public.ai_weekly_usage enable row level security;
alter table public.ai_weekly_usage force row level security;

create policy "Users read their own weekly AI usage"
on public.ai_weekly_usage for select to authenticated
using ((select auth.uid()) = user_id);

grant select on public.ai_weekly_usage to authenticated;
revoke all on public.ai_weekly_usage from anon;

create or replace function public.consume_weekly_ai_budget(
  p_estimated_cost_usd numeric,
  p_weekly_limit_usd numeric default 3.00
)
returns table (
  allowed boolean,
  spent_usd numeric,
  remaining_usd numeric,
  request_count integer,
  resets_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := (select auth.uid());
  v_week_start date := date_trunc('week', timezone('utc', now()))::date;
  v_usage public.ai_weekly_usage%rowtype;
begin
  if v_user_id is null then
    raise exception 'Authentication required';
  end if;
  if p_estimated_cost_usd <= 0 or p_weekly_limit_usd <= 0 then
    raise exception 'Budget values must be positive';
  end if;

  insert into public.ai_weekly_usage (user_id, week_start)
  values (v_user_id, v_week_start)
  on conflict (user_id, week_start) do nothing;

  update public.ai_weekly_usage
  set estimated_cost_usd = estimated_cost_usd + p_estimated_cost_usd,
      request_count = request_count + 1,
      updated_at = now()
  where user_id = v_user_id
    and week_start = v_week_start
    and estimated_cost_usd + p_estimated_cost_usd <= p_weekly_limit_usd
  returning * into v_usage;

  if found then
    return query select true, v_usage.estimated_cost_usd,
      greatest(0, p_weekly_limit_usd - v_usage.estimated_cost_usd),
      v_usage.request_count,
      (v_week_start::timestamp + interval '7 days') at time zone 'UTC';
  else
    select * into v_usage from public.ai_weekly_usage
    where user_id = v_user_id and week_start = v_week_start;
    return query select false, v_usage.estimated_cost_usd,
      greatest(0, p_weekly_limit_usd - v_usage.estimated_cost_usd),
      v_usage.request_count,
      (v_week_start::timestamp + interval '7 days') at time zone 'UTC';
  end if;
end;
$$;

revoke all on function public.consume_weekly_ai_budget(numeric, numeric) from public, anon;
grant execute on function public.consume_weekly_ai_budget(numeric, numeric) to authenticated;
