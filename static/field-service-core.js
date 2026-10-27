/* Field-service Demo: pure logic only (no DOM, no network, no real records).
 * Loaded by the browser as window.FieldServiceCore and by Node tests via require(). */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FieldServiceCore = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------------------------------------------------------------- statuses --
  const FLOW = ['requested', 'awaiting_schedule', 'assigned', 'preparing', 'traveling',
    'in_service', 'awaiting_acceptance', 'completed'];
  const STATUS = {
    requested: { label: 'รับคำขอ', tone: 'grey' },
    awaiting_schedule: { label: 'รอนัดหมาย', tone: 'amber' },
    assigned: { label: 'มอบหมายช่าง', tone: 'blue' },
    preparing: { label: 'เตรียมพร้อม', tone: 'blue' },
    traveling: { label: 'เดินทาง', tone: 'purple' },
    in_service: { label: 'กำลังบริการ', tone: 'purple' },
    awaiting_acceptance: { label: 'รอตรวจรับ', tone: 'orange' },
    completed: { label: 'เสร็จสิ้น', tone: 'green' },
    waiting_parts: { label: 'รออะไหล่', tone: 'red' },
    returned_to_center: { label: 'นำเครื่องกลับศูนย์', tone: 'orange' },
  };
  const TYPES = {
    install: 'ติดตั้ง', inspection: 'ตรวจเช็ก', repair: 'ซ่อม', maintenance: 'บำรุงรักษา',
  };

  // Allowed moves. needsReason=true -> the Demo asks for a reason and records it in history.
  const TRANSITIONS = {
    requested: [{ to: 'awaiting_schedule', label: 'รับคำขอแล้ว → รอนัดหมาย' }],
    awaiting_schedule: [{ to: 'assigned', label: 'ยืนยันนัดและมอบหมายช่าง', needsTech: true }],
    assigned: [{ to: 'preparing', label: 'เริ่มเตรียมเครื่องมือ/อะไหล่' }],
    preparing: [
      { to: 'traveling', label: 'ออกเดินทาง' },
      { to: 'waiting_parts', label: 'รออะไหล่', needsReason: true },
    ],
    traveling: [{ to: 'in_service', label: 'ถึงหน้างาน เริ่มบริการ' }],
    in_service: [
      { to: 'awaiting_acceptance', label: 'บริการเสร็จ ส่งให้ลูกค้าตรวจรับ' },
      { to: 'waiting_parts', label: 'รออะไหล่', needsReason: true },
      { to: 'returned_to_center', label: 'นำเครื่องกลับศูนย์', needsReason: true },
    ],
    awaiting_acceptance: [
      { to: 'completed', label: 'ลูกค้าตรวจรับแล้ว ปิดงาน' },
      { to: 'in_service', label: 'ลูกค้าขอแก้ไขเพิ่ม', needsReason: true },
    ],
    waiting_parts: [{ to: 'preparing', label: 'อะไหล่พร้อม กลับไปเตรียมงาน' }],
    returned_to_center: [],
    completed: [],
  };
  // "นัดใหม่" is an action (keeps the job, changes the appointment) allowed from these statuses.
  const RESCHEDULABLE = ['awaiting_schedule', 'assigned', 'preparing', 'traveling', 'waiting_parts'];

  const NEXT_HINT = {
    requested: 'ตรวจคำขอแล้วกด “รับคำขอแล้ว” เพื่อเข้าคิวนัดหมาย',
    awaiting_schedule: 'ตกลงวันเวลากับลูกค้า แล้วมอบหมายช่าง',
    assigned: 'ช่างเตรียมเครื่องมือ อะไหล่ และ Checklist ก่อนวันนัด',
    preparing: 'เมื่อพร้อมให้กด “ออกเดินทาง” หากขาดอะไหล่ให้เลือก “รออะไหล่”',
    traveling: 'เมื่อถึงหน้างานให้กด “ถึงหน้างาน เริ่มบริการ”',
    in_service: 'ทำ Checklist และบันทึกผล เสร็จแล้วส่งให้ลูกค้าตรวจรับ',
    awaiting_acceptance: 'ให้ผู้ติดต่อของลูกค้าตรวจรับ แล้วปิดงาน',
    completed: 'งานปิดแล้ว ดูรายงานบริการได้ในใบงาน',
    waiting_parts: 'เมื่ออะไหล่มาถึงให้กด “อะไหล่พร้อม” หรือเลือกนัดใหม่',
    returned_to_center: 'เครื่องกลับศูนย์ — งานจริงต้องเปิดตั๋วซ่อมแยก (Demo ไม่สร้างให้)',
  };

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function allowedTransitions(job) {
    return (TRANSITIONS[job.status] || []).slice();
  }
  function canReschedule(job) { return RESCHEDULABLE.indexOf(job.status) >= 0; }

  /** Returns a NEW job with the status changed and a history entry appended. Throws on invalid input. */
  function applyTransition(job, to, opts) {
    opts = opts || {};
    const rule = allowedTransitions(job).find(function (t) { return t.to === to; });
    if (!rule) throw new Error('เปลี่ยนจาก ' + STATUS[job.status].label + ' ไป ' + (STATUS[to] ? STATUS[to].label : to) + ' ไม่ได้');
    const reason = String(opts.reason || '').trim();
    if (rule.needsReason && !reason) throw new Error('กรุณาระบุเหตุผล');
    if (rule.needsTech && !job.techId) throw new Error('กรุณาเลือกช่างก่อน');
    const next = clone(job);
    next.history.push({ at: opts.at || '', from: job.status, to: to, note: reason, actor: opts.actor || 'Demo' });
    next.status = to;
    return next;
  }

  /** "นัดใหม่": requires reason + new date; status becomes assigned (has tech) or awaiting_schedule. */
  function reschedule(job, opts) {
    opts = opts || {};
    if (!canReschedule(job)) throw new Error('สถานะนี้นัดใหม่ไม่ได้');
    const reason = String(opts.reason || '').trim();
    if (!reason) throw new Error('กรุณาระบุเหตุผล');
    if (!opts.date) throw new Error('กรุณาเลือกวันนัดใหม่');
    const next = clone(job);
    const to = job.techId ? 'assigned' : 'awaiting_schedule';
    const before = (job.date || 'ยังไม่นัด') + (job.window ? ' ' + job.window.join('–') : '');
    next.date = opts.date;
    if (opts.window) next.window = opts.window.slice();
    const after = next.date + (next.window ? ' ' + next.window.join('–') : '');
    next.rescheduled = (job.rescheduled || 0) + 1;
    next.history.push({ at: opts.at || '', from: job.status, to: to, note: 'นัดใหม่: ' + reason + ' (' + before + ' → ' + after + ')', actor: opts.actor || 'Demo', kind: 'reschedule' });
    next.status = to;
    return next;
  }

  // ---------------------------------------------------------------- summary --
  const ACTIVE = ['traveling', 'in_service', 'awaiting_acceptance'];
  function summary(jobs, today) {
    const out = { today: 0, awaiting: 0, active: 0, waiting_parts: 0, completed: 0 };
    jobs.forEach(function (j) {
      if (j.date === today) out.today += 1;
      if (j.status === 'requested' || j.status === 'awaiting_schedule') out.awaiting += 1;
      if (ACTIVE.indexOf(j.status) >= 0) out.active += 1;
      if (j.status === 'waiting_parts') out.waiting_parts += 1;
      if (j.status === 'completed') out.completed += 1;
    });
    return out;
  }
  const SUMMARY_GROUPS = {
    awaiting: ['requested', 'awaiting_schedule'], active: ACTIVE,
    waiting_parts: ['waiting_parts'], completed: ['completed'],
  };

  function filterJobs(jobs, f, customers) {
    f = f || {};
    const q = String(f.q || '').trim().toLowerCase();
    return jobs.filter(function (j) {
      if (f.type && j.type !== f.type) return false;
      if (f.tech === 'none' && j.techId) return false;
      if (f.tech && f.tech !== 'none' && j.techId !== f.tech) return false;
      if (f.status && SUMMARY_GROUPS[f.status]) { if (SUMMARY_GROUPS[f.status].indexOf(j.status) < 0) return false; }
      else if (f.status && j.status !== f.status) return false;
      if (f.date && j.date !== f.date) return false;
      if (q) {
        const c = customers && customers[j.customerId];
        const hay = [j.id, j.symptom, j.machine.model, j.machine.serial, c && c.name, c && c.site].join(' ').toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
  }

  /** Appointment queue: dated jobs sorted by date then window start; undated jobs last. */
  function queue(jobs) {
    return jobs.slice().sort(function (a, b) {
      const ka = (a.date || '9999') + (a.window ? a.window[0] : '99:99');
      const kb = (b.date || '9999') + (b.window ? b.window[0] : '99:99');
      return ka < kb ? -1 : ka > kb ? 1 : (a.id < b.id ? -1 : 1);
    });
  }

  function techLoad(jobs, techs, date) {
    return techs.map(function (t) {
      const mine = jobs.filter(function (j) { return j.techId === t.id && j.date === date && j.status !== 'returned_to_center'; });
      const minutes = mine.reduce(function (s, j) { return s + (j.serviceMin || 0); }, 0);
      return { techId: t.id, jobs: mine.length, serviceMin: minutes, open: mine.filter(function (j) { return j.status !== 'completed'; }).length };
    });
  }

  // ---------------------------------------------------------------- time --
  function toMin(hhmm) { const p = String(hhmm).split(':'); return Number(p[0]) * 60 + Number(p[1]); }
  function fmt(min) {
    min = Math.round(min);
    const h = Math.floor(min / 60), m = min % 60;
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  function fmtDuration(min) {
    min = Math.round(min);
    const h = Math.floor(min / 60), m = min % 60;
    return h ? h + ' ชม. ' + m + ' นาที' : m + ' นาที';
  }

  // ---------------------------------------------------------------- route (simulated) --
  // Without Google: distance = straight-line km x ROAD_FACTOR, time = distance / AVG_SPEED (Demo estimate,
  // not road routing). With opts.matrix: Google Routes driving distance/time without live traffic.
  const ROUTE_DEFAULTS = { roadFactor: 1.3, speedKmh: 30 };

  // opts.matrix (optional): {'HQ>C1': {km, minutes}, ...} from Google Routes (traffic-unaware), keyed by point id (loc).
  function leg(a, b, opts) {
    opts = Object.assign({}, ROUTE_DEFAULTS, opts || {});
    if (opts.matrix && a.loc && a.loc === b.loc) return { km: 0, minutes: 0, source: 'google' };   // same site
    const hit = opts.matrix && a.loc && b.loc ? opts.matrix[a.loc + '>' + b.loc] : null;
    if (hit) return { km: hit.km, minutes: hit.minutes, source: 'google' };
    const dx = a.x - b.x, dy = a.y - b.y;
    const km = Math.sqrt(dx * dx + dy * dy) * opts.roadFactor;
    return { km: Math.round(km * 10) / 10, minutes: Math.round(km / opts.speedKmh * 60), source: 'simulated' };
  }

  /**
   * plan = { start:{x,y,loc,name}, end:'return'|'last', departAt:'08:30', workEnd:'17:30',
   *          stops:[{id, loc, x, y, window:['09:00','10:00'], serviceMin, postponed?}] }
   * Postponed stops are listed but skipped in timing.
   */
  function planRoute(plan, opts) {
    const legs = [], rows = [], warnings = [], sources = {};
    let clock = toMin(plan.departAt), pos = plan.start, km = 0, travel = 0, service = 0, wait = 0;
    plan.stops.forEach(function (s, i) {
      if (s.postponed) { rows.push({ id: s.id, index: i, skipped: true }); return; }
      const l = leg(pos, s, opts);
      legs.push({ from: pos.id || 'start', to: s.id, km: l.km, minutes: l.minutes, source: l.source });
      sources[l.source] = true;
      km += l.km; travel += l.minutes; clock += l.minutes;
      const arrive = clock;
      const ws = toMin(s.window[0]), we = toMin(s.window[1]);
      const waitMin = Math.max(0, ws - arrive);
      const startService = arrive + waitMin;
      const endService = startService + (s.serviceMin || 0);
      const late = arrive > we;
      if (late) warnings.push({ kind: 'late', id: s.id, minutes: arrive - we, text: 'ไปถึง ' + s.id + ' เวลา ' + fmt(arrive) + ' หลังช่วงนัด ' + s.window.join('–') + ' (ช้า ' + (arrive - we) + ' นาที)' });
      rows.push({ id: s.id, index: i, km: l.km, travelMin: l.minutes, arrive: arrive, wait: waitMin, start: startService, end: endService, late: late, lateBy: late ? arrive - we : 0 });
      wait += waitMin; service += s.serviceMin || 0; clock = endService; pos = s;
    });
    let endAt = clock, back = null;
    const visited = rows.filter(function (r) { return !r.skipped; });
    if (plan.end === 'return' && visited.length) {
      back = leg(pos, plan.start, opts);
      km += back.km; travel += back.minutes; endAt = clock + back.minutes;
      legs.push({ from: pos.id, to: 'end', km: back.km, minutes: back.minutes, source: back.source });
      sources[back.source] = true;
    }
    const workEnd = toMin(plan.workEnd);
    if (endAt > workEnd) warnings.push({ kind: 'overtime', minutes: endAt - workEnd, text: 'แผนจบเวลา ' + fmt(endAt) + ' เกินเวลาทำงาน ' + plan.workEnd + ' (' + (endAt - workEnd) + ' นาที)' });
    overlaps(plan.stops).forEach(function (o) { warnings.push(o); });
    return {
      legs: legs, rows: rows, back: back, warnings: warnings,
      source: sources.google && sources.simulated ? 'mixed' : sources.google ? 'google' : 'simulated',
      totalKm: Math.round(km * 10) / 10, travelMin: travel, serviceMin: service, waitMin: wait,
      departAt: toMin(plan.departAt), endAt: endAt, totalMin: endAt - toMin(plan.departAt),
    };
  }

  /** Two appointments overlap when one starts before the other could finish (start + service). */
  function overlaps(stops) {
    const live = stops.filter(function (s) { return !s.postponed; })
      .slice().sort(function (a, b) { return toMin(a.window[0]) - toMin(b.window[0]); });
    const out = [];
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i], b = live[j];
        if (toMin(b.window[0]) < toMin(a.window[0]) + (a.serviceMin || 0)) {
          out.push({ kind: 'overlap', ids: [a.id, b.id], text: 'เวลานัด ' + a.id + ' (' + a.window[0] + ' + ' + a.serviceMin + ' นาที) ทับกับ ' + b.id + ' (' + b.window[0] + ')' });
        }
      }
    }
    return out;
  }

  function score(result) {
    let s = result.totalMin;
    result.warnings.forEach(function (w) {
      if (w.kind === 'late') s += 10000 + w.minutes * 10;
      if (w.kind === 'overtime') s += 1000 + w.minutes * 10;
    });
    return s;
  }

  function permutations(items) {
    if (items.length <= 1) return [items.slice()];
    const out = [];
    items.forEach(function (item, i) {
      const rest = items.slice(0, i).concat(items.slice(i + 1));
      permutations(rest).forEach(function (p) { out.push([item].concat(p)); });
    });
    return out;
  }

  /**
   * Suggest an order: locked stops keep their position; others are permuted (max 7 movable).
   * Never changes the plan itself — the caller shows the suggestion and lets the technician accept.
   */
  function suggestOrder(plan, opts) {
    const lockedAt = {}, movable = [];
    plan.stops.forEach(function (s, i) { if (s.locked) lockedAt[i] = s; else movable.push(s); });
    if (movable.length > 7) throw new Error('จุดแวะที่จัดลำดับได้มากเกินไปสำหรับ Demo (สูงสุด 7)');
    const current = planRoute(plan, opts);
    let best = { order: plan.stops.map(function (s) { return s.id; }), score: score(current), result: current };
    permutations(movable).forEach(function (perm) {
      const stops = [];
      let k = 0;
      for (let i = 0; i < plan.stops.length; i++) stops.push(lockedAt[i] || perm[k++]);
      const result = planRoute(Object.assign({}, plan, { stops: stops }), opts);
      const sc = score(result);
      if (sc < best.score) best = { order: stops.map(function (s) { return s.id; }), score: sc, result: result };
    });
    const before = plan.stops.map(function (s) { return s.id; });
    return {
      order: best.order, result: best.result, changed: best.order.join() !== before.join(),
      current: current, improvementMin: current.totalMin - best.result.totalMin,
    };
  }

  function moveItem(list, from, to) {
    const out = list.slice();
    if (from < 0 || from >= out.length || to < 0 || to >= out.length) return out;
    const item = out.splice(from, 1)[0];
    out.splice(to, 0, item);
    return out;
  }

  const STOP_STATUS = {
    not_departed: 'ยังไม่ออกเดินทาง', traveling: 'เดินทาง', arrived: 'ถึงหน้างาน',
    done: 'บริการเสร็จ', postponed: 'เลื่อนนัด',
  };
  const STOP_NEXT = { not_departed: 'traveling', traveling: 'arrived', arrived: 'done' };

  return {
    FLOW: FLOW, STATUS: STATUS, TYPES: TYPES, TRANSITIONS: TRANSITIONS, NEXT_HINT: NEXT_HINT,
    SUMMARY_GROUPS: SUMMARY_GROUPS, STOP_STATUS: STOP_STATUS, STOP_NEXT: STOP_NEXT, ROUTE_DEFAULTS: ROUTE_DEFAULTS,
    allowedTransitions: allowedTransitions, applyTransition: applyTransition, canReschedule: canReschedule,
    reschedule: reschedule, summary: summary, filterJobs: filterJobs, queue: queue, techLoad: techLoad,
    toMin: toMin, fmt: fmt, fmtDuration: fmtDuration, leg: leg, planRoute: planRoute, overlaps: overlaps,
    suggestOrder: suggestOrder, moveItem: moveItem, clone: clone,
  };
});
