const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = require('./frontend_fixture.cjs').html().match(/<script>([\s\S]*?)<\/script>/)[1];
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup(fetch) {
  const timers = new Map();
  let nextTimer = 0;
  const context = vm.createContext({
    fetch, AbortController, readSessionToken: () => '', location: {pathname: '/'},
    redirectToLogin() {throw Error('Unexpected auth redirect');},
    setTimeout(callback, ms) {const id = ++nextTimer; timers.set(id, {callback, ms}); return id;},
    clearTimeout(id) {timers.delete(id);},
  });
  for (const prefix of ['let dataReadActive=', 'const dataReadWaiters=', 'async function acquireDataRead(', 'function releaseDataRead(', 'async function api(']) {
    const line = script.split('\n').find(item => item.startsWith(prefix));
    assert.ok(line, prefix);
    vm.runInContext(line, context);
  }
  return {context, timers};
}
const ok = data => ({ok: true, status: 200, json: async () => data});

test('a hung preview request times out and the next local request can recover', async () => {
  let calls = 0;
  const ui = setup((_path, options) => {
    assert.equal(options.priority, 'high');
    assert.equal(options.cache, 'no-store');
    if (++calls > 1) return Promise.resolve(ok({frame_id: 2}));
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(Error('Network changed'))));
  });
  const pending = ui.context.api('/api/live/snapshot?preview=1');
  const timer = [...ui.timers.values()][0];
  assert.equal(timer.ms, 5000);
  timer.callback();
  await assert.rejects(pending, /Camera local chưa phản hồi/);
  assert.equal(ui.timers.size, 0);
  assert.equal((await ui.context.api('/api/live/snapshot?preview=1')).frame_id, 2);
  assert.equal(ui.timers.size, 0);
});

test('slow cloud reads reserve browser connections for camera and local writes', async () => {
  const jobs = [];
  const ui = setup((path, options) => {
    if (path.startsWith('/api/live/') || options.method === 'POST') return Promise.resolve(ok({ok: true}));
    return new Promise(resolve => jobs.push({path, finish: () => resolve(ok({items: []}))}));
  });
  const pending = Array.from({length: 6}, (_, index) => ui.context.api('/api/measurements?page=' + index));
  await tick();
  assert.equal(jobs.length, 2);
  assert.equal((await ui.context.api('/api/live/recognition')).ok, true);
  assert.equal((await ui.context.api('/api/photo-capture', {method: 'POST'})).ok, true);
  for (let index = 0; index < 6; index++) {jobs[index].finish(); await tick();}
  await Promise.all(pending);
  assert.equal(vm.runInContext('dataReadActive', ui.context), 0);
});

test('cancelling a queued cloud read removes it without consuming a connection', async () => {
  const jobs = [];
  const ui = setup(path => new Promise(resolve => jobs.push({path, finish: () => resolve(ok({}))})));
  const first = ui.context.api('/api/production-orders?first');
  const second = ui.context.api('/api/measurements?second');
  await tick();
  const controller = new AbortController();
  const third = ui.context.api('/api/lookup?cancelled', {signal: controller.signal});
  controller.abort();
  await assert.rejects(third, /Đã hủy tải dữ liệu/);
  assert.equal(jobs.length, 2);
  assert.equal(vm.runInContext('dataReadWaiters.length', ui.context), 0);
  jobs.forEach(job => job.finish());
  await Promise.all([first, second]);
  assert.equal(vm.runInContext('dataReadActive', ui.context), 0);
});
