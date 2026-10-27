// Field-service Demo: pure logic + guided tour playback. Fictional data only; no browser needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const C = require('../static/field-service-core.js');
const Data = require('./fixtures/field-service-data.cjs');

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
