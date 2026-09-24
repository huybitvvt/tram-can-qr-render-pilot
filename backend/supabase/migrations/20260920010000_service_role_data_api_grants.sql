-- New Supabase projects may disable automatic Data API grants. RLS bypass is
-- not enough: the Edge Functions' service_role still needs table privileges.
-- Keep anon/authenticated grants limited to the explicit read-only migrations.
grant usage on schema public to service_role;

grant select, insert, update, delete on table
  public.devices,
  public.rolls,
  public.measurements,
  public.can_tu_dong,
  public.can_kiem_kho,
  public.anh_can_cho_ai,
  public.ca_can,
  public.roll_scale_secrets
to service_role;

do $$
declare
  sequence_name text;
begin
  for sequence_name in
    select pg_get_serial_sequence(format('public.%I', table_name), 'id')
    from (values
      ('measurements'),
      ('can_tu_dong'),
      ('can_kiem_kho'),
      ('anh_can_cho_ai'),
      ('ca_can')
    ) as tables_with_identity(table_name)
  loop
    if sequence_name is not null then
      execute format('grant usage, select on sequence %s to service_role', sequence_name);
    end if;
  end loop;
end $$;
