const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function setup(api) {
  const fields = { productionRecordsStatus: {}, selectAllNhapKho: { classList: { toggle() {} }, setAttribute() {} },
    nhapKhoSelectedCount: {}, nhapKhoSelectedCountValue: {}, recordsFilterSync: { value: 'waiting' }, recordsFilterNhapKho: { value: '' } };
  const buttons = [{ dataset: { eventId: 'e1' }, disabled: false }];
  const ctx = vm.createContext({ $, api, document: { querySelectorAll: () => buttons },
    recordsListQuery: () => 'work_date=2026-10-12&shift=HC1&machine=M1',
    recordErrorStatus: row => row.error_status || 'ok',
    recordNhapKhoStatus: row => ({ key: row.nhap_kho_trang_thai === 'done' ? 'done' : 'waiting' }),
    matchesRecordsStatusFilters: row => row.sync_status === fields.recordsFilterSync.value,
    status: (field, message, kind) => Object.assign(field, { message, kind }),
    setManualSyncRunning() {},
  });
  function $(id) { return fields[id]; }
  vm.runInContext("let recordsSelectionBusy=false,productionSelectionFilter='',productionAllSelectedFilter='',productionRowsByEvent={},selectedNhapKhoIds=new Set(),nhapKhoSelectedEventIds=[];", ctx);
  for (const prefix of ['function canSelectProductionRecord(', 'function recordsSelectionKey(', 'function paintNhapKhoSelectBtn(', 'function updateNhapKhoSelectedCount(']) {
    vm.runInContext(script.split('\n').find(line => line.startsWith(prefix)), ctx);
  }
  // The button stubs record their selection without needing a browser layout.
  ctx.paintNhapKhoSelectBtn = (button, selected) => { button.selected = selected; };
  const start = script.indexOf('async function toggleSelectAllNhapKho(');
  const end = script.indexOf('\nasync function deleteProductionRecord(', start);
  vm.runInContext(script.slice(start, end), ctx);
  return { ctx, fields, buttons, ids: () => vm.runInContext('[...selectedNhapKhoIds]', ctx) };
}

test('selects all matching rows across pages without a warehouse-status filter', async () => {
  const rows = Array.from({ length: 205 }, (_, index) => ({ event_id: 'e' + index, qr_code: 'SP_' + index,
    sync_status: index === 5 ? 'synced' : 'waiting', error_status: index === 6 ? 'error' : 'ok',
    nhap_kho_trang_thai: index === 7 ? 'done' : 'waiting' }));
  const calls = [];
  const { ctx, fields, ids } = setup(async url => {
    calls.push(url);
    const offset = Number(new URL('http://local' + url).searchParams.get('offset'));
    return { items: rows.slice(offset, offset + 200), total_count: rows.length };
  });
  await ctx.toggleSelectAllNhapKho();
  assert.equal(calls.length, 2);
  assert.equal(ids().length, 203);
  assert.ok(ids().includes('e204'));
  assert.ok(ids().includes('e7'), 'already imported rows can be selected for Supabase');
  assert.ok(!ids().includes('e5'));
  assert.ok(!ids().includes('e6'));
  assert.equal(fields.nhapKhoSelectedCountValue.textContent, '203');
  await ctx.toggleSelectAllNhapKho();
  assert.equal(ids().length, 0);
  assert.equal(calls.length, 2);
});

test('does not commit partial selection when a later page fails', async () => {
  let calls = 0;
  const { ctx, fields, ids } = setup(async () => {
    if (++calls === 2) throw new Error('network down');
    return { items: Array.from({ length: 200 }, (_, index) => ({ event_id: 'e' + index, qr_code: 'SP_' + index, sync_status: 'waiting' })), total_count: 201 };
  });
  await ctx.toggleSelectAllNhapKho();
  assert.equal(ids().length, 0);
  assert.equal(fields.productionRecordsStatus.kind, 'bad');
});

test('cancels selection if filters change while rows are loading', async () => {
  let fields;
  const state = setup(async () => {
    fields.recordsFilterSync.value = 'synced';
    return { items: [{ event_id: 'e1', qr_code: 'SP_1', sync_status: 'waiting' }] };
  });
  fields = state.fields;
  await state.ctx.toggleSelectAllNhapKho();
  assert.equal(state.ids().length, 0);
  assert.match(fields.productionRecordsStatus.message, /Bộ lọc đã thay đổi/);
});
