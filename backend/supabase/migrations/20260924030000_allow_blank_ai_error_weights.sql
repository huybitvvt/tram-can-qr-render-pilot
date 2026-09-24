-- AI may fail to read either display after the evidence photo is captured.
-- Keep the official ticket with a real NULL so zero remains a valid reading.
alter table if exists public.can_tu_dong
  alter column weight drop not null,
  alter column tare_weight drop not null;

alter table if exists public.measurements
  alter column weight drop not null;

comment on column public.can_tu_dong.weight is
  'Product/gross reading; NULL means AI could not read the display.';
comment on column public.can_tu_dong.tare_weight is
  'Core/tare reading; NULL means AI could not read the display.';
