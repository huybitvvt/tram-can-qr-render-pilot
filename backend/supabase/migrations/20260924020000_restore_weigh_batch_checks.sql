-- Restore the unrelated checks if the earlier partial-confirmation migration
-- already removed them on a deployed database.
do $$
begin
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname = 'ca_can_dot_can_check') then
    alter table public.ca_can add constraint ca_can_dot_can_check check (dot_can > 0);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname = 'ca_can_moc_so_luong_check') then
    alter table public.ca_can add constraint ca_can_moc_so_luong_check check (moc_so_luong >= so_luong);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname = 'ca_can_so_luong_check') then
    alter table public.ca_can add constraint ca_can_so_luong_check check (so_luong between 0 and 30);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname = 'ca_can_danh_sach_san_pham_check') then
    alter table public.ca_can add constraint ca_can_danh_sach_san_pham_check check (jsonb_typeof(danh_sach_san_pham) = 'array');
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname = 'ca_can_trang_thai_check') then
    alter table public.ca_can add constraint ca_can_trang_thai_check check (trang_thai in ('confirmed', 'void'));
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.ca_can'::regclass and conname in ('ca_can_check', 'ca_can_gio_can_check')) then
    alter table public.ca_can add constraint ca_can_gio_can_check check (gio_bat_dau <= gio_ket_thuc);
  end if;
end $$;
