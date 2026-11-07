-- Run on the WEIGH AI project, not the warehouse project.
-- can_tu_dong remains the API's source of truth; these are physical read tables.
-- Assign gateways in can_ai_gateway_chi_nhanh to route both old and new tickets.
begin;

lock table public.can_tu_dong in share row exclusive mode;

create table if not exists public.can_ai_gateway_chi_nhanh (
  gateway_id text primary key check (length(btrim(gateway_id)) > 0),
  chi_nhanh text not null check (chi_nhanh in ('da_nang', 'hcm'))
);

create table if not exists public.can_tu_dong_da_nang
  (like public.can_tu_dong including all);
create table if not exists public.can_tu_dong_hcm
  (like public.can_tu_dong including all);

comment on table public.can_ai_gateway_chi_nhanh is
  'Admin routing: gateway_id -> da_nang or hcm. Unassigned gateways stay in can_tu_dong only.';
comment on table public.can_tu_dong_da_nang is
  'Da Nang AI scale records; automatically mirrored from can_tu_dong. Write through ingest-measurement.';
comment on table public.can_tu_dong_hcm is
  'HCM AI scale records; automatically mirrored from can_tu_dong. Write through ingest-measurement.';

alter table public.can_ai_gateway_chi_nhanh enable row level security;
alter table public.can_tu_dong_da_nang enable row level security;
alter table public.can_tu_dong_hcm enable row level security;
revoke all on public.can_ai_gateway_chi_nhanh from public, anon, authenticated, service_role;
revoke all on public.can_tu_dong_da_nang, public.can_tu_dong_hcm
  from public, anon, authenticated, service_role;

-- Match the existing can_tu_dong anon read access. Branch separation is for
-- organizing data, not branch-level authentication/authorization.
grant select on public.can_tu_dong_da_nang, public.can_tu_dong_hcm to anon, service_role;
drop policy if exists anon_read_can_tu_dong_da_nang on public.can_tu_dong_da_nang;
create policy anon_read_can_tu_dong_da_nang on public.can_tu_dong_da_nang
  for select to anon using (true);
drop policy if exists anon_read_can_tu_dong_hcm on public.can_tu_dong_hcm;
create policy anon_read_can_tu_dong_hcm on public.can_tu_dong_hcm
  for select to anon using (true);

create or replace function public.can_ai_mirror_row(row_data jsonb)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  branch text;
  target_table text;
  columns_sql text;
  updates_sql text;
begin
  select m.chi_nhanh into branch
  from public.can_ai_gateway_chi_nhanh m
  where m.gateway_id = coalesce(nullif(row_data->>'gateway_id', ''), row_data->>'device_id');

  -- Also removes stale copies after a gateway or branch assignment changes.
  if branch is distinct from 'da_nang' then
    delete from public.can_tu_dong_da_nang where event_id = (row_data->>'event_id')::uuid;
  end if;
  if branch is distinct from 'hcm' then
    delete from public.can_tu_dong_hcm where event_id = (row_data->>'event_id')::uuid;
  end if;
  if branch is null then return; end if;
  target_table := case branch when 'da_nang' then 'can_tu_dong_da_nang' else 'can_tu_dong_hcm' end;

  -- Exclude generated columns (notably net_weight); PostgreSQL recomputes them.
  select string_agg(format('%I', a.attname), ', ' order by a.attnum),
         string_agg(format('%I = excluded.%I', a.attname, a.attname), ', ' order by a.attnum)
  into columns_sql, updates_sql
  from pg_catalog.pg_attribute a
  where a.attrelid = format('public.%I', target_table)::regclass
    and a.attnum > 0 and not a.attisdropped and a.attgenerated = '';

  execute format(
    'insert into public.%I (%s) overriding system value '
    'select %s from jsonb_populate_record(null::public.%I, $1) '
    'on conflict (event_id) do update set %s',
    target_table, columns_sql, columns_sql, target_table, updates_sql
  ) using row_data;
end;
$$;

create or replace function public.can_ai_mirror_trigger()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    delete from public.can_tu_dong_da_nang where event_id = old.event_id;
    delete from public.can_tu_dong_hcm where event_id = old.event_id;
    return old;
  end if;
  if tg_op = 'UPDATE' then
    if old.event_id is distinct from new.event_id then
      delete from public.can_tu_dong_da_nang where event_id = old.event_id;
      delete from public.can_tu_dong_hcm where event_id = old.event_id;
    end if;
  end if;
  perform public.can_ai_mirror_row(to_jsonb(new));
  return new;
end;
$$;

create or replace function public.can_ai_refresh_branches()
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  source_row record;
begin
  -- Serialize with ingestion while copying history/reassigning a gateway.
  lock table public.can_tu_dong in share row exclusive mode;
  for source_row in select * from public.can_tu_dong loop
    perform public.can_ai_mirror_row(to_jsonb(source_row));
  end loop;
end;
$$;

create or replace function public.can_ai_gateway_branch_trigger()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  perform public.can_ai_refresh_branches();
  return null;
end;
$$;

revoke all on function public.can_ai_mirror_row(jsonb) from public, anon, authenticated, service_role;
revoke all on function public.can_ai_mirror_trigger() from public, anon, authenticated, service_role;
revoke all on function public.can_ai_refresh_branches() from public, anon, authenticated, service_role;
revoke all on function public.can_ai_gateway_branch_trigger() from public, anon, authenticated, service_role;

drop trigger if exists can_ai_mirror on public.can_tu_dong;
create trigger can_ai_mirror after insert or update or delete on public.can_tu_dong
  for each row execute function public.can_ai_mirror_trigger();
drop trigger if exists can_ai_gateway_branch_changed on public.can_ai_gateway_chi_nhanh;
create trigger can_ai_gateway_branch_changed
  after insert or update or delete on public.can_ai_gateway_chi_nhanh
  for each statement execute function public.can_ai_gateway_branch_trigger();

select public.can_ai_refresh_branches();
commit;

-- Future source-schema migrations must apply the same column changes to both
-- branch tables before inserting/updating data that uses the new columns.
