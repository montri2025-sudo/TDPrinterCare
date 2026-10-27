// Field-service Demo: pure logic + guided tour playback. Fictional data only; no browser needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const C = require('../static/field-service-core.js');
const Data = require('../static/field-service-data.js');

const TODAY = '2026-10-26';
const fresh = () => Data.build(TODAY);
const byId = (d) => Object.fromEntries(d.jobs.map((j) => [j.id, j]));
function plan(d, order, extra = {}) {
  const jobs = byId(d);
  return Object.assign({ start: d.center, end: 'return', departAt: '08:30', workEnd: '17:30',
    stops: order.map((id) => { const j = jobs[id], c = d.customers[j.customerId]; return { id, x: c.x, y: c.y, window: j.window, serviceMin: j.serviceMin }; }) }, extra);
}
function walk(job, steps) { return steps.reduce((j, [to, reason]) => C.applyTransition(j, to, { reason, at: 'T' }), job); }

test('full flow for install, inspection and maintenance keeps counts and history consistent', () => {
  const d = fresh();
  let jobs = d.jobs;
  const before = C.summary(jobs, TODAY);
  for (const id of ['FS-1001', 'FS-1002', 'FS-1003']) {   // install, inspection, maintenance
    const j = jobs.find((x) => x.id === id);
    const done = walk(j, [['preparing'], ['traveling'], ['in_service'], ['awaiting_acceptance'], ['completed']]);
    assert.equal(done.status, 'completed');
    assert.deepEqual(done.history.slice(-5).map((e) => e.to), ['preparing', 'traveling', 'in_service', 'awaiting_acceptance', 'completed']);
    assert.equal(j.status, 'assigned', 'original object is not mutated');
    jobs = jobs.map((x) => (x.id === id ? done : x));
  }
  const after = C.summary(jobs, TODAY);
  assert.equal(after.completed, before.completed + 3);
  assert.equal(after.today, before.today);
  assert.equal(C.filterJobs(jobs, { status: 'completed' }).length, after.completed);
  assert.equal(C.filterJobs(jobs, { status: 'active' }).length, after.active);
  assert.equal(C.filterJobs(jobs, { status: 'awaiting' }).length, after.awaiting);
});

test('request → schedule → assign needs a technician; invalid jumps are rejected', () => {
  const d = fresh();
  let j = byId(d)['FS-1008'];
  assert.equal(j.status, 'requested');
  assert.throws(() => C.applyTransition(j, 'completed'), /ไม่ได้/);
  j = C.applyTransition(j, 'awaiting_schedule');
  assert.throws(() => C.applyTransition(j, 'assigned'), /เลือกช่าง/);
  j = Object.assign({}, j, { techId: 'T2' });
  j = C.applyTransition(j, 'assigned');
  assert.equal(j.status, 'assigned');
});

test('waiting for parts and return to center require a reason and are recorded', () => {
  const d = fresh();
  const j = walk(byId(d)['FS-1004'], [['traveling'], ['in_service']]);
  assert.throws(() => C.applyTransition(j, 'waiting_parts', { reason: '   ' }), /เหตุผล/);
  const wp = C.applyTransition(j, 'waiting_parts', { reason: 'สกรูแกน Z ผิดขนาด' });
  assert.equal(wp.status, 'waiting_parts');
  assert.equal(wp.history.at(-1).note, 'สกรูแกน Z ผิดขนาด');
  const back = C.applyTransition(wp, 'preparing');
  assert.equal(back.status, 'preparing');
  const rtc = C.applyTransition(walk(back, [['traveling'], ['in_service']]), 'returned_to_center', { reason: 'ต้องเปลี่ยนบอร์ดที่ศูนย์' });
  assert.equal(rtc.status, 'returned_to_center');
  assert.deepEqual(C.allowedTransitions(rtc), []);
  assert.equal(C.canReschedule(rtc), false);
});

test('reschedule records reason and old/new appointment, keeps technician', () => {
  const d = fresh();
  const j = byId(d)['FS-1006'];                          // waiting_parts
  assert.throws(() => C.reschedule(j, { date: '2026-10-28' }), /เหตุผล/);
  assert.throws(() => C.reschedule(j, { reason: 'x' }), /วันนัด/);
  const r = C.reschedule(j, { reason: 'ลูกค้าปิดไลน์ผลิต', date: '2026-10-28', window: ['13:00', '14:00'] });
  assert.equal(r.status, 'assigned');
  assert.equal(r.date, '2026-10-28');
  assert.equal(r.rescheduled, 1);
  assert.match(r.history.at(-1).note, /ลูกค้าปิดไลน์ผลิต.*2026-10-26 14:00–15:00 → 2026-10-28 13:00–14:00/);
  const unassigned = C.reschedule(byId(d)['FS-1007'], { reason: 'เลื่อน', date: '2026-10-30' });
  assert.equal(unassigned.status, 'awaiting_schedule');
  assert.throws(() => C.reschedule(byId(d)['FS-1009'], { reason: 'x', date: '2026-10-30' }), /นัดใหม่ไม่ได้/);
});

test('search, filters and queue ordering', () => {
  const d = fresh();
  assert.deepEqual(C.filterJobs(d.jobs, { type: 'install' }).map((j) => j.id).sort(), ['FS-1001', 'FS-1007']);
  assert.ok(C.filterJobs(d.jobs, { tech: 'none' }).every((j) => !j.techId));
  assert.deepEqual(C.filterJobs(d.jobs, { q: 'เดโมเมดิคอล' }, d.customers).map((j) => j.id).sort(), ['FS-1003', 'FS-1007']);
  assert.deepEqual(C.filterJobs(d.jobs, { q: 'demo-rsn-0420' }, d.customers).map((j) => j.id), ['FS-1005']);
  const q = C.queue(d.jobs);
  assert.equal(q.at(-1).id, 'FS-1008', 'undated request is last');
  const keys = q.filter((j) => j.date).map((j) => j.date + j.window[0]);
  assert.deepEqual(keys, keys.slice().sort());
  const load = C.techLoad(d.jobs, d.techs, TODAY).find((l) => l.techId === 'T1');
  assert.equal(load.jobs, 5);
  assert.equal(load.serviceMin, 120 + 45 + 60 + 90 + 40);
});

test('route: initial demo order is late and over hours; reorder keeps pins and list identical', () => {
  const d = fresh();
  const r = C.planRoute(plan(d, d.route.order));
  assert.ok(r.rows.length >= 3);
  const late = r.warnings.filter((w) => w.kind === 'late').map((w) => w.id);
  assert.deepEqual(late, ['FS-1002']);
  assert.ok(r.warnings.some((w) => w.kind === 'overtime'));
  assert.equal(r.rows.find((x) => x.id === 'FS-1001').wait, 15, 'arrives 08:45, waits for 09:00');
  const moved = C.moveItem(d.route.order, 2, 1);           // move FS-1002 up
  assert.deepEqual(moved, ['FS-1001', 'FS-1002', 'FS-1003', 'FS-1004']);
  const r2 = C.planRoute(plan(d, moved));
  assert.deepEqual(r2.rows.map((x) => x.id), moved, 'timing rows follow the same order the map pins use');
  assert.deepEqual(r2.warnings, []);
  assert.equal(C.fmt(r2.endAt), '17:14');
  assert.equal(r2.source, 'simulated');
  assert.equal(r2.totalMin, r2.travelMin + r2.serviceMin + r2.waitMin);
  assert.deepEqual(C.moveItem(moved, 0, -1), moved, 'out-of-range move is a no-op');
});

test('route: overlap, end at last customer and postponed stops', () => {
  const d = fresh();
  const withExtra = plan(d, ['FS-1001', 'FS-1012', 'FS-1002', 'FS-1003', 'FS-1004']);
  const res = C.planRoute(withExtra);
  assert.ok(res.warnings.some((w) => w.kind === 'overlap' && w.ids.join() === 'FS-1001,FS-1012'));
  const last = C.planRoute(plan(d, ['FS-1001', 'FS-1002', 'FS-1003', 'FS-1004'], { end: 'last' }));
  assert.equal(last.back, null);
  assert.equal(C.fmt(last.endAt), '17:00');
  const p = plan(d, ['FS-1001', 'FS-1002', 'FS-1003', 'FS-1004']);
  p.stops[1].postponed = true;
  const skipped = C.planRoute(p);
  assert.equal(skipped.rows[1].skipped, true);
  assert.equal(skipped.rows.filter((x) => !x.skipped).length, 3);
});

test('Google matrix (traffic-unaware) replaces simulated legs when present, incl. same-site stops', () => {
  const d = fresh();
  const p = plan(d, ['FS-1001', 'FS-1002']);
  p.start = Object.assign({ loc: 'HQ' }, d.center);
  p.stops[0].loc = 'C1'; p.stops[1].loc = 'C3';
  const matrix = { 'HQ>C1': { km: 9.4, minutes: 21 }, 'C1>C3': { km: 12.1, minutes: 25 }, 'C3>HQ': { km: 15.5, minutes: 30 } };
  const r = C.planRoute(p, { matrix });
  assert.equal(r.source, 'google');
  assert.deepEqual(r.legs.map((l) => l.minutes), [21, 25, 30]);
  assert.equal(r.totalKm, 37);
  assert.equal(C.fmt(r.rows[0].arrive), '08:51');
  const partial = C.planRoute(p, { matrix: { 'HQ>C1': matrix['HQ>C1'] } });
  assert.equal(partial.source, 'mixed');
  assert.equal(C.leg({ loc: 'C1', x: 0, y: 0 }, { loc: 'C1', x: 0, y: 0 }, { matrix }).minutes, 0);
  const s = C.suggestOrder(p, { matrix });
  assert.equal(s.result.source, 'google');
});

test('suggestion respects locked stops and is only a proposal', () => {
  const d = fresh();
  const p = plan(d, d.route.order);
  const s = C.suggestOrder(p);
  assert.equal(s.changed, true);
  assert.deepEqual(s.order, ['FS-1001', 'FS-1002', 'FS-1003', 'FS-1004']);
  assert.deepEqual(p.stops.map((x) => x.id), d.route.order, 'input plan unchanged');
  p.stops[1].locked = true;                                  // keep FS-1003 second
  const locked = C.suggestOrder(p);
  assert.equal(locked.order[1], 'FS-1003');
  const best = C.suggestOrder(plan(d, ['FS-1001', 'FS-1002', 'FS-1003', 'FS-1004']));
  assert.equal(best.changed, false);
});

test('fictional data only', () => {
  const d = fresh();
  assert.ok(d.jobs.every((j) => j.machine.serial.startsWith('DEMO-')));
  assert.ok(Object.values(d.customers).every((c) => c.phone.startsWith('02-000-') && /สมมติ/.test(c.contact) && /สมมติ/.test(c.address)));
  assert.ok(Object.keys(d.customers).length >= 3);
  for (const t of Object.keys(C.TYPES)) assert.ok(d.jobs.some((j) => j.type === t), t);
});

// ---------------------------------------------------------------- guided tour --
const tourSource = fs.readFileSync('static/field-service-tour.js', 'utf8');
const tourTexts = [...tourSource.matchAll(/step\('[^']*', '[^']*', '[^']*', '([^']*)'\)/g)].map((m) => m[1]);
const LABELS = { control: 'ห้องควบคุมงานบริการ', tech: 'มุมมองช่าง', customer: 'มุมมองลูกค้า', route: 'แผนการเดินทาง' };
function tour({ views = ['control', 'tech', 'customer', 'route'], start = 'control', manifestFor = () => '0123456789abcdef.mp3', reject = false } = {}) {
  const nodes = new Map(), events = {}, winEvents = {}, pending = new Map(), audios = [], storage = new Map(), calls = [];
  let seq = 0, currentView = start;
  const node = (id) => { if (!nodes.has(id)) nodes.set(id, { id, hidden: true, checked: false, disabled: false, textContent: '', classList: { add() {}, remove() {} }, scrollIntoView() {}, focus() {}, addEventListener(n, fn) { this['on_' + n] = fn; } }); return nodes.get(id); };
  node('fsd-tour-all').checked = true;
  const manifest = Object.fromEntries(tourTexts.map((t) => [t, manifestFor(t)]).filter(([, f]) => f));
  const ctx = {
    document: { hidden: false, getElementById: node, querySelector: (s) => (s === 'dialog[open]' ? null : node('target:' + s)), querySelectorAll: () => [], addEventListener: (n, fn) => { events[n] = fn; } },
    window: { FieldServiceDemo: { views, current: () => currentView, label: (v) => LABELS[v], show: (v) => { currentView = v; calls.push('show:' + v); }, openJob: (id, o) => calls.push('job:' + id + ':' + (o && o.modal)), closeDialogs: () => calls.push('close') }, matchMedia: () => ({ matches: true }), addEventListener: (n, fn) => { winEvents[n] = fn; } },
    sessionStorage: { getItem: (k) => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) },
    fetch: async () => ({ ok: true, json: async () => manifest }),
    Audio: class { constructor(src) { this.src = src; audios.push(this); } play() { return reject ? Promise.reject(new Error('blocked')) : Promise.resolve(); } pause() { this.paused = true; } },
    setTimeout: (fn, ms) => { pending.set(++seq, { fn, ms }); return seq; },
    clearTimeout: (id) => pending.delete(id),
    Promise,
  };
  ctx.window.document = ctx.document;
  vm.runInNewContext(tourSource, ctx);
  const flush = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
  const fireShortest = () => { const next = [...pending].sort((a, b) => a[1].ms - b[1].ms)[0]; assert.ok(next, 'a timer is pending'); pending.delete(next[0]); next[1].fn(); };
  return { node, events, winEvents, pending, audios, calls, flush, fireShortest, ctx, view: () => currentView, groups: () => ctx.window.FieldServiceTour.groups };
}
const step = (env) => env.node('fsd-tour-step').textContent;

test('tour groups steps per allowed tab, in tab order, like the customer Virtual Office Demo', () => {
  assert.ok(tourTexts.length >= 15);
  assert.ok(tourTexts.some((t) => /ไม่ใช่เส้นทางถนนจริง/.test(t)));
  assert.ok(tourTexts.some((t) => /ไม่คิดสภาพจราจรสด/.test(t)));
  assert.deepEqual(tour().groups().map((g) => [g.view, g.steps.length]), [['control', 8], ['tech', 2], ['customer', 1], ['route', 6]]);
  assert.deepEqual(tour({ views: ['tech', 'route'] }).groups().map((g) => g.view), ['tech', 'route']);
  assert.deepEqual(tour({ views: ['control', 'customer'] }).groups().map((g) => [g.view, g.steps.length]), [['control', 8], ['customer', 2]]);
});

test('“Demo แนะนำหน้านี้” starts on the current tab and continues to the next tab only when “เล่นต่อทุกแท็บ” is on', async () => {
  const env = tour({ start: 'customer', manifestFor: () => null });
  env.node('fsd-tour-start').on_click(); await env.flush();
  assert.equal(step(env), 'สาธิต 1 / 1 · มุมมองลูกค้า');
  assert.equal(env.node('fsd-tour-next').textContent, 'แท็บถัดไป →');
  env.fireShortest(); await env.flush();                           // captions timer → next tab
  assert.equal(env.view(), 'route');
  assert.equal(step(env), 'สาธิต 1 / 6 · แผนการเดินทาง');
  const off = tour({ start: 'tech', manifestFor: () => null });
  off.node('fsd-tour-all').checked = false;
  off.node('fsd-tour-start').on_click(); await off.flush();
  off.node('fsd-tour-next').on_click();
  assert.equal(off.node('fsd-tour-next').textContent, 'จบ Demo');
  off.node('fsd-tour-next').on_click();
  assert.equal(off.node('fsd-tour-panel').hidden, true);
  assert.match(off.node('fsd-tour-note').textContent, /จบการสาธิตแท็บนี้แล้ว/);
  assert.equal(off.view(), 'tech');
});

test('narration advances only after audio ends; pause, close and hidden tab stop playback', async () => {
  const env = tour();
  env.node('fsd-tour-start').on_click(); await env.flush();
  assert.equal(step(env), 'สาธิต 1 / 8 · ห้องควบคุมงานบริการ');
  assert.equal(env.audios.length, 1);
  assert.equal(env.pending.size, 1, 'only the long watchdog is waiting');
  const firstEnded = env.audios[0].onended;
  env.node('fsd-tour-pause').on_click();
  assert.equal(env.node('fsd-tour-pause').textContent, 'เล่นต่อ');
  assert.equal(env.audios[0].paused, true);
  firstEnded();                                                    // stale event after pause is ignored
  assert.equal(env.pending.size, 0);
  env.node('fsd-tour-pause').on_click(); await env.flush();
  env.audios.at(-1).onended(); env.fireShortest(); await env.flush();
  assert.match(step(env), /^สาธิต 2 \/ 8/);
  env.ctx.document.hidden = true; env.events.visibilitychange();
  assert.equal(env.pending.size, 0);
  assert.equal(env.audios.at(-1).paused, true);
  env.ctx.document.hidden = false;
  env.node('fsd-tour-close').on_click();
  assert.equal(env.node('fsd-tour-panel').hidden, true);
  assert.ok(env.calls.includes('close'));
});

test('mute (bar or panel) and missing clips use timed Thai captions without any substitute voice', async () => {
  const env = tour({ manifestFor: () => null });
  env.node('fsd-tour-start').on_click(); await env.flush();
  assert.equal(env.audios.length, 0);
  assert.match(env.node('fsd-tour-note').textContent, /ยังไม่มีไฟล์เสียงต้นแบบ/);
  const m = tour();
  m.node('fsd-tour-start').on_click(); await m.flush();
  m.node('fsd-tour-panel-mute').checked = true; m.node('fsd-tour-panel-mute').on_change();
  assert.equal(m.node('fsd-tour-mute').checked, true, 'bar and panel checkboxes stay in sync');
  assert.equal(m.audios[0].paused, true);
  assert.match(m.node('fsd-tour-note').textContent, /ปิดเสียง/);
});

test('blocked autoplay pauses with a resume prompt; back crosses tabs; restart; job steps open non-modal', async () => {
  const env = tour({ reject: true });
  env.node('fsd-tour-start').on_click(); await env.flush();
  assert.equal(env.node('fsd-tour-pause').textContent, 'เล่นต่อ');
  assert.equal(env.pending.size, 0);
  const e2 = tour({ manifestFor: () => null });
  e2.node('fsd-tour-start').on_click();
  for (let i = 0; i < 5; i++) e2.node('fsd-tour-next').on_click();
  assert.match(step(e2), /^สาธิต 6 \/ 8/);
  assert.ok(e2.calls.includes('job:FS-1004:false'));
  for (let i = 0; i < 3; i++) e2.node('fsd-tour-next').on_click();     // into tech tab
  assert.equal(e2.view(), 'tech');
  e2.node('fsd-tour-prev').on_click();                                  // back to last control step
  assert.equal(e2.view(), 'control');
  assert.match(step(e2), /^สาธิต 8 \/ 8/);
  e2.node('fsd-tour-restart').on_click();
  assert.equal(step(e2), 'สาธิต 1 / 8 · ห้องควบคุมงานบริการ');
  assert.equal(e2.node('fsd-tour-prev').disabled, true);
  e2.winEvents.pagehide();
  assert.equal(e2.pending.size, 0);
});

test('startAll (used by the staff menu Demo) plays every tab and calls back only when finished, not when closed', async () => {
  let finished = 0;
  const env = tour({ start: 'route', manifestFor: () => null });
  env.ctx.window.FieldServiceTour.startAll(() => { finished += 1; });
  assert.equal(step(env), 'สาธิต 1 / 8 · ห้องควบคุมงานบริการ');
  for (let i = 0; i < 17; i++) env.node('fsd-tour-next').on_click();
  assert.equal(finished, 1);
  const closed = tour({ manifestFor: () => null });
  closed.ctx.window.FieldServiceTour.startAll(() => { finished += 1; });
  closed.node('fsd-tour-close').on_click();
  assert.equal(finished, 1);
});
