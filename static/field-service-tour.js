/* Guided Thai tour for the field-service Demo. Navigates views and opens one fictional job;
 * it never changes Demo state. Narration MP3s (if generated) come from /static/field-service-voice/
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
  const steps = ALL.filter(function (s) {
    const view = s.view.indexOf('job:') === 0 ? 'control' : s.view;
    return view === '*' || api.views.indexOf(view) >= 0;
  });
  el('bar').hidden = false;

  let index = -1, muted = false, paused = false, timer = null, watchdog = null, version = 0, audio = null, manifest = {};
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

  function play() {
    cancel(); if (index < 0 || paused) return;
    const token = version, text = steps[index].text;
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
        paused = true; cancel(); el('pause').textContent = '▶ เล่นต่อ';
        note('เบราว์เซอร์ไม่อนุญาตให้เล่นเสียงอัตโนมัติ กด “เล่นต่อ” หรือเลือกปิดเสียงเพื่อดูคำบรรยาย');
      });
    });
  }
  function clearHighlight() { Array.prototype.forEach.call(document.querySelectorAll('.fsd-tour-target'), function (n) { n.classList.remove('fsd-tour-target'); }); }
  function show(i) {
    index = i; paused = false; el('pause').textContent = '⏸ หยุดชั่วคราว';
    const s = steps[i];
    clearHighlight();
    if (s.view.indexOf('job:') === 0) { api.closeDialogs(); api.show('control'); api.openJob(s.view.slice(4), { modal: false }); }
    else { api.closeDialogs(); if (s.view !== '*') api.show(s.view); }
    el('panel').hidden = false;
    el('step').textContent = 'ขั้นที่ ' + (i + 1) + ' / ' + steps.length;
    el('title').textContent = s.title;
    el('text').textContent = s.text;
    el('prev').disabled = i === 0;
    el('next').textContent = i === steps.length - 1 ? 'จบ Demo' : 'ถัดไป →';
    const target = document.querySelector(s.target);
    if (target) {
      target.classList.add('fsd-tour-target');
      const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (target.scrollIntoView) target.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    }
    play();
  }
  function stop(message) {
    index = -1; paused = false; cancel(); clearHighlight(); api.closeDialogs();
    el('panel').hidden = true; note(message || 'กด “เริ่ม Demo” เพื่อฟังคำแนะนำทีละขั้น'); el('start').focus();
  }
  function advance() { if (index < 0) return; if (index < steps.length - 1) show(index + 1); else stop('จบ Demo แล้ว กดเริ่มเพื่อดูอีกครั้ง'); }
  function setMute(v) { muted = v; el('mute').checked = v; store('fsd-tour-muted', v ? '1' : '0'); if (index >= 0 && !paused) play(); }

  el('start').addEventListener('click', function () { show(0); });
  el('restart').addEventListener('click', function () { show(0); });
  el('pause').addEventListener('click', function () {
    if (index < 0) return;
    paused = !paused; el('pause').textContent = paused ? '▶ เล่นต่อ' : '⏸ หยุดชั่วคราว';
    if (paused) { cancel(); note('หยุดชั่วคราว'); } else play();
  });
  el('next').addEventListener('click', advance);
  el('prev').addEventListener('click', function () { if (index > 0) show(index - 1); });
  el('close').addEventListener('click', function () { stop(); });
  el('mute').addEventListener('change', function () { setMute(el('mute').checked); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && index >= 0 && !document.querySelector('dialog[open]')) stop(); });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden && index >= 0 && !paused) { paused = true; cancel(); el('pause').textContent = '▶ เล่นต่อ'; note('หยุดเพราะซ่อนแท็บ กดเล่นต่อเมื่อกลับมา'); }
  });
  window.addEventListener('pagehide', cancel);
  setMute(stored('fsd-tour-muted') === '1');
  window.FieldServiceTour = { steps: steps };
})();
