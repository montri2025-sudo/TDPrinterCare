/* Field-service Demo UI. Everything here is fictional and client-side only:
 * no fetch/XHR, no form posts, no real records. Demo changes live in sessionStorage
 * (this browser tab session) and can be reset at any time. */
(function () {
  'use strict';
  const C = window.FieldServiceCore, Data = window.FieldServiceData;
  const root = document.getElementById('fsd');
  if (!root || !C || !Data) return;
  const config = JSON.parse(document.getElementById('fsd-config').textContent);
  const KEY = 'fsd-demo-state-v1';
  // Google settings from the server: routing = server has a Routes key (key itself never sent here);
  // mapsKey = browser key for Maps JavaScript API (must be referrer-restricted). Points are fictional.
  const G = config.google || { routing: false, mapsKey: null, mapId: 'DEMO_MAP_ID', points: null };
  const $ = function (sel, base) { return (base || document).querySelector(sel); };
  const $$ = function (sel, base) { return Array.prototype.slice.call((base || document).querySelectorAll(sel)); };
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function todayISO() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function nowStamp() {
    const d = new Date();
    return todayISO() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') node.textContent = v;
      else if (k === 'className') node.className = v;
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }
  function svg(tag, attrs, children) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  // ------------------------------------------------------------------ state --
  const fixed = Data.build(todayISO(), G.points);  // static fictional references (customers, techs …)
  fixed.center.loc = 'HQ';
  Object.keys(fixed.customers).forEach(function (k) { fixed.customers[k].loc = k; });
  function freshState() {
    const d = Data.build(todayISO(), G.points);
    const routes = {}; routes[d.route.techId + '|' + d.route.date] = d.route;
    return { version: 1, today: d.today, jobs: d.jobs, routes: routes, checks: {}, notes: {}, filters: {} };
  }
  function load() {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (raw) { const s = JSON.parse(raw); if (s && s.version === 1 && s.today === todayISO()) return s; }
    } catch (e) { /* storage unavailable: Demo still works for this page view */ }
    return freshState();
  }
  let state = load();
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* ignore */ } }
  function jobById(id) { return state.jobs.find(function (j) { return j.id === id; }); }
  function replaceJob(next) { state.jobs = state.jobs.map(function (j) { return j.id === next.id ? next : j; }); }
  function techName(id) { const t = fixed.techs.find(function (x) { return x.id === id; }); return t ? t.name : 'ยังไม่มอบหมาย'; }
  function customer(id) { return fixed.customers[id]; }
  function announce(text) { const live = $('#fsd-live'); live.textContent = ''; setTimeout(function () { live.textContent = text; }, 30); }
  function chip(status) { return h('span', { className: 'fsd-chip fsd-tone-' + C.STATUS[status].tone, text: C.STATUS[status].label }); }
  function dateLabel(iso) {
    if (!iso) return 'ยังไม่นัด';
    const diff = Math.round((new Date(iso) - new Date(state.today)) / 86400000);
    const rel = diff === 0 ? 'วันนี้' : diff === 1 ? 'พรุ่งนี้' : diff === -1 ? 'เมื่อวาน' : diff > 0 ? 'อีก ' + diff + ' วัน' : (-diff) + ' วันก่อน';
    return rel + ' (' + iso + ')';
  }

  // ------------------------------------------------------------------ views/tabs --
  const VIEWS = { control: 'ห้องควบคุมงานบริการ', tech: 'มุมมองช่าง', customer: 'มุมมองลูกค้า', route: 'แผนการเดินทาง' };
  const allowed = config.views.filter(function (v) { return VIEWS[v]; });
  let current = null;
  function buildTabs() {
    const list = $('#fsd-tabs');
    allowed.forEach(function (v) {
      list.appendChild(h('button', { type: 'button', role: 'tab', id: 'fsd-tab-' + v, 'aria-controls': 'fsd-view-' + v, 'aria-selected': 'false', tabindex: '-1', text: VIEWS[v], onclick: function () { show(v, true); } }));
    });
    list.addEventListener('keydown', function (e) {
      const idx = allowed.indexOf(current);
      let next = null;
      if (e.key === 'ArrowRight') next = allowed[(idx + 1) % allowed.length];
      if (e.key === 'ArrowLeft') next = allowed[(idx - 1 + allowed.length) % allowed.length];
      if (e.key === 'Home') next = allowed[0];
      if (e.key === 'End') next = allowed[allowed.length - 1];
      if (next) { e.preventDefault(); show(next, true); $('#fsd-tab-' + next).focus(); }
    });
    Object.keys(VIEWS).forEach(function (v) { if (allowed.indexOf(v) < 0) { const p = $('#fsd-view-' + v); if (p) p.remove(); } });
  }
  function show(view, updateHash) {
    if (allowed.indexOf(view) < 0) view = allowed[0];
    current = view;
    allowed.forEach(function (v) {
      const on = v === view, tab = $('#fsd-tab-' + v), panel = $('#fsd-view-' + v);
      tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1; panel.hidden = !on;
    });
    if (updateHash && history.replaceState) history.replaceState(null, '', '#' + view);
    render();
  }

  // ------------------------------------------------------------------ control room --
  function renderSummary() {
    const s = C.summary(state.jobs, state.today);
    const cards = [['today', 'งานวันนี้', ''], ['awaiting', 'รอนัดหมาย', 'awaiting'], ['active', 'กำลังบริการ', 'active'], ['waiting_parts', 'รออะไหล่', 'waiting_parts'], ['completed', 'เสร็จสิ้น', 'completed']];
    const box = $('#fsd-summary'); box.textContent = '';
    cards.forEach(function (c) {
      box.appendChild(h('button', {
        type: 'button', className: 'fsd-stat fsd-stat-' + c[0], id: 'fsd-count-' + c[0], 'aria-pressed': String(state.filters.status === c[2] && !!c[2]),
        onclick: function () {
          if (c[0] === 'today') { state.filters = Object.assign({}, state.filters, { date: state.filters.date ? '' : state.today, status: '' }); }
          else state.filters = Object.assign({}, state.filters, { status: state.filters.status === c[2] ? '' : c[2], date: '' });
          save(); syncFilterInputs(); renderControl();
        },
      }, [h('span', { className: 'fsd-stat-num', text: String(s[c[0]]) }), h('span', { className: 'fsd-stat-label', text: c[1] })]));
    });
    $('#fsd-summary-note').textContent = 'กำลังบริการ = เดินทาง + กำลังบริการ + รอตรวจรับ · รอนัดหมาย = รับคำขอ + รอนัดหมาย · คลิกการ์ดเพื่อกรอง';
  }
  function buildFilters() {
    const type = $('#fsd-filter-type'), tech = $('#fsd-filter-tech'), status = $('#fsd-filter-status');
    Object.keys(C.TYPES).forEach(function (k) { type.appendChild(h('option', { value: k, text: C.TYPES[k] })); });
    fixed.techs.forEach(function (t) { tech.appendChild(h('option', { value: t.id, text: t.name })); });
    tech.appendChild(h('option', { value: 'none', text: 'ยังไม่มอบหมาย' }));
    [['awaiting', 'กลุ่ม: รอนัดหมาย'], ['active', 'กลุ่ม: กำลังบริการ']].concat(Object.keys(C.STATUS).map(function (k) { return [k, C.STATUS[k].label]; }))
      .forEach(function (o) { status.appendChild(h('option', { value: o[0], text: o[1] })); });
    [type, tech, status].forEach(function (el) {
      el.addEventListener('change', function () { state.filters[el.dataset.key] = el.value; if (el.dataset.key === 'status') state.filters.date = ''; save(); renderControl(); });
    });
    $('#fsd-search').addEventListener('input', function (e) { state.filters.q = e.target.value; save(); renderQueue(); });
    $('#fsd-filter-clear').addEventListener('click', function () { state.filters = {}; save(); syncFilterInputs(); renderControl(); });
    syncFilterInputs();
  }
  function syncFilterInputs() {
    $('#fsd-filter-type').value = state.filters.type || '';
    $('#fsd-filter-tech').value = state.filters.tech || '';
    $('#fsd-filter-status').value = state.filters.status || '';
    $('#fsd-search').value = state.filters.q || '';
  }
  function renderQueue() {
    const rows = C.queue(C.filterJobs(state.jobs, state.filters, fixed.customers));
    const body = $('#fsd-queue-body'); body.textContent = '';
    $('#fsd-queue-count').textContent = 'พบ ' + rows.length + ' ใบงาน' + (state.filters.date ? ' (เฉพาะวันนี้)' : '');
    rows.forEach(function (j) {
      const c = customer(j.customerId);
      body.appendChild(h('tr', {}, [
        h('td', { 'data-label': 'วันนัด' }, [h('div', { text: dateLabel(j.date) }), h('small', { text: j.window ? j.window.join('–') : '—' })]),
        h('td', { 'data-label': 'ใบงาน' }, [h('button', { type: 'button', className: 'fsd-link', text: j.id, onclick: function () { openJob(j.id); } }), h('small', { text: ' ' + C.TYPES[j.type] })]),
        h('td', { 'data-label': 'ลูกค้า/สถานที่' }, [h('div', { text: c.name }), h('small', { text: c.site })]),
        h('td', { 'data-label': 'ช่าง', text: techName(j.techId) }),
        h('td', { 'data-label': 'สถานะ' }, [chip(j.status), j.rescheduled ? h('small', { className: 'fsd-flag', text: ' นัดใหม่ ' + j.rescheduled + ' ครั้ง' }) : null]),
      ]));
    });
    if (!rows.length) body.appendChild(h('tr', {}, [h('td', { colspan: '5', className: 'fsd-empty', text: 'ไม่พบใบงานตามเงื่อนไข' })]));
  }
  function renderLoad() {
    const box = $('#fsd-load'); box.textContent = '';
    C.techLoad(state.jobs, fixed.techs, state.today).forEach(function (l) {
      const pct = Math.min(100, Math.round(l.serviceMin / 480 * 100));
      box.appendChild(h('div', { className: 'fsd-load-row' }, [
        h('div', { className: 'fsd-load-name' }, [h('b', { text: techName(l.techId) }), h('small', { text: ' ' + l.jobs + ' งานวันนี้ · ค้าง ' + l.open })]),
        h('div', { className: 'fsd-bar', role: 'img', 'aria-label': 'เวลาบริการ ' + C.fmtDuration(l.serviceMin) + ' จาก 8 ชั่วโมง' }, [h('span', { style: 'width:' + pct + '%' })]),
        h('small', { text: C.fmtDuration(l.serviceMin) + ' / 8 ชม. (เฉพาะเวลาบริการ ไม่รวมเดินทาง)' }),
      ]));
    });
  }
  function renderControl() { renderSummary(); renderQueue(); renderLoad(); }

  // ------------------------------------------------------------------ job dialog --
  let openJobId = null;
  // opts.modal=false keeps the page interactive (used by the guided tour so its controls stay usable).
  function openJob(id, opts) {
    const modal = !(opts && opts.modal === false);
    openJobId = id;
    renderJobDialog();
    const dlg = $('#fsd-job-dialog');
    if (dlg.open && dlg.dataset.modal !== String(modal)) dlg.close();
    if (!dlg.open) {
      dlg.dataset.modal = String(modal);
      if (modal && dlg.showModal) dlg.showModal(); else if (dlg.show) dlg.show(); else dlg.setAttribute('open', '');
    }
    if (modal) $('#fsd-job-close').focus();
  }
  function renderJobDialog() {
    const j = jobById(openJobId); if (!j) return;
    const c = customer(j.customerId);
    $('#fsd-job-title').textContent = 'ใบงาน ' + j.id + ' · ' + C.TYPES[j.type];
    const info = $('#fsd-job-info'); info.textContent = '';
    [['ลูกค้า', c.name], ['โรงงาน', c.site], ['สถานที่', c.address], ['ผู้ติดต่อ', c.contact + ' · ' + c.phone],
      ['รุ่นเครื่อง', j.machine.model], ['หมายเลขเครื่อง', j.machine.serial], ['อาการ/งาน', j.symptom],
      ['วันนัด', dateLabel(j.date) + (j.window ? ' · ' + j.window.join('–') : '')], ['เวลาบริการโดยประมาณ', C.fmtDuration(j.serviceMin)],
      ['ผู้รับผิดชอบ', techName(j.techId)]].forEach(function (r) { info.appendChild(h('dt', { text: r[0] })); info.appendChild(h('dd', { text: r[1] })); });
    // stepper
    const stepper = $('#fsd-stepper'); stepper.textContent = '';
    const reached = {}; j.history.forEach(function (e) { reached[e.to] = true; });
    C.FLOW.forEach(function (s, i) {
      stepper.appendChild(h('li', { className: (s === j.status ? 'is-current ' : '') + (reached[s] && s !== j.status ? 'is-done' : ''), 'aria-current': s === j.status ? 'step' : null }, [h('span', { className: 'fsd-step-no', text: String(i + 1) }), h('span', { text: C.STATUS[s].label })]));
    });
    const exc = $('#fsd-exception'); exc.textContent = '';
    if (C.FLOW.indexOf(j.status) < 0) exc.appendChild(h('p', { className: 'fsd-exception' }, ['สถานะพิเศษ: ', chip(j.status)]));
    $('#fsd-next').textContent = 'ขั้นตอนถัดไป: ' + C.NEXT_HINT[j.status];
    // actions
    const actions = $('#fsd-actions'); actions.textContent = '';
    if (j.status === 'awaiting_schedule') {
      const sel = h('select', { id: 'fsd-assign', 'aria-label': 'เลือกช่าง' }, [h('option', { value: '', text: '— เลือกช่าง —' })].concat(fixed.techs.map(function (t) { return h('option', { value: t.id, text: t.name }); })));
      sel.value = j.techId || '';
      sel.addEventListener('change', function () { const next = C.clone(j); next.techId = sel.value || null; replaceJob(next); save(); renderAll(); });
      actions.appendChild(h('label', { className: 'fsd-inline' }, ['ช่าง: ', sel]));
    }
    C.allowedTransitions(j).forEach(function (t) {
      actions.appendChild(h('button', { type: 'button', className: 'btn small' + (t.needsReason ? ' secondary' : ''), 'data-to': t.to, text: t.label,
        onclick: function () { if (t.needsReason) askReason(j.id, t.to, t.label); else doTransition(j.id, t.to, ''); } }));
    });
    if (C.canReschedule(j)) actions.appendChild(h('button', { type: 'button', className: 'btn small secondary', 'data-to': 'reschedule', text: 'นัดใหม่', onclick: function () { askReason(j.id, 'reschedule', 'นัดใหม่'); } }));
    if (!actions.children.length) actions.appendChild(h('p', { className: 'fsd-muted', text: 'ไม่มีการเปลี่ยนสถานะเพิ่มเติม' }));
    // history
    const list = $('#fsd-history'); list.textContent = '';
    j.history.forEach(function (e) {
      list.appendChild(h('li', {}, [h('time', { text: e.at || '—' }), h('span', { text: (e.from ? C.STATUS[e.from].label + ' → ' : '') + C.STATUS[e.to].label }), e.note ? h('small', { text: e.note }) : null, h('small', { className: 'fsd-muted', text: e.actor })]));
    });
    $('#fsd-report').textContent = j.report ? 'รายงานบริการ: ' + j.report : '';
  }
  function doTransition(id, to, reason, extra) {
    try {
      const j = jobById(id);
      const next = to === 'reschedule' ? C.reschedule(j, Object.assign({ reason: reason, at: nowStamp() }, extra)) : C.applyTransition(j, to, { reason: reason, at: nowStamp() });
      replaceJob(next); save(); renderAll();
      announce('เปลี่ยน ' + id + ' เป็น “' + C.STATUS[next.status].label + '” แล้ว (ข้อมูลจำลอง)');
      return true;
    } catch (err) { announce(err.message); alertBox(err.message); return false; }
  }
  function alertBox(text) { const box = $('#fsd-reason-error'); if (box) box.textContent = text; }
  let pending = null;
  function askReason(id, to, label) {
    pending = { id: id, to: to };
    const dlg = $('#fsd-reason-dialog');
    $('#fsd-reason-title').textContent = label + ' · ' + id;
    $('#fsd-reason-text').value = '';
    $('#fsd-reason-error').textContent = '';
    const resched = to === 'reschedule';
    $('#fsd-resched-fields').hidden = !resched;
    if (resched) {
      const j = jobById(id);
      $('#fsd-resched-date').value = Data.addDays(state.today, 1);
      $('#fsd-resched-start').value = j.window ? j.window[0] : '09:00';
      $('#fsd-resched-end').value = j.window ? j.window[1] : '10:00';
    }
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    $('#fsd-reason-text').focus();
  }
  function bindReasonDialog() {
    $('#fsd-reason-form').addEventListener('submit', function (e) {
      e.preventDefault();                                   // never submits to the server
      if (!pending) return;
      const extra = {};
      if (pending.to === 'reschedule') {
        const s = $('#fsd-resched-start').value, en = $('#fsd-resched-end').value;
        if (!s || !en || C.toMin(en) <= C.toMin(s)) { alertBox('ช่วงเวลานัดไม่ถูกต้อง'); return; }
        extra.date = $('#fsd-resched-date').value; extra.window = [s, en];
      }
      if (doTransition(pending.id, pending.to, $('#fsd-reason-text').value, extra)) { pending = null; $('#fsd-reason-dialog').close(); }
    });
    $('#fsd-reason-cancel').addEventListener('click', function () { pending = null; $('#fsd-reason-dialog').close(); });
    $('#fsd-job-close').addEventListener('click', function () { $('#fsd-job-dialog').close(); });
    $('#fsd-job-dialog').addEventListener('close', function () { openJobId = null; });
  }

  // ------------------------------------------------------------------ technician view --
  let techSel = 'T1', techJob = null;
  function renderTech() {
    const sel = $('#fsd-tech-select');
    if (!sel.options.length) {
      fixed.techs.forEach(function (t) { sel.appendChild(h('option', { value: t.id, text: t.name })); });
      sel.addEventListener('change', function () { techSel = sel.value; techJob = null; renderTech(); });
    }
    sel.value = techSel;
    const mine = C.queue(state.jobs.filter(function (j) { return j.techId === techSel; }));
    const list = $('#fsd-tech-jobs'); list.textContent = '';
    if (!techJob && mine.length) techJob = (mine.find(function (j) { return j.status !== 'completed'; }) || mine[0]).id;
    mine.forEach(function (j) {
      const c = customer(j.customerId);
      list.appendChild(h('li', {}, [h('button', { type: 'button', className: 'fsd-tech-card' + (techJob === j.id ? ' is-active' : ''), 'aria-pressed': String(techJob === j.id), onclick: function () { techJob = j.id; renderTech(); } },
        [h('b', { text: j.id + ' · ' + C.TYPES[j.type] }), h('span', { text: c.name }), h('small', { text: dateLabel(j.date) + (j.window ? ' ' + j.window.join('–') : '') }), chip(j.status)])]));
    });
    const panel = $('#fsd-tech-detail'); panel.textContent = '';
    const j = jobById(techJob);
    if (!j || j.techId !== techSel) { panel.appendChild(h('p', { className: 'fsd-muted', text: 'ไม่มีงานของช่างคนนี้' })); return; }
    const c = customer(j.customerId);
    panel.appendChild(h('div', { className: 'fsd-tech-head' }, [h('div', {}, [h('h3', { text: j.id + ' · ' + c.name }), h('p', { className: 'fsd-muted', text: c.site + ' · ' + j.machine.model + ' (' + j.machine.serial + ')' }), h('p', { text: C.NEXT_HINT[j.status] })]), h('button', { type: 'button', className: 'btn small', text: 'เปิดใบงาน / เปลี่ยนสถานะ', onclick: function () { openJob(j.id); } })]));
    const checks = state.checks[j.id] || {};
    const done = j.checklist.filter(function (_, i) { return checks[i]; }).length;
    panel.appendChild(h('h4', { id: 'fsd-checklist-title', text: 'Checklist (' + done + '/' + j.checklist.length + ')' }));
    panel.appendChild(h('ul', { className: 'fsd-checklist', id: 'fsd-checklist', 'aria-labelledby': 'fsd-checklist-title' }, j.checklist.map(function (item, i) {
      const box = h('input', { type: 'checkbox', id: 'fsd-chk-' + i });
      box.checked = !!checks[i];
      box.addEventListener('change', function () { state.checks[j.id] = Object.assign({}, state.checks[j.id]); state.checks[j.id][i] = box.checked; save(); renderTech(); $('#fsd-chk-' + i).focus(); });
      return h('li', {}, [box, h('label', { for: 'fsd-chk-' + i, text: item })]);
    })));
    panel.appendChild(h('div', { className: 'fsd-two' }, [
      h('div', {}, [h('h4', { text: 'เครื่องมือ' }), h('ul', {}, j.tools.map(function (t) { return h('li', { text: t }); }))]),
      h('div', {}, [h('h4', { text: 'อะไหล่ที่เตรียม' }), j.parts.length ? h('ul', {}, j.parts.map(function (p) { return h('li', { text: p.name + ' × ' + p.qty }); })) : h('p', { className: 'fsd-muted', text: 'ไม่มี' }), h('small', { className: 'fsd-muted', text: 'อะไหล่จำลอง — Demo ไม่ตัดสต็อก' })]),
    ]));
    const note = h('textarea', { id: 'fsd-tech-note', rows: '3', maxlength: '500', placeholder: 'บันทึกผลการทำงาน (เก็บเฉพาะใน Demo นี้)' });
    note.value = state.notes[j.id] || '';
    note.addEventListener('input', function () { state.notes[j.id] = note.value; save(); });
    panel.appendChild(h('label', { for: 'fsd-tech-note', className: 'fsd-label', text: 'บันทึกผล' }));
    panel.appendChild(note);
    panel.appendChild(h('h4', { text: 'ภาพประกอบ' }));
    const pics = h('div', { className: 'fsd-photos', id: 'fsd-photos' });
    [['ก่อนให้บริการ', '#5f8db0'], ['หลังให้บริการ', '#3f9b7a']].forEach(function (p) {
      pics.appendChild(h('figure', {}, [illustration(p[1], j.machine.model), h('figcaption', { text: p[0] + ' — ภาพประกอบจำลอง' })]));
    });
    panel.appendChild(pics);
  }
  function illustration(color, label) {
    return svg('svg', { viewBox: '0 0 160 100', role: 'img', 'aria-label': 'ภาพประกอบจำลองของ ' + label }, [
      svg('rect', { x: '1', y: '1', width: '158', height: '98', rx: '8', fill: 'none', stroke: 'currentColor', 'stroke-opacity': '.25' }),
      svg('rect', { x: '45', y: '18', width: '70', height: '62', rx: '6', fill: color, 'fill-opacity': '.35', stroke: color }),
      svg('rect', { x: '58', y: '30', width: '44', height: '30', rx: '3', fill: 'none', stroke: color }),
      svg('rect', { x: '70', y: '64', width: '20', height: '6', rx: '2', fill: color }),
      svg('text', { x: '80', y: '94', 'text-anchor': 'middle', 'font-size': '9', fill: 'currentColor', text: 'DEMO' }),
    ]);
  }

  // ------------------------------------------------------------------ customer view --
  let factoryMachine = null;
  function renderCustomer() {
    const cust = customer('C1');
    $('#fsd-factory-name').textContent = cust.name + ' · ' + cust.site;
    const floor = $('#fsd-factory'); floor.textContent = '';
    const zones = {};
    fixed.factories.C1.forEach(function (m) { (zones[m.zone] = zones[m.zone] || []).push(m); });
    Object.keys(zones).forEach(function (z) {
      floor.appendChild(h('section', { className: 'fsd-zone', 'aria-label': z }, [h('h4', { text: z }), h('div', { className: 'fsd-machines' }, zones[z].map(function (m) {
        const j = m.jobId ? jobById(m.jobId) : null;
        const tone = j ? C.STATUS[j.status].tone : 'grey';
        return h('button', { type: 'button', className: 'fsd-machine fsd-tone-' + tone + (factoryMachine === m.id ? ' is-active' : ''), 'aria-pressed': String(factoryMachine === m.id), onclick: function () { factoryMachine = m.id; renderCustomer(); } },
          [h('span', { className: 'fsd-machine-icon', 'aria-hidden': 'true' }), h('b', { text: m.model }), h('small', { text: j ? C.STATUS[j.status].label : 'ไม่มีงานบริการ' })]);
      }))]));
    });
    const panel = $('#fsd-factory-panel'); panel.textContent = '';
    const m = fixed.factories.C1.find(function (x) { return x.id === factoryMachine; });
    if (!m) { panel.appendChild(h('p', { className: 'fsd-muted', text: 'คลิกเครื่องในโรงงานเพื่อดูนัดหมาย สถานะ และรายงานบริการ' })); return; }
    const j = m.jobId ? jobById(m.jobId) : null;
    panel.appendChild(h('h3', { text: m.model }));
    panel.appendChild(h('p', { className: 'fsd-muted', text: 'หมายเลขเครื่อง ' + m.serial + ' · ' + m.zone }));
    if (!j) { panel.appendChild(h('p', { text: 'ยังไม่มีนัดหมายบริการสำหรับเครื่องนี้' })); return; }
    panel.appendChild(h('dl', { className: 'fsd-dl' }, [h('dt', { text: 'นัดหมาย' }), h('dd', { text: dateLabel(j.date) + (j.window ? ' · ' + j.window.join('–') : '') }), h('dt', { text: 'งาน' }), h('dd', { text: C.TYPES[j.type] + ' · ' + j.symptom }), h('dt', { text: 'สถานะ' }), h('dd', {}, [chip(j.status)]), h('dt', { text: 'ช่าง' }), h('dd', { text: techName(j.techId) })]));
    panel.appendChild(h('p', { className: 'fsd-report', text: j.report ? 'รายงานบริการ: ' + j.report : 'รายงานบริการจะแสดงเมื่องานเสร็จสิ้น' }));
  }

  // ------------------------------------------------------------------ route planner --
  let routeTech = 'T1', routeDate = null, suggestion = null, dragFrom = null;
  function routeKey() { return routeTech + '|' + (routeDate || state.today); }
  function route() {
    const key = routeKey();
    if (!state.routes[key]) state.routes[key] = { techId: routeTech, date: routeDate || state.today, departAt: '08:30', workEnd: '17:30', end: 'return', order: [], locked: {}, stopStatus: {} };
    return state.routes[key];
  }
  function planFor(r) {
    return {
      start: fixed.center, end: r.end, departAt: r.departAt, workEnd: r.workEnd,
      stops: r.order.map(function (id) {
        const j = jobById(id), c = customer(j.customerId);
        return { id: id, loc: c.id, x: c.x, y: c.y, window: j.window, serviceMin: j.serviceMin, locked: !!r.locked[id], postponed: r.stopStatus[id] === 'postponed' };
      }),
    };
  }
  function bindRouteControls() {
    const tech = $('#fsd-route-tech');
    fixed.techs.forEach(function (t) { tech.appendChild(h('option', { value: t.id, text: t.name })); });
    tech.addEventListener('change', function () { routeTech = tech.value; suggestion = null; renderRoute(); });
    $('#fsd-route-date').addEventListener('change', function (e) { routeDate = e.target.value || state.today; suggestion = null; renderRoute(); });
    $('#fsd-route-end').addEventListener('change', function (e) { route().end = e.target.value; suggestion = null; save(); renderRoute(); });
    $('#fsd-route-depart').addEventListener('change', function (e) { if (e.target.value) { route().departAt = e.target.value; suggestion = null; save(); renderRoute(); } });
    $('#fsd-route-workend').addEventListener('change', function (e) { if (e.target.value) { route().workEnd = e.target.value; suggestion = null; save(); renderRoute(); } });
    $('#fsd-route-add').addEventListener('click', function () {
      const id = $('#fsd-route-candidate').value; if (!id) return;
      route().order.push(id); suggestion = null; save(); renderRoute(); announce('เพิ่ม ' + id + ' เข้าแผนแล้ว');
    });
    $('#fsd-route-suggest').addEventListener('click', function () {
      try { suggestion = C.suggestOrder(planFor(route()), routeOpts(route())); } catch (err) { announce(err.message); return; }
      renderRoute(); $('#fsd-suggest-box').focus();
    });
  }
  function moveStop(from, to) {
    const r = route();
    r.order = C.moveItem(r.order, from, to); suggestion = null; save(); renderRoute();
    announce('ย้าย ' + r.order[to] + ' ไปลำดับที่ ' + (to + 1));
  }
  function renderRoute() {
    const r = route();
    $('#fsd-route-tech').value = routeTech;
    $('#fsd-route-date').value = routeDate || state.today;
    $('#fsd-route-end').value = r.end;
    $('#fsd-route-depart').value = r.departAt;
    $('#fsd-route-workend').value = r.workEnd;
    // candidates: this tech's jobs that day with an appointment window, not yet in plan
    const cand = $('#fsd-route-candidate'); cand.textContent = '';
    const pool = state.jobs.filter(function (j) { return j.techId === routeTech && j.date === (routeDate || state.today) && j.window && r.order.indexOf(j.id) < 0 && j.status !== 'completed'; });
    cand.appendChild(h('option', { value: '', text: pool.length ? '— เลือกใบงานเพื่อเพิ่มจุดแวะ —' : 'ไม่มีใบงานอื่นของช่างในวันนี้' }));
    pool.forEach(function (j) { cand.appendChild(h('option', { value: j.id, text: j.id + ' · ' + customer(j.customerId).name + ' · ' + j.window.join('–') })); });
    $('#fsd-route-add').disabled = !pool.length;

    const plan = planFor(r);
    const result = C.planRoute(plan, routeOpts(r));
    const viaGoogle = result.source === 'google';
    $('#fsd-route-disclaimer').textContent = viaGoogle
      ? 'ระยะทางและเวลาเดินทางจาก Google Routes API แบบไม่คิดสภาพจราจร (ไม่มีข้อมูลจราจรสด ไม่รับประกันว่าเร็วที่สุด) · ลูกค้าเป็นบริษัทสมมติที่วางบนถนนสาธารณะใกล้ศูนย์ ไม่ใช่ที่ตั้งบริษัทจริง · ส่งให้ Google เฉพาะพิกัดจุดแวะ · ไม่ขอตำแหน่งปัจจุบัน'
      : 'ข้อมูลจำลอง: ระยะทาง = ระยะเส้นตรง × 1.3 และเวลา = ความเร็วเฉลี่ย 30 กม./ชม. ไม่ใช่เส้นทางถนนจริง ไม่มีข้อมูลจราจร และไม่ใช่เส้นทางที่เร็วที่สุด · ไม่ขอตำแหน่งปัจจุบัน'
        + (G.routing ? (gm.failed ? ' · ขอข้อมูลจาก Google ไม่สำเร็จ (' + gm.failed + ') จึงใช้ค่าประมาณแทน' : ' · กำลังขอระยะทางจาก Google…') : '');
    const rowById = {}; result.rows.forEach(function (x) { rowById[x.id] = x; });

    // list
    const list = $('#fsd-route-list'); list.textContent = '';
    let n = 0;
    r.order.forEach(function (id, i) {
      const j = jobById(id), c = customer(j.customerId), row = rowById[id];
      const st = r.stopStatus[id] || 'not_departed';
      if (!row.skipped) n += 1;
      const stSel = h('select', { 'aria-label': 'สถานะจุดแวะ ' + id }, Object.keys(C.STOP_STATUS).map(function (k) { return h('option', { value: k, text: C.STOP_STATUS[k] }); }));
      stSel.value = st;
      stSel.addEventListener('change', function () { r.stopStatus[id] = stSel.value; suggestion = null; save(); renderRoute(); announce(id + ': ' + C.STOP_STATUS[stSel.value]); });
      const lock = h('input', { type: 'checkbox', id: 'fsd-lock-' + id });
      lock.checked = !!r.locked[id];
      lock.addEventListener('change', function () { r.locked[id] = lock.checked; suggestion = null; save(); renderRoute(); });
      const li = h('li', { className: 'fsd-stop' + (row.late ? ' is-late' : '') + (row.skipped ? ' is-skipped' : ''), draggable: 'true', 'data-id': id, 'data-index': String(i) }, [
        h('span', { className: 'fsd-stop-no', 'aria-hidden': 'true', text: row.skipped ? '–' : String(n) }),
        h('div', { className: 'fsd-stop-main' }, [
          h('div', {}, [h('button', { type: 'button', className: 'fsd-link', text: id, onclick: function () { openJob(id); } }), h('span', { text: ' · ' + c.name })]),
          h('small', { text: 'นัด ' + j.window.join('–') + ' · บริการ ' + j.serviceMin + ' นาที' }),
          row.skipped ? h('small', { className: 'fsd-muted', text: 'เลื่อนนัด — ไม่นับในเวลาของวันนี้' }) :
            h('small', { text: 'เดินทาง ' + row.km + ' กม. ~' + row.travelMin + ' นาที · ถึง ' + C.fmt(row.arrive) + (row.wait ? ' (รอ ' + row.wait + ' นาที)' : '') + ' · เสร็จ ' + C.fmt(row.end) }),
          row.late ? h('strong', { className: 'fsd-warn-text', text: '⚠ ไปไม่ทันช่วงนัด ช้า ' + row.lateBy + ' นาที' }) : null,
        ]),
        h('div', { className: 'fsd-stop-tools' }, [
          stSel,
          h('label', { className: 'fsd-inline', for: 'fsd-lock-' + id }, [lock, ' ล็อกลำดับ']),
          h('div', { className: 'fsd-move' }, [
            h('button', { type: 'button', className: 'fsd-icon-btn', 'aria-label': 'เลื่อน ' + id + ' ขึ้น', disabled: i === 0, text: '↑', onclick: function () { moveStop(i, i - 1); focusMove(id, 'up'); } }),
            h('button', { type: 'button', className: 'fsd-icon-btn', 'aria-label': 'เลื่อน ' + id + ' ลง', disabled: i === r.order.length - 1, text: '↓', onclick: function () { moveStop(i, i + 1); focusMove(id, 'down'); } }),
            h('button', { type: 'button', className: 'fsd-icon-btn', 'aria-label': 'ลบ ' + id + ' ออกจากแผน', text: '✕', onclick: function () { r.order.splice(i, 1); delete r.locked[id]; delete r.stopStatus[id]; suggestion = null; save(); renderRoute(); announce('ลบ ' + id + ' ออกจากแผนแล้ว'); } }),
          ]),
        ]),
      ]);
      li.addEventListener('dragstart', function (e) { dragFrom = i; li.classList.add('is-dragging'); try { e.dataTransfer.setData('text/plain', id); e.dataTransfer.effectAllowed = 'move'; } catch (er) { /* ignore */ } });
      li.addEventListener('dragend', function () { li.classList.remove('is-dragging'); });
      li.addEventListener('dragover', function (e) { e.preventDefault(); });
      li.addEventListener('drop', function (e) { e.preventDefault(); if (dragFrom !== null && dragFrom !== i) moveStop(dragFrom, i); dragFrom = null; });
      list.appendChild(li);
    });
    if (!r.order.length) list.appendChild(h('li', { className: 'fsd-empty', text: 'ยังไม่มีจุดแวะ เลือกใบงานด้านบนเพื่อเพิ่ม' }));

    renderMap(r, result);
    // totals
    const t = $('#fsd-route-totals'); t.textContent = '';
    const src = viaGoogle ? ' (Google ไม่คิดจราจร)' : ' (ประมาณจำลอง)';
    [['ระยะทางรวม' + src, result.totalKm + ' กม.'], ['เวลาเดินทาง' + src, C.fmtDuration(result.travelMin)], ['เวลาบริการ', C.fmtDuration(result.serviceMin)], ['เวลารอหน้างาน', C.fmtDuration(result.waitMin)],
      ['ออกเดินทาง', r.departAt], [r.end === 'return' ? 'กลับถึงศูนย์ (ETA)' : 'จบงานรายสุดท้าย (ETA)', C.fmt(result.endAt)], ['เวลารวมทั้งวัน', C.fmtDuration(result.totalMin)]]
      .forEach(function (x) { t.appendChild(h('div', {}, [h('dt', { text: x[0] }), h('dd', { text: x[1] })])); });
    const w = $('#fsd-route-warnings'); w.textContent = '';
    if (!result.warnings.length) w.appendChild(h('li', { className: 'fsd-ok', text: 'ไม่พบปัญหาเวลานัด เวลาทับซ้อน หรือเวลาทำงานเกิน' + (viaGoogle ? ' (ตามเวลาเดินทางจาก Google แบบไม่คิดจราจร)' : ' (ตามค่าประมาณจำลอง)') }));
    result.warnings.forEach(function (x) { w.appendChild(h('li', { className: 'fsd-warn-' + x.kind, text: '⚠ ' + x.text })); });
    // suggestion preview (never applied automatically)
    const box = $('#fsd-suggest-box'); box.textContent = ''; box.hidden = !suggestion;
    if (suggestion) {
      if (!suggestion.changed) box.appendChild(h('p', { text: 'ลำดับปัจจุบันดีที่สุดตามเกณฑ์แล้ว (คำนึงถึงเวลานัด เวลาบริการ และจุดที่ล็อก)' }));
      else {
        box.appendChild(h('p', {}, [h('b', { text: 'ลำดับที่แนะนำ: ' }), suggestion.order.join(' → ')]));
        box.appendChild(h('p', { className: 'fsd-muted', text: 'ปัจจุบัน: เตือน ' + suggestion.current.warnings.length + ' รายการ จบ ' + C.fmt(suggestion.current.endAt) + ' · แนะนำ: เตือน ' + suggestion.result.warnings.length + ' รายการ จบ ' + C.fmt(suggestion.result.endAt) }));
        box.appendChild(h('div', { className: 'fsd-row' }, [
          h('button', { type: 'button', className: 'btn small', id: 'fsd-suggest-apply', text: 'ใช้ลำดับนี้', onclick: function () { route().order = suggestion.order.slice(); suggestion = null; save(); renderRoute(); announce('ใช้ลำดับที่แนะนำแล้ว'); } }),
          h('button', { type: 'button', className: 'btn small secondary', text: 'ไม่ใช้', onclick: function () { suggestion = null; renderRoute(); } }),
        ]));
      }
    }
  }
  function focusMove(id, dir) {
    const li = $('.fsd-stop[data-id="' + id + '"]');
    if (!li) return;
    // keep keyboard focus on the moved item: same direction if still possible, else the opposite one
    const same = li.querySelector('[aria-label="เลื่อน ' + id + (dir === 'up' ? ' ขึ้น' : ' ลง') + '"]');
    const other = li.querySelector('[aria-label="เลื่อน ' + id + (dir === 'up' ? ' ลง' : ' ขึ้น') + '"]');
    (same && !same.disabled ? same : other && !other.disabled ? other : li.querySelector('.fsd-link')).focus();
  }
  // ---------------------------------------------------------------- Google (optional) --
  const gm = { matrix: {}, pending: {}, failed: null, failedKey: null, routes: {}, routePending: {}, routeFailed: {} };
  function routeLocs(r) {
    const locs = ['HQ'];
    r.order.forEach(function (id) { const loc = jobById(id).customerId; if (locs.indexOf(loc) < 0) locs.push(loc); });
    return locs;
  }
  function getJson(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (res) { return res.json().then(function (body) { return { ok: res.ok && body && body.ok, body: body || {} }; }); });
  }
  /** Matrix of Google driving times between the plan's points (one cached request per point set). */
  function routeOpts(r) {
    if (!G.routing || !r.order.length) return {};
    const locs = routeLocs(r), key = locs.slice().sort().join(',');
    if (gm.matrix[key]) return { matrix: gm.matrix[key] };
    if (!gm.pending[key] && gm.failedKey !== key) {
      gm.pending[key] = true;
      getJson('/field-service/google/matrix?ids=' + encodeURIComponent(locs.join(',')))
        .then(function (x) { if (x.ok) { gm.matrix[key] = x.body.pairs; gm.failed = null; } else { gm.failed = x.body.error || 'error'; gm.failedKey = key; } })
        .catch(function () { gm.failed = 'network'; gm.failedKey = key; })
        .then(function () { delete gm.pending[key]; if (current === 'route') renderRoute(); });
    }
    return {};
  }
  let mapsPromise = null, gmap = null, gOverlays = [];
  function loadGoogleMaps() {
    if (mapsPromise) return mapsPromise;
    mapsPromise = new Promise(function (resolve, reject) {
      window.__fsdMapsReady = function () { resolve(window.google.maps); };
      window.gm_authFailure = function () { reject(new Error('auth')); useSvgMap('คีย์แผนที่ Google ใช้ไม่ได้ จึงแสดงผังจำลองแทน'); };
      const s = document.createElement('script');
      s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(G.mapsKey) + '&v=weekly&libraries=marker,geometry&language=th&region=TH&loading=async&callback=__fsdMapsReady';
      s.async = true;
      s.onerror = function () { reject(new Error('load')); };
      document.head.appendChild(s);
    });
    mapsPromise.catch(function () { useSvgMap('โหลดแผนที่ Google ไม่สำเร็จ จึงแสดงผังจำลองแทน'); });
    return mapsPromise;
  }
  let svgFallbackReason = null;
  function useSvgMap(reason) {
    svgFallbackReason = reason;
    $('#fsd-gmap').hidden = true; $('#fsd-map').removeAttribute('hidden');
    $('#fsd-map-legend').textContent = reason + ' · S = ศูนย์บริการ · ตัวเลข = ลำดับแวะ · เส้นประ = ลำดับการแวะเท่านั้น ไม่ใช่เส้นทางถนน';
    if (current === 'route') renderRoute();
  }
  function routeSeq(r) {
    const seq = ['HQ'];
    r.order.forEach(function (id) { if (r.stopStatus[id] !== 'postponed') seq.push(jobById(id).customerId); });
    if (r.end === 'return' && seq.length > 1) seq.push('HQ');
    return seq.filter(function (loc, i) { return i === 0 || loc !== seq[i - 1]; });
  }
  function renderGoogleMap(r, result) {
    $('#fsd-map').setAttribute('hidden', ''); $('#fsd-gmap').hidden = false;
    loadGoogleMaps().then(function (maps) {
      if (current !== 'route') return;
      if (!gmap) gmap = new maps.Map($('#fsd-gmap'), { center: { lat: fixed.center.lat, lng: fixed.center.lng }, zoom: 12, mapId: G.mapId, gestureHandling: 'cooperative', streetViewControl: false, mapTypeControl: false, fullscreenControl: false });
      gOverlays.forEach(function (o) { if (o.setMap) o.setMap(null); else o.map = null; });
      gOverlays = [];
      const bounds = new maps.LatLngBounds();
      function pin(pos, glyph, color, title, onClick) {
        const el = new maps.marker.PinElement({ glyph: glyph, background: color, borderColor: '#ffffff', glyphColor: '#ffffff' });
        const m = new maps.marker.AdvancedMarkerElement({ map: gmap, position: pos, content: el.element, title: title, gmpClickable: !!onClick });
        if (onClick) m.addListener('click', onClick);
        gOverlays.push(m); bounds.extend(pos);
      }
      pin({ lat: fixed.center.lat, lng: fixed.center.lng }, 'S', '#1b2b3c', 'ศูนย์บริการ (จุดเริ่มต้น)', null);
      let n = 0;
      r.order.forEach(function (id) {
        const j = jobById(id), c = customer(j.customerId), row = result.rows.find(function (x) { return x.id === id; });
        const skipped = row && row.skipped; if (!skipped) n += 1;
        pin({ lat: c.lat, lng: c.lng }, skipped ? '–' : String(n), skipped ? '#64748b' : row && row.late ? '#b91c1c' : '#216e61',
          'หมุด ' + (skipped ? 'เลื่อนนัด' : n) + ' ' + id + ' ' + c.name + ' (เปิดใบงาน)', function () { openJob(id); });
      });
      if (!bounds.isEmpty()) gmap.fitBounds(bounds, 48);
      // Road polyline only from Google Routes; never draw straight lines on a real map.
      const seq = routeSeq(r), key = seq.join(',');
      const legend = $('#fsd-map-legend');
      if (!G.routing) { legend.textContent = 'แผนที่ Google · ยังไม่ได้ตั้งค่า Routes API จึงไม่แสดงเส้นทาง (ระยะทาง/เวลาเป็นค่าประมาณจำลอง)'; return; }
      if (seq.length < 2) { legend.textContent = 'แผนที่ Google · ยังไม่มีจุดแวะ'; return; }
      const draw = function (encoded) {
        const line = new maps.Polyline({ map: gmap, path: maps.geometry.encoding.decodePath(encoded), strokeColor: '#216e61', strokeOpacity: .85, strokeWeight: 5 });
        gOverlays.push(line);
        legend.textContent = 'เส้นทางขับรถจาก Google Routes (ไม่คิดสภาพจราจร) ตามลำดับที่เลือก · S = ศูนย์บริการ · ตัวเลข = ลำดับแวะ · คลิกหมุดเพื่อเปิดใบงาน';
      };
      if (gm.routes[key]) { draw(gm.routes[key]); return; }
      if (gm.routeFailed[key]) { legend.textContent = 'ขอเส้นทางจาก Google ไม่สำเร็จ (' + gm.routeFailed[key] + ') — แสดงเฉพาะหมุด'; return; }
      legend.textContent = 'กำลังขอเส้นทางจาก Google…';
      if (gm.routePending[key]) return;
      gm.routePending[key] = true;
      getJson('/field-service/google/route?seq=' + encodeURIComponent(key))
        .then(function (x) { if (x.ok && x.body.polyline) gm.routes[key] = x.body.polyline; else gm.routeFailed[key] = x.body.error || 'error'; })
        .catch(function () { gm.routeFailed[key] = 'network'; })
        .then(function () { delete gm.routePending[key]; if (current === 'route') renderRoute(); });
    }).catch(function () { /* fallback handled in loadGoogleMaps */ });
  }

  function renderMap(r, result) {
    if (G.mapsKey && !svgFallbackReason) { renderGoogleMap(r, result); return; }
    const map = $('#fsd-map'); map.textContent = '';
    const pts = [fixed.center].concat(r.order.map(function (id) { return customer(jobById(id).customerId); }));
    Object.keys(fixed.customers).forEach(function (k) { pts.push(fixed.customers[k]); });
    const xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
    const minX = Math.min.apply(null, xs) - 3, maxX = Math.max.apply(null, xs) + 3, minY = Math.min.apply(null, ys) - 3, maxY = Math.max.apply(null, ys) + 3;
    const W = 600, H = 420;
    const sx = function (x) { return (x - minX) / (maxX - minX) * W; }, sy = function (y) { return H - (y - minY) / (maxY - minY) * H; };
    const g = svg('g', {});
    for (let x = Math.ceil(minX); x <= maxX; x += 2) g.appendChild(svg('line', { x1: sx(x), y1: 0, x2: sx(x), y2: H, class: 'fsd-grid' }));
    for (let y = Math.ceil(minY); y <= maxY; y += 2) g.appendChild(svg('line', { x1: 0, y1: sy(y), x2: W, y2: sy(y), class: 'fsd-grid' }));
    map.appendChild(g);
    // order connector (explicitly NOT a road route)
    const seq = [fixed.center].concat(r.order.filter(function (id) { return r.stopStatus[id] !== 'postponed'; }).map(function (id) { return customer(jobById(id).customerId); }));
    if (r.end === 'return' && seq.length > 1) seq.push(fixed.center);
    if (seq.length > 1) map.appendChild(svg('polyline', { points: seq.map(function (p) { return sx(p.x) + ',' + sy(p.y); }).join(' '), class: 'fsd-connector' }));
    // other fictional customers (not in plan)
    Object.keys(fixed.customers).forEach(function (k) {
      const c = fixed.customers[k];
      map.appendChild(svg('circle', { cx: sx(c.x), cy: sy(c.y), r: 4, class: 'fsd-dot' }));
    });
    map.appendChild(svg('g', { class: 'fsd-start' }, [svg('rect', { x: sx(0) - 13, y: sy(0) - 13, width: 26, height: 26, rx: 6 }), svg('text', { x: sx(0), y: sy(0) + 5, 'text-anchor': 'middle', text: 'S' })]));
    let n = 0;
    r.order.forEach(function (id) {
      const j = jobById(id), c = customer(j.customerId), row = result.rows.find(function (x) { return x.id === id; });
      const skipped = row && row.skipped; if (!skipped) n += 1;
      const label = skipped ? '–' : String(n);
      const pin = svg('g', { class: 'fsd-pin' + (row && row.late ? ' is-late' : '') + (skipped ? ' is-skipped' : ''), tabindex: '0', role: 'button', 'data-id': id, 'aria-label': 'หมุด ' + label + ' ' + id + ' ' + c.name + ' เปิดใบงาน',
        onclick: function () { openJob(id); }, onkeydown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openJob(id); } } }, [
        svg('circle', { cx: sx(c.x), cy: sy(c.y), r: 15 }),
        svg('text', { x: sx(c.x), y: sy(c.y) + 5, 'text-anchor': 'middle', text: label }),
        svg('text', { x: sx(c.x), y: sy(c.y) + 32, 'text-anchor': 'middle', class: 'fsd-pin-label', text: c.name.replace(/^บริษัท |^หจก\. | จำกัด$/g, '') }),
      ]);
      map.appendChild(pin);
    });
  }

  // ------------------------------------------------------------------ boot --
  function renderAll() {
    if (allowed.indexOf('control') >= 0) renderControl();
    if (openJobId) renderJobDialog();
    render();
  }
  function render() {
    if (current === 'control') renderControl();
    if (current === 'tech') renderTech();
    if (current === 'customer') renderCustomer();
    if (current === 'route') renderRoute();
  }
  $('#fsd-reset').addEventListener('click', function () {
    state = freshState(); try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
    suggestion = null; techJob = null; factoryMachine = null; routeTech = 'T1'; routeDate = null;
    if ($('#fsd-job-dialog').open) $('#fsd-job-dialog').close();
    if ($('#fsd-filter-type')) syncFilterInputs();
    renderAll(); announce('ล้างข้อมูล Demo กลับค่าเริ่มต้นแล้ว');
  });
  buildTabs();
  if (allowed.indexOf('control') >= 0) buildFilters();
  if (allowed.indexOf('route') >= 0) bindRouteControls();
  bindReasonDialog();
  if (config.role === 'technician') techSel = 'T1';
  const fromHash = (location.hash || '').slice(1);
  show(allowed.indexOf(fromHash) >= 0 ? fromHash : config.defaultView);
  window.addEventListener('hashchange', function () { const v = (location.hash || '').slice(1); if (v !== current && allowed.indexOf(v) >= 0) show(v); });
  root.classList.toggle('fsd-reduced-motion', !!reduceMotion);

  // Small API for the guided tour (field-service-tour.js). Read/navigate only.
  window.FieldServiceDemo = {
    views: allowed.slice(),
    current: function () { return current; },
    label: function (view) { return VIEWS[view]; },
    show: function (view) { show(view, true); },
    openJob: openJob,
    closeDialogs: function () { $$('dialog[open]', root).forEach(function (d) { d.close(); }); },
  };
})();
