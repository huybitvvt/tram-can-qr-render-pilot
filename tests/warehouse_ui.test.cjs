const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'index.html'),
  'utf8'
);

assert.match(html, /id="pushSupabaseBtn"[^>]*>Đẩy kho</);
assert.match(html, /id="nhapKhoModal"/);
assert.match(html, /id="confirmNhapKhoBtn"/);
assert.match(html, /id="checkNhapKhoBtn"/);
assert.match(html, /function openNhapKhoModal\(/);
assert.match(html, /\/api\/warehouse\/nhap-kho\/confirm/);
assert.match(html, /Đã nhập kho/);
assert.doesNotMatch(html, /bindActionButton\('pushSupabaseBtn',\(\)=>startManualSync\(true\)\)/);

console.log('warehouse_ui.test.cjs: ok');
