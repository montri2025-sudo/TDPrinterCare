// Staff cross-menu Demo (static/staff-demo.js): menu order, continuation, playback controls. No browser.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('static/staff-demo.js', 'utf8');
const texts = [...source.matchAll(/step\('[^']*', '[^']*', '([^']*)'\)/g)].map((m) => m[1]);
const ADMIN_MENU = ['/staff/warehouse', '/admin/dashboard', '/admin/board', '/field-service', '/admin/ticket/new', '/admin/customers', '/admin/inventory', '/sales/orders',
  '/admin/restock-orders', '/admin/settlements', '/admin/maintenance-plans', '/admin/checklist-items', '/admin/users', '/admin/centers', '/admin/activities',
  '/admin/odoo-sync', '/admin/reports', '/admin/commission-report', '/track', '/guide'];

function setup({ path = '/admin/dashboard', menu = ADMIN_MENU, manifestFor = () => '0123456789abcdef.mp3', reject = false, storage = new Map(), fieldTour = null } = {}) {
  const nodes = new Map(), events = {}, winEvents = {}, pending = new Map(), audios = [], navigations = [];
  let seq = 0;
  const node = (id) => { if (!nodes.has(id)) nodes.set(id, { id, hidden: true, checked: false, disabled: false, textContent: '', classList: { add() {}, remove() {} }, getClientRects: () => [{}], scrollIntoView() {}, focus() {}, addEventListener(n, fn) { this['on_' + n] = fn; } }); return nodes.get(id); };
  node('staff-demo-all').checked = true;
  const links = menu.map((href) => ({ getAttribute: () => href }));
  const manifest = Object.fromEntries(texts.map((t) => [t, manifestFor(t)]).filter(([, f]) => f));
  const ctx = {
    location: { pathname: path, assign: (p) => navigations.push(p) },
    document: { hidden: false, getElementById: node, querySelectorAll: (s) => (s === '.sidebar nav a' ? links : [node('target:' + s)]), querySelector: (s) => (s === 'dialog[open]' ? null : node('target:' + s)), addEventListener: (n, fn) => { events[n] = fn; } },
    window: { matchMedia: () => ({ matches: true }), addEventListener: (n, fn) => { winEvents[n] = fn; }, FieldServiceTour: fieldTour },
    sessionStorage: { getItem: (k) => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) },
    fetch: async () => ({ ok: true, json: async () => manifest }),
    Audio: class { constructor(src) { this.src = src; audios.push(this); } play() { return reject ? Promise.reject(new Error('blocked')) : Promise.resolve(); } pause() { this.paused = true; } },
    setTimeout: (fn, ms) => { pending.set(++seq, { fn, ms }); return seq; },
    clearTimeout: (id) => pending.delete(id),
    Promise,
  };
  ctx.window.document = ctx.document;
  vm.runInNewContext(source, ctx);
  const flush = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
  const fire = () => { const next = [...pending].sort((a, b) => a[1].ms - b[1].ms)[0]; assert.ok(next, 'a timer is pending'); pending.delete(next[0]); next[1].fn(); };
  return { node, events, winEvents, pending, audios, navigations, storage, ctx, flush, fire, api: () => ctx.window.StaffDemo };
}

test('every staff menu except the guide has narrated steps; menu order follows the sidebar', () => {
  const env = setup();
  assert.deepEqual([...env.api().menu], ADMIN_MENU.filter((p) => p !== '/guide'));
  for (const p of ['/manager/dashboard', '/manager/approvals', '/manager/restock-orders', '/manager/settlements', '/manager/csat', '/tech/tasks', '/tech/report', '/sales/new', '/sharespace'])
    assert.ok(env.api().pages[p] && env.api().pages[p].length, p);
  assert.ok(texts.length >= 50);
  assert.ok(texts.every((t) => t.length > 20), 'narration lines are literal and complete');
  assert.ok(texts.some((t) => /Odoo จริง.*Demo จะไม่กดแทน/.test(t)));
  const guide = setup({ path: '/guide' });
  assert.equal(guide.node('staff-demo-bar').hidden, true);
});

test('page tour advances after audio; at the end it continues to the next sidebar menu', async () => {
  const env = setup({ path: '/admin/dashboard' });
  env.node('staff-demo-start').on_click(); await env.flush();
  assert.equal(env.node('staff-demo-step').textContent, 'สาธิต 1 / 3');
  for (let i = 0; i < 3; i++) { env.audios.at(-1).onended(); env.fire(); await env.flush(); }
  assert.deepEqual(env.navigations, ['/admin/board']);
  assert.equal(env.storage.get('staff-demo-resume'), '/admin/board');
  const next = setup({ path: '/admin/board', storage: env.storage });   // arriving resumes automatically
  await next.flush();
  assert.equal(next.node('staff-demo-panel').hidden, false);
  assert.equal(next.node('staff-demo-step').textContent, 'สาธิต 1 / 4');
});

test('turning off “เล่นต่อทุกเมนู” stops on this page; last menu ends the Demo', async () => {
  const env = setup({ path: '/admin/users', manifestFor: () => null });
  env.node('staff-demo-all').checked = false;
  env.node('staff-demo-start').on_click(); await env.flush();
  for (let i = 0; i < 3; i++) env.node('staff-demo-next').on_click();
  assert.deepEqual(env.navigations, []);
  assert.equal(env.node('staff-demo-panel').hidden, true);
  const last = setup({ path: '/track', manifestFor: () => null });
  last.node('staff-demo-start').on_click(); await last.flush();
  last.node('staff-demo-next').on_click(); last.node('staff-demo-next').on_click();
  assert.deepEqual(last.navigations, []);
  assert.match(last.node('staff-demo-note').textContent, /จบ Demo ทุกเมนูแล้ว/);
});

test('mute uses captions without substitute voice; pause, hidden tab, close and autoplay rejection stop playback', async () => {
  const env = setup({ manifestFor: () => null });
  env.node('staff-demo-start').on_click(); await env.flush();
  assert.equal(env.audios.length, 0);
  assert.match(env.node('staff-demo-note').textContent, /ยังไม่มีไฟล์เสียงต้นแบบ/);
  const a = setup();
  a.node('staff-demo-start').on_click(); await a.flush();
  a.node('staff-demo-panel-mute').checked = true; a.node('staff-demo-panel-mute').on_change();
  assert.equal(a.node('staff-demo-mute').checked, true);
  assert.equal(a.audios[0].paused, true);
  a.node('staff-demo-pause').on_click();
  assert.equal(a.node('staff-demo-pause').textContent, 'เล่นต่อ');
  assert.equal(a.pending.size, 0);
  a.node('staff-demo-pause').on_click();
  a.ctx.document.hidden = true; a.events.visibilitychange();
  assert.equal(a.pending.size, 0);
  a.ctx.document.hidden = false;
  a.node('staff-demo-close').on_click();
  assert.equal(a.node('staff-demo-panel').hidden, true);
  assert.equal(a.storage.get('staff-demo-resume'), '');
  const r = setup({ reject: true });
  r.node('staff-demo-start').on_click(); await r.flush();
  assert.equal(r.node('staff-demo-pause').textContent, 'เล่นต่อ');
  assert.equal(r.pending.size, 0);
});

test('continuing into บริการนอกสถานที่ hands over to its tab tour, then moves to the next menu', async () => {
  let done = null;
  const storage = new Map([['staff-demo-resume', '/field-service']]);
  const env = setup({ path: '/field-service', storage, fieldTour: { startAll: (cb) => { done = cb; } } });
  assert.equal(env.node('staff-demo-bar').hidden, true);
  assert.equal(typeof done, 'function');
  done();
  assert.deepEqual(env.navigations, ['/admin/ticket/new']);
  const plain = setup({ path: '/field-service', fieldTour: { startAll: () => assert.fail('should not auto-start') } });
  assert.deepEqual(plain.navigations, []);
});

test('the Demo never submits, clicks or posts', () => {
  for (const banned of ['.submit(', '.click(', "method: 'POST'", 'XMLHttpRequest', 'speechSynthesis', 'localStorage'])
    assert.ok(!source.includes(banned), banned);
  assert.deepEqual([...source.matchAll(/fetch\('([^']+)'/g)].map((m) => m[1]), ['/static/staff-demo-voice/manifest.json']);
});
