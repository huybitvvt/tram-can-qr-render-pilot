const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

// Optional PostgreSQL integration: install @electric-sql/pglite, or point
// PGLITE_MODULE_PATH at a temporary installation outside the repository.
let PGlite;
try{({PGlite}=require(process.env.PGLITE_MODULE_PATH||'@electric-sql/pglite'))}catch(error){
  if(error.code!=='MODULE_NOT_FOUND')throw error;
}
const migration=fs.readFileSync('backend/supabase/migrations/20261108010000_can_ai_branch_tables.sql','utf8');

test('branch tables route history and future changes while preserving the AI source',
  {skip:!PGlite},async()=>{
    const db=new PGlite();
    const one='00000000-0000-0000-0000-000000000001';
    const two='00000000-0000-0000-0000-000000000002';
    const three='00000000-0000-0000-0000-000000000003';
    async function rows(table){return (await db.query(`select event_id, net_weight, metadata from public.${table} order by event_id`)).rows}
    try{
      await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
      // Use the real original schemas, before unrelated Storage/RLS setup.
      const base=fs.readFileSync('backend/supabase/migrations/20260801000100_roll_ingestion.sql','utf8')
        .split('-- Upgrade the earlier prototype schema')[0].replace('create extension if not exists pgcrypto;','');
      await db.exec(base);
      await db.exec(fs.readFileSync('backend/supabase/migrations/20260802090000_can_tu_dong.sql','utf8'));
      await db.exec(`alter table public.can_tu_dong add column gateway_id text;
        insert into public.can_tu_dong (event_id,qr_code,weight,tare_weight,unit,image_path,gateway_id)
        values ('${one}','SP-1',10,2,'kg','photo-1','gateway-03'),
               ('${two}','SP-2',20,3,'kg','photo-2','gateway-hcm');`);
      await db.exec(migration);
      assert.equal((await rows('can_tu_dong_da_nang')).length,0);
      assert.equal((await rows('can_tu_dong_hcm')).length,0);
      // Assignment backfills old tickets without editing can_tu_dong.
      await db.exec(`insert into public.can_ai_gateway_chi_nhanh values ('gateway-03','da_nang'),('gateway-hcm','hcm');`);
      assert.deepEqual((await rows('can_tu_dong_da_nang')).map(r=>r.event_id),[one]);
      assert.deepEqual((await rows('can_tu_dong_hcm')).map(r=>r.event_id),[two]);
      assert.equal(Number((await rows('can_tu_dong_da_nang'))[0].net_weight),8);
      await db.exec(`update public.can_tu_dong set metadata='{"nhap_kho_trang_thai":"Đã nhập kho"}', weight=12 where event_id='${one}';`);
      const updated=(await rows('can_tu_dong_da_nang'))[0];
      assert.equal(Number(updated.net_weight),10);
      assert.equal(updated.metadata.nhap_kho_trang_thai,'Đã nhập kho');
      // New ingestion is routed immediately; fallback device_id also works.
      await db.exec(`insert into public.devices(id) values ('gateway-03');
        insert into public.can_tu_dong(event_id,qr_code,weight,unit,image_path,device_id)
        values ('${three}','SP-3',5,'kg','photo-3','gateway-03');`);
      assert.equal((await rows('can_tu_dong_da_nang')).length,2);
      // Reassignment moves all history, with no duplicate in the old branch.
      await db.exec(`update public.can_ai_gateway_chi_nhanh set chi_nhanh='hcm' where gateway_id='gateway-03';`);
      assert.equal((await rows('can_tu_dong_da_nang')).length,0);
      assert.equal((await rows('can_tu_dong_hcm')).length,3);
      await db.exec(`delete from public.can_tu_dong where event_id='${three}';`);
      assert.equal((await rows('can_tu_dong_hcm')).length,2);
      // Unassigning removes only the branch copy, not the original ticket.
      await db.exec(`delete from public.can_ai_gateway_chi_nhanh where gateway_id='gateway-hcm';`);
      assert.deepEqual((await rows('can_tu_dong_hcm')).map(r=>r.event_id),[one]);
      assert.equal((await rows('can_tu_dong')).length,2);
      await db.exec(migration);
      assert.deepEqual((await rows('can_tu_dong_hcm')).map(r=>r.event_id),[one]);
      // Branch reads match current source access; writes/admin helpers are private.
      await db.exec('set role anon');
      assert.equal((await rows('can_tu_dong_hcm')).length,1);
      await assert.rejects(db.exec('delete from public.can_tu_dong_hcm'),/permission denied/);
      await assert.rejects(db.exec('select public.can_ai_refresh_branches()'),/permission denied/);
      await assert.rejects(db.exec('select * from public.can_ai_gateway_chi_nhanh'),/permission denied/);
      await db.exec('reset role');
    }finally{await db.close()}
  });
