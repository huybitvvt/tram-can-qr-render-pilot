-- Xác nhận đợt cân là thao tác ghi log thủ công. Không chặn khi số cuộn
-- hiện có thấp hơn mốc hoặc dữ liệu của đợt chưa đầy đủ.

do $$
declare constraint_name text;
begin
  for constraint_name in
    select conname from pg_constraint
    where conrelid = 'public.ca_can'::regclass and contype = 'c'
  loop
    execute format('alter table public.ca_can drop constraint %I', constraint_name);
  end loop;
end $$;

alter table public.ca_can
  alter column so_luong set default 0;

comment on table public.ca_can is
  'Manual weighing-batch confirmation log; partial or empty batches are allowed.';
comment on column public.ca_can.danh_sach_san_pham is
  'Ordered snapshot of available can_tu_dong rows when the operator confirms.';
