const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'index.html'),
  'utf8'
);

assert.match(html, /id="pushSupabaseBtn"[^>]*>Đẩy Supabase</);
assert.match(html, /id="nhapKhoBtn"[^>]*>Nhập kho</);
assert.match(html, /id="recordsFilterProductCode"/);
assert.match(html, /<th>Đẩy kho<\/th>/);
assert.match(html, /id="selectAllNhapKho"/);
assert.match(html, /paintNhapKhoSelectBtn/);
assert.match(html, /skip_sync:true/);
assert.match(html, /bindActionButton\('pushSupabaseBtn',\(\)=>startManualSync\(true\)\)/);
assert.match(html, /bindActionButton\('nhapKhoBtn',\(\)=>openNhapKhoModal\(\)\)/);
assert.match(html, /function canSelectForNhapKho\(/);
assert.match(html, /function recordNhapKhoStatus\(/);
assert.match(html, /function appendNhapKhoStatusCell\(/);
assert.match(html, /Đã đẩy kho/);
assert.match(html, /Chờ đẩy kho/);
assert.match(html, /id="nhapKhoModal"/);
assert.match(html, /id="confirmNhapKhoBtn"/);
assert.match(html, /id="checkNhapKhoBtn"/);
assert.match(html, /function openNhapKhoModal\(/);
assert.match(html, /event_ids:eventIds/);
assert.match(html, /function markProductionRowsPushed\(/);
assert.match(html, /void loadRecords\(\)/);
assert.match(html, /\/api\/warehouse\/nhap-kho\/confirm/);
assert.match(html, /Đã nhập kho/);
assert.match(html, /production-row-delete/);
assert.match(html, /Xóa dòng đã đẩy kho/);
assert.match(html, /NHAP_KHO_SUMMARY_KEY='rollQrScale\.nhapKhoSummary\.v1'/);
assert.match(html, /function rememberNhapKhoPush\(/);
assert.match(html, /id="nhapKhoSummaryModal"/);
assert.match(html, /Tổng hợp đẩy kho/);
assert.match(html, /\/api\/warehouse\/nhap-kho\/summary/);
assert.match(html, /\/api\/warehouse\/nhap-kho\/summary-export/);
assert.match(html, /Mở thư mục Excel/);
assert.match(html, /id="printNhapKhoSummaryBtn"/);
assert.match(html, /function printNhapKhoSummary\(/);
assert.match(html, /TỔNG HỢP ĐẨY KHO/);
assert.match(html, /In PDF/);
assert.doesNotMatch(html, /function downloadNhapKhoSummaryCsv\(/);
assert.doesNotMatch(html, /bindActionButton\('pushSupabaseBtn',\(\)=>openNhapKhoModal\(\)\)/);

console.log('warehouse_ui.test.cjs: ok');

const vm = require('node:vm');
const { test } = require('node:test');

function confirmContext(api) {
  const fields = {};
  for (const [id, value] of Object.entries({ nhapKhoDate: '2026-10-08', nhapKhoCa: 'HC1',
    nhapKhoMay: 'Máy 1', nhapKhoMaSp: 'SP01', nhapKhoWarehouse: 'Kho thành phẩm', nhapKhoSoCuon: '1' })) {
    fields[id] = { value };
  }
  for (const id of ['confirmNhapKhoBtn', 'checkNhapKhoBtn', 'closeNhapKhoBtn', 'nhapKhoStatus', 'productionRecordsStatus']) {
    fields[id] = { disabled: false };
  }
  const context = vm.createContext({ nhapKhoBusy: false, nhapKhoSelectedEventIds: ['e1'],
    selectedNhapKhoIds: new Set(['e1']), $: id => fields[id], api,
    status: (field, message, kind) => Object.assign(field, { message, kind }),
    setManualSyncRunning: () => {}, closeNhapKhoModal: () => {}, loadRecords: async () => {},
    rememberNhapKhoPush: () => null, markProductionRowsPushed: () => {},
    refreshNhapKhoCandidates: async () => { fields.nhapKhoStatus.message = 'Sẵn sàng'; },
  });
  vm.runInContext(html.match(/^async function confirmNhapKho\(\).*$/m)[0], context);
  return { context, fields };
}

test('keeps warehouse failure visible after refreshing candidates', async () => {
  const { context, fields } = confirmContext(async () => { throw new Error('Bấm Nhập kho lại để hoàn tất'); });
  await context.confirmNhapKho();
  assert.strictEqual(fields.nhapKhoStatus.message, 'Bấm Nhập kho lại để hoàn tất');
  assert.strictEqual(fields.nhapKhoStatus.kind, 'bad');
  assert.strictEqual(fields.closeNhapKhoBtn.disabled, false);
  assert.strictEqual(context.nhapKhoBusy, false);
});

test('reports recovered receipts as warehouse waiting, not a newly created receipt', async () => {
  const { context, fields } = confirmContext(async () => ({
    saved_count: 1, recovered_count: 1, ma_phieu: 'PN1', ma_phieu_list: ['PN1', 'PN2'],
  }));
  await context.confirmNhapKho();
  assert.match(fields.productionRecordsStatus.message, /kho chờ/);
  assert.match(fields.productionRecordsStatus.message, /PN1, PN2/);
  assert.match(fields.productionRecordsStatus.message, /dùng lại 1 QR/);
  assert.strictEqual(fields.productionRecordsStatus.kind, 'ok');
});
