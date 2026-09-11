-- Image retention policy:
-- Render Persistent Disk is the independent seven-day evidence copy. Supabase
-- stores the weighing rows and metadata only; no image bucket is required.

alter table public.anh_can_cho_ai
  alter column image_url drop not null,
  alter column image_public_id drop not null;

alter table public.anh_can_cho_ai
  drop constraint if exists anh_can_cho_ai_capture_kind_check;

alter table public.anh_can_cho_ai
  add constraint anh_can_cho_ai_capture_kind_check
    check (capture_kind in ('core', 'product', 'inventory'));

comment on table public.anh_can_cho_ai is
  'Unreadable AI evidence rows are retained after the local/Cloudinary image retention window.';
