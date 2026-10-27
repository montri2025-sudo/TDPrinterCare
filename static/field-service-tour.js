/* Guided Thai tour for the field-service Demo, styled and behaving like the customer Virtual Office Demo:
 * "Demo แนะนำหน้านี้" explains the current tab; with "เล่นต่อทุกแท็บ" it continues tab by tab
 * (ห้องควบคุม → ใบงาน → ช่าง → ลูกค้า → แผนการเดินทาง, per role). It never changes Demo state. Narration MP3s (if generated) come from /static/field-service-voice/
 * via manifest.json keyed by the exact text below. Missing clips fall back to timed captions
 * (no substitute voice). tools/make-field-service-voice.py parses the step(...) lines. */
(function () {
  'use strict';
  const el = function (id) { return document.getElementById('fsd-tour-' + id); };
  const api = window.FieldServiceDemo;
  if (!el('start') || !api) return;
  const step = function (view, target, title, text) { return { view: view, target: target, title: title, text: text }; };
  const ALL = [
    step('control', '#fsd-title', 'Demo บริการนอกสถานที่', 'เมนูนี้ใช้วางแผนส่งช่างไปติดตั้ง ตรวจเช็ก ซ่อม และบำรุงรักษาเครื่องพิมพ์ที่โรงงานลูกค้า ทุกชื่อและตัวเลขเป็นข้อมูลจำลอง การเปลี่ยนแปลงไม่บันทึกลงระบบจริงครับ'),
    step('control', '#fsd-summary', 'สรุปงานบริการ', 'การ์ดด้านบนสรุปงานวันนี้ งานรอนัดหมาย งานที่กำลังบริการ งานรออะไหล่ และงานที่เสร็จสิ้น คลิกการ์ดเพื่อกรองรายการด้านล่าง'),
    step('control', '#fsd-filters', 'ค้นหาและกรองงาน', 'ค้นหาด้วยเลขใบงาน ชื่อลูกค้า หรือรุ่นเครื่อง แล้วกรองตามประเภทงาน ช่าง และสถานะ'),
    step('control', '#fsd-queue', 'คิวนัดหมาย', 'คิวเรียงตามวันและเวลานัด คลิกเลขใบงานเพื่อเปิดรายละเอียด ลูกค้า โรงงาน ผู้ติดต่อ รุ่นเครื่อง หมายเลขเครื่อง และอาการ'),
    step('control', '#fsd-load', 'ภาระงานของช่าง', 'แถบนี้แสดงจำนวนงานและเวลาบริการของช่างแต่ละคนในวันนี้ ใช้ประกอบการมอบหมายงาน'),
    step('job:FS-1004', '#fsd-stepper', 'ลำดับขั้นของใบงาน', 'ใบงานไล่ขั้นตั้งแต่รับคำขอ รอนัดหมาย มอบหมายช่าง เตรียมพร้อม เดินทาง กำลังบริการ รอตรวจรับ จนเสร็จสิ้น พร้อมบอกขั้นตอนถัดไป'),
    step('job:FS-1004', '#fsd-actions', 'เปลี่ยนสถานะและกรณีพิเศษ', 'ปุ่มเหล่านี้เปลี่ยนสถานะทีละขั้น ถ้าต้องรออะไหล่ นัดใหม่ หรือนำเครื่องกลับศูนย์ ระบบจะให้ระบุเหตุผลทุกครั้ง'),
    step('job:FS-1004', '#fsd-history', 'ประวัติการเปลี่ยนสถานะ', 'ประวัติแสดงเวลา สถานะเดิม สถานะใหม่ เหตุผล และผู้ทำรายการ ตัวเลขสรุปในห้องควบคุมจะเปลี่ยนตามทันที'),
    step('tech', '#fsd-tech-jobs', 'มุมมองช่าง', 'ช่างเห็นงานที่ตนรับผิดชอบเรียงตามเวลานัด เลือกงานเพื่อดูรายละเอียด'),
    step('tech', '#fsd-tech-detail', 'Checklist และบันทึกผล', 'ติ๊ก Checklist ตรวจเครื่องมือและอะไหล่ที่เตรียม บันทึกผล และดูภาพประกอบจำลอง อะไหล่ใน Demo ไม่ตัดสต็อก'),
    step('customer', '#fsd-factory', 'โรงงานของลูกค้า', 'ลูกค้าเห็นผังโรงงานเสมือนของตนเอง คลิกเครื่องเพื่อดูวันนัด สถานะ และรายงานบริการ'),
    step('route', '#fsd-route-controls', 'แผนการเดินทาง', 'เลือกช่างและวันที่ กำหนดเวลาออกเดินทาง และเลือกว่าจะกลับศูนย์หรือจบที่ลูกค้ารายสุดท้าย'),
    step('route', '.fsd-map-card', 'หมุดตามลำดับ', 'หมุดหมายเลขบนแผนที่ตรงกับรายการด้านข้าง ถ้าเชื่อมกูเกิลแล้วจะเห็นเส้นทางขับรถ ถ้ายังไม่เชื่อมจะเป็นผังจำลองที่เส้นประบอกแค่ลำดับ ไม่ใช่เส้นทางถนนจริง คลิกหมุดเพื่อเปิดใบงาน'),
    step('route', '#fsd-route-list', 'จัดลำดับจุดแวะ', 'ลากเพื่อสลับลำดับ หรือใช้ปุ่มขึ้นและลงบนมือถือและคีย์บอร์ด ล็อกจุดที่ไม่ต้องการย้าย และปรับสถานะรายจุดได้'),
    step('route', '#fsd-route-warnings', 'ตรวจเวลานัดและเวลาทำงาน', 'ระบบเตือนเมื่อไปไม่ทันช่วงนัด เวลานัดทับกัน หรือแผนเกินเวลาทำงาน เวลาเดินทางไม่คิดสภาพจราจรสด ควรเผื่อเวลาตามจริงเสมอ'),
    step('route', '#fsd-route-suggest', 'แนะนำลำดับ', 'ปุ่มแนะนำลำดับจะคำนวณลำดับใหม่โดยคงจุดที่ล็อกไว้ ช่างตรวจผลแล้วเลือกใช้เองก่อนเปลี่ยนแผน'),
    step('*', '#fsd-reset', 'ล้างข้อมูล Demo', 'ทดลองเปลี่ยนสถานะและจัดแผนได้เต็มที่ แล้วกดปุ่มนี้เพื่อกลับค่าเริ่มต้น จบการสาธิตครับ'),
  ];
  const viewOf = function (s) { return s.view.indexOf('job:') === 0 ? 'control' : s.view; };
  // One group of steps per allowed tab, in tab order; the closing "*" step ends the last group.
  const groups = api.views.map(function (v) { return { view: v, steps: ALL.filter(function (s) { return viewOf(s) === v; }) }; })
    .filter(function (g) { return g.steps.length; });
  if (groups.length) groups[groups.length - 1].steps = groups[groups.length - 1].steps.concat(ALL.filter(function (s) { return s.view === '*'; }));
  const steps = [].concat.apply([], groups.map(function (g) { return g.steps; }));   // every narrated step for this role
  el('bar').hidden = false;

  let onFinish = null;   // set by StaffDemo when continuing across menus
  let g = -1, index = -1, muted = false, paused = false, timer = null, watchdog = null, version = 0, audio = null, manifest = {};
  function stored(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  const manifestReady = (typeof fetch === 'function' ? fetch('/static/field-service-voice/manifest.json') : Promise.reject())
    .then(function (r) { return r.ok ? r.json() : {}; }).then(function (d) { manifest = d || {}; }).catch(function () { manifest = {}; });

  function note(text) { el('note').textContent = text; }
  function waitTime(text) { return Math.max(6000, Math.min(40000, text.length * 105)); }
  function cancel() {
    version++; clearTimeout(timer); clearTimeout(watchdog); timer = null; watchdog = null;
    if (audio) { audio.onended = null; audio.onerror = null; audio.pause(); audio = null; }
  }
  function schedule(ms) { clearTimeout(timer); timer = setTimeout(function () { if (index >= 0 && !paused && !document.hidden) advance(); }, ms); }
  function captions(text, why) { note(why + ' · แสดงคำบรรยายและเลื่อนต่ออัตโนมัติ'); schedule(waitTime(text)); }
  function setPaused(v) { paused = v; el('pause').textContent = v ? 'เล่นต่อ' : 'พักเล่น'; }
  function current() { return groups[g].steps[index]; }

  function play() {
    cancel(); if (index < 0 || paused) return;
    const token = version, text = current().text;
    if (muted) { captions(text, 'ปิดเสียงอยู่'); return; }
    manifestReady.then(function () {
      if (token !== version || paused || index < 0) return;
      const file = manifest[text];
      if (!file || !/^[a-f0-9]{16}\.mp3$/.test(file)) { captions(text, 'ยังไม่มีไฟล์เสียงต้นแบบสำหรับขั้นนี้'); return; }
      audio = new Audio('/static/field-service-voice/' + file);
      audio.preload = 'auto';
      audio.onended = function () { if (token === version) { clearTimeout(watchdog); schedule(800); } };
      audio.onerror = function () { if (token === version) { clearTimeout(watchdog); captions(text, 'เล่นไฟล์เสียงไม่ได้'); } };
      Promise.resolve(audio.play()).then(function () {
        if (token !== version) return;
        note('เสียงบรรยายภาษาไทย · เลื่อนต่อเมื่อพูดจบ');
        watchdog = setTimeout(function () { if (token === version) { cancel(); schedule(500); } }, 120000);
      }).catch(function () {
        if (token !== version) return;
        setPaused(true); cancel();
        note('เบราว์เซอร์ไม่อนุญาตให้เล่นเสียงอัตโนมัติ กด “เล่นต่อ” หรือเลือกปิดเสียงเพื่อดูคำบรรยาย');
      });
    });
  }
  function clearHighlight() { Array.prototype.forEach.call(document.querySelectorAll('.fsd-tour-target'), function (n) { n.classList.remove('fsd-tour-target'); }); }
  function show(groupIndex, i) {
    g = groupIndex; index = i; setPaused(false);
    const s = current(), total = groups[g].steps.length;
    clearHighlight();
    api.closeDialogs();
    api.show(groups[g].view);
    if (s.view.indexOf('job:') === 0) api.openJob(s.view.slice(4), { modal: false });
    el('panel').hidden = false;
    el('step').textContent = 'สาธิต ' + (i + 1) + ' / ' + total + (groups.length > 1 ? ' · ' + api.label(groups[g].view) : '');
    el('title').textContent = s.title;
    el('text').textContent = s.text;
    el('prev').disabled = g === 0 && i === 0;
    const lastHere = i === total - 1, more = el('all').checked && g < groups.length - 1;
    el('next').textContent = lastHere ? (more ? 'แท็บถัดไป →' : 'จบ Demo') : 'ถัดไป →';
    const target = document.querySelector(s.target);
    if (target) {
      target.classList.add('fsd-tour-target');
      const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (target.scrollIntoView) target.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    }
    play();
  }
  function stop(message, finished) {
    const cb = finished ? onFinish : null;
    onFinish = null;
    g = -1; index = -1; setPaused(false); cancel(); clearHighlight(); api.closeDialogs();
    if (cb) { cb(); return; }
    el('panel').hidden = true; note(message || 'กด “Demo แนะนำหน้านี้” เพื่อฟังคำแนะนำ พร้อมคำอธิบายบนจอ'); el('start').focus();
  }
  function advance() {
    if (index < 0) return;
    if (index < groups[g].steps.length - 1) { show(g, index + 1); return; }
    if (el('all').checked && g < groups.length - 1) { show(g + 1, 0); return; }
    stop(g === groups.length - 1 ? 'จบ Demo แล้ว กดเริ่มเพื่อดูอีกครั้ง' : 'จบการสาธิตแท็บนี้แล้ว', g === groups.length - 1);
  }
  function back() {
    if (index > 0) show(g, index - 1);
    else if (g > 0) show(g - 1, groups[g - 1].steps.length - 1);
  }
  function startHere() {
    const here = groups.findIndex(function (x) { return x.view === api.current(); });
    show(here >= 0 ? here : 0, 0);
  }
  function setMute(v) { muted = v; el('mute').checked = v; el('panel-mute').checked = v; store('fsd-tour-muted', v ? '1' : '0'); if (index >= 0 && !paused) play(); }

  el('start').addEventListener('click', startHere);
  el('restart').addEventListener('click', function () { show(0, 0); });
  el('pause').addEventListener('click', function () {
    if (index < 0) return;
    setPaused(!paused);
    if (paused) { cancel(); note('พักเล่นอยู่'); } else play();
  });
  el('next').addEventListener('click', advance);
  el('prev').addEventListener('click', back);
  el('close').addEventListener('click', function () { stop(); });
  ['mute', 'panel-mute'].forEach(function (id) { el(id).addEventListener('change', function () { setMute(el(id).checked); }); });
  el('all').checked = stored('fsd-tour-all') !== '0';
  el('all').addEventListener('change', function () { store('fsd-tour-all', el('all').checked ? '1' : '0'); if (index >= 0) el('next').textContent = index === groups[g].steps.length - 1 ? (el('all').checked && g < groups.length - 1 ? 'แท็บถัดไป →' : 'จบ Demo') : 'ถัดไป →'; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && index >= 0 && !document.querySelector('dialog[open]')) stop(); });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden && index >= 0 && !paused) { setPaused(true); cancel(); note('หยุดเพราะซ่อนแท็บ กดเล่นต่อเมื่อกลับมา'); }
  });
  window.addEventListener('pagehide', cancel);
  setMute(stored('fsd-tour-muted') === '1');
  window.FieldServiceTour = {
    steps: steps, groups: groups,
    // Used by the staff cross-menu Demo: play every tab, then call done() (not called if the user closes).
    startAll: function (done) { onFinish = done || null; el('all').checked = true; show(0, 0); },
  };
})();
