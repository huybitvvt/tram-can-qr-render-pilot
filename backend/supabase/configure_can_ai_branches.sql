-- Run in SQL Editor on https://njdlkyxdieefeebcyaov.supabase.co
-- FIRST run migrations/20261108010000_can_ai_branch_tables.sql.
-- Find the gateways already present (gateway_id falls back to device_id).
select coalesce(nullif(gateway_id, ''), device_id) as gateway_id,
       count(*) as so_phieu,
       min(captured_at) as phieu_dau,
       max(captured_at) as phieu_cuoi
from public.can_tu_dong
group by 1 order by 1;

-- UNCOMMENT exactly the assignment matching each gateway's actual location.
-- Machine 03's location has not been confirmed; do not assign it by guesswork.
-- insert into public.can_ai_gateway_chi_nhanh (gateway_id, chi_nhanh)
-- values ('gateway-03', 'da_nang')
-- on conflict (gateway_id) do update set chi_nhanh = excluded.chi_nhanh;

-- If machine 03 is in HCM, use this instead:
-- insert into public.can_ai_gateway_chi_nhanh (gateway_id, chi_nhanh)
-- values ('gateway-03', 'hcm')
-- on conflict (gateway_id) do update set chi_nhanh = excluded.chi_nhanh;

-- Changing the mapping automatically copies existing tickets and routes future
-- tickets. Each gateway must identify one branch only (unique across branches).
select * from public.can_ai_gateway_chi_nhanh order by gateway_id;
select 'da_nang' as chi_nhanh, count(*) as so_phieu from public.can_tu_dong_da_nang
union all
select 'hcm', count(*) from public.can_tu_dong_hcm
union all
select 'chua_gan_chi_nhanh', count(*) from public.can_tu_dong c
where not exists (
  select 1 from public.can_ai_gateway_chi_nhanh m
  where m.gateway_id = coalesce(nullif(c.gateway_id, ''), c.device_id)
);
