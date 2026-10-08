const assert = require('node:assert/strict');
const { test } = require('node:test');
const { warehouseImportStatus } = require('../backend/supabase/functions/ingest-measurement/warehouse_import.ts');

function database(rows, options = {}) {
  const writes = [];
  return {
    writes,
    from(table) {
      assert.equal(table, 'can_tu_dong');
      return {
        select() { return { in: async (_field, ids) => ({ data: rows.filter(row => ids.includes(row.event_id)), error: null }) }; },
        update(value) {
          writes.push(value);
          return { eq: (_field, id) => ({ select: () => ({ maybeSingle: async () => {
            const row = rows.find(row => row.id === id);
            if (options.empty) return { data: null, error: null };
            if (options.error) return { data: null, error: { message: 'network down' } };
            Object.assign(row, value);
            return { data: { id }, error: null };
          } }) }) };
        },
      };
    },
  };
}

test('preflight verifies every event without updating records', async () => {
  const db = database([{ id: 1, event_id: 'e1', qr_code: 'SP01_A', metadata: {} }]);
  const res = await warehouseImportStatus({ event_ids: ['e1'], check_only: true }, db);
  assert.equal(res.status, 200);
  assert.equal((await res.json()).items[0].qr_code, 'SP01_A');
  assert.equal(db.writes.length, 0);
});

test('missing events block all updates', async () => {
  const db = database([{ id: 1, event_id: 'e1' }]);
  const res = await warehouseImportStatus({ event_ids: ['e1', 'missing'], ma_phieu: 'PN1' }, db);
  assert.equal(res.status, 409);
  assert.equal(db.writes.length, 0);
});

test('marks imported and preserves weighing metadata; retries are idempotent', async () => {
  const db = database([{ id: 1, event_id: 'e1', metadata: { core_weight: 0, product_weight: 6.27, work_date: '2026-10-08' } }]);
  const body = { event_ids: ['e1'], ma_phieu: 'PN1', nguoi: 'Trạm cân' };
  let res = await warehouseImportStatus(body, db);
  assert.equal(res.status, 200);
  assert.equal((await res.json()).confirmed_count, 1);
  assert.equal(db.writes[0].metadata.product_weight, 6.27);
  assert.equal(db.writes[0].metadata.nhap_kho_trang_thai, 'Đã nhập kho');
  res = await warehouseImportStatus(body, db);
  assert.equal((await res.json()).updated, 0);
  assert.equal(db.writes.length, 1);
});

for (const options of [{ empty: true }, { error: true }]) {
  test('does not report completion without an acknowledged update ' + JSON.stringify(options), async () => {
    const res = await warehouseImportStatus({ event_ids: ['e1'], ma_phieu: 'PN1' }, database([{ id: 1, event_id: 'e1' }], options));
    assert.equal(res.status, 500);
    assert.equal((await res.json()).ok, false);
  });
}

test('rejects invalid event ids and missing receipt', async () => {
  const db = database([]);
  for (const body of [{ event_ids: [] }, { event_ids: ['bad id'] }, { event_ids: ['e1'] }]) {
    assert.equal((await warehouseImportStatus(body, db)).status, 422);
  }
  assert.equal(db.writes.length, 0);
});
