-- Xác nhận đợt cân là thao tác ghi log thủ công. Không chặn khi số cuộn
-- hiện có thấp hơn mốc hoặc dữ liệu của đợt chưa đầy đủ.

alter table public.ca_can
  drop constraint if exists ca_can_so_luong_check;

alter table public.ca_can
  add constraint ca_can_so_luong_check check (so_luong between 0 and 30);

alter table public.ca_can
  alter column so_luong set default 0;

comment on table public.ca_can is
  'Manual weighing-batch confirmation log; partial or empty batches are allowed.';
comment on column public.ca_can.danh_sach_san_pham is
  'Ordered snapshot of available can_tu_dong rows when the operator confirms.';
