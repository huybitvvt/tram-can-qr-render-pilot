-- Keep existing batches and allow the operator to confirm up to 30 rolls at a time.
-- A source may have milestones such as 10, 26, 42 after upgrade.
alter table public.ca_can
  drop constraint if exists ca_can_moc_so_luong_check,
  drop constraint if exists ca_can_so_luong_check;

alter table public.ca_can
  add constraint ca_can_moc_so_luong_check check (moc_so_luong >= so_luong),
  add constraint ca_can_so_luong_check check (so_luong between 1 and 30);

comment on table public.ca_can is
  'Confirmed production weighing batches of 1 to 30 rolls, with a per-machine limit.';
comment on column public.ca_can.danh_sach_san_pham is
  'Ordered snapshot of the can_tu_dong rows included in this batch.';
