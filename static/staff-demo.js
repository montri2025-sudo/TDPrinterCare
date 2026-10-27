/* Staff guided Demo across every staff menu except the guide (คู่มือใช้งาน). Same look and controls as
 * the customer Virtual Office Demo: "Demo แนะนำหน้านี้", mute, "เล่นต่อทุกเมนู", pause/back/next/close.
 * Read-only: it highlights and explains; it never submits forms, clicks buttons or changes records.
 * Menu order is taken from the sidebar links the signed-in role actually has.
 * Narration MP3s (if generated) come from /static/staff-demo-voice/manifest.json; otherwise timed
 * Thai captions (no substitute voice). tools/make-field-service-voice.py also reads the step(...) lines here. */
(function () {
  'use strict';
  const el = function (id) { return document.getElementById('staff-demo-' + id); };
  const path = location.pathname;
  if (!el('bar') || /^\/guide(?:\/|$)/.test(path)) return;
  const step = function (target, title, text) { return { target: target, title: title, text: text }; };
  const dashboard = [
    step('#command-title, .main-area h1', 'ห้องมอนิเตอร์', 'หน้าแรกของงานบริการ สรุปงานซ่อม การชำระเงิน อะไหล่ และภาระงานช่างในจอเดียว'),
    step('#dashFilterForm', 'เลือกช่วงวันที่', 'เลือกช่วงวันที่เพื่อดูตัวเลขและกราฟเฉพาะช่วงที่ต้องการ'),
    step('#dashTrendChart, #dashTicketsTrendChart', 'แนวโน้มและงานเร่งด่วน', 'กราฟแสดงงานเข้าเทียบงานปิด ด้านล่างมีคิวนัดวันนี้ งานเร่งด่วน การชำระเงินที่รอตรวจ และอะไหล่ใกล้หมด คลิกรายการเพื่อดูรายละเอียด'),
  ];
  const PAGES = {
    '/staff/warehouse': [
      step('#stock-room-title, .main-area h1', 'ห้องมอนิเตอร์คลังสินค้า', 'จอนี้สรุปจำนวนรายการสินค้า จำนวนคงเหลือ และยอดขาย เหมาะเปิดไว้บนจอในร้าน'),
      step('#warehouse-screen-rows, .main-area table', 'รายการสินค้าและจำนวน', 'ตารางแสดงสินค้าแต่ละรายการพร้อมจำนวนคงเหลือ ใช้ช่องค้นหาเพื่อหาสินค้าที่ต้องการ'),
    ],
    '/admin/dashboard': dashboard,
    '/manager/dashboard': dashboard,
    '/admin/board': [
      step('#office-title, .main-area h1', 'Virtual Office', 'แผนผังร้านแสดงงานซ่อมทุกงานตามห้องและขั้นตอน ตั้งแต่รับงาน ตรวจวิเคราะห์ รออะไหล่ ซ่อม ทดสอบ จนพร้อมส่งมอบ'),
      step('#office-search', 'ค้นหาและกรองงาน', 'ค้นหาด้วยเลขงานหรือชื่อลูกค้า และกรองตามสาขา ช่าง หรือเครื่อง'),
      step('#office-scene, #office-floor', 'ติดตามงานตามห้อง', 'คลิกห้องหรือการ์ดงานเพื่ออ่านรายละเอียดและประวัติ การเปลี่ยนสถานะต้องกดยืนยันเองทุกครั้ง'),
      step('#office-front-summary, #office-dispatch-list', 'หน้าร้านและการส่งมอบ', 'ด้านข้างสรุปคิวหน้าร้านและงานที่รอส่งมอบ ช่วยให้รู้ว่าลูกค้ารายไหนกำลังรอเครื่อง'),
    ],
    '/admin/ticket/new': [
      step('.main-area h1', 'แจ้งซ่อมแทนลูกค้า', 'ใช้เปิดงานซ่อมเมื่อลูกค้าแจ้งทางโทรศัพท์หรือที่หน้าร้าน'),
      step('#customer_display', 'เลือกลูกค้าและเครื่อง', 'ค้นหาลูกค้า แล้วเลือกเครื่องที่ต้องการซ่อม เครื่องที่มีงานค้างจะเลือกซ้ำไม่ได้'),
      step('.main-area form', 'กรอกอาการและนัดหมาย', 'ระบุประเภทปัญหา อาการ และวันนัดถ้ามี ตรวจข้อมูลให้ครบแล้วกดบันทึกเอง  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/admin/customers': [
      step('.main-area h1', 'ลูกค้าและเครื่องพิมพ์', 'หน้านี้รวมข้อมูลลูกค้าและเครื่องพิมพ์ที่ลงทะเบียนในระบบ'),
      step('#customers-table', 'รายชื่อลูกค้า', 'ค้นหาและแก้ไขข้อมูลลูกค้า ข้อมูลติดต่อเป็นข้อมูลส่วนบุคคล ใช้เท่าที่จำเป็น'),
      step('#devices-table', 'เครื่องพิมพ์ทั้งหมด', 'ดูเครื่องของลูกค้าแต่ละราย สถานะประกัน และประวัติ ลงทะเบียนเครื่องใหม่ได้จากแบบฟอร์มด้านบน  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/admin/inventory': [
      step('#warehouse-racks, .main-area h1', 'Virtual Warehouse', 'ชั้นวางเสมือนแสดงสินค้าและอะไหล่ตามตำแหน่ง สีบอกระดับคงเหลือ คลิกสินค้าเพื่อดูรายละเอียด'),
      step('#warehouse-order-list', 'แผนสั่งเพิ่ม', 'รายการนี้แนะนำสินค้าที่ควรสั่งเพิ่มจากยอดขายและจุดสั่งซื้อ ใช้ประกอบการตัดสินใจเท่านั้น'),
      step('#inventory-table', 'ตารางสินค้า', 'ตารางแสดงรหัส ราคา จำนวน และตำแหน่งจัดเก็บ การรับเข้าและปรับสต็อกต้องทำผ่านปุ่มของแต่ละรายการ  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/sales/orders': [
      step('.main-area h1', 'รายการขายสินค้า', 'หน้านี้สรุปการขายสินค้าและอะไหล่ของสาขา'),
      step('#categoryDoughnutChart, #monthlySalesChart', 'ยอดขายแยกประเภทและรายเดือน', 'กราฟแสดงสัดส่วนยอดขายตามประเภทสินค้า และแนวโน้มรายเดือน'),
      step('.main-area table', 'รายการขายทั้งหมด', 'คลิกบิลเพื่อดูรายละเอียด พิมพ์ใบเสนอราคา ใบเสร็จ หรือใบกำกับภาษีตามสถานะของบิล'),
    ],
    '/sales/new': [
      step('.main-area h1', 'บันทึกการขาย', 'ใช้บันทึกการขายสินค้าหน้าร้าน'),
      step('#customer_display', 'เลือกลูกค้า', 'ค้นหาลูกค้าเพื่อออกเอกสารในนามลูกค้า หรือขายแบบไม่ระบุลูกค้าตามที่ระบบรองรับ'),
      step('#linesTable', 'รายการสินค้า', 'เพิ่มสินค้า ตรวจจำนวนคงเหลือ จำนวน และราคา ระบบรวมยอดให้อัตโนมัติ ตรวจให้ถูกต้องก่อนบันทึก  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/admin/restock-orders': [
      step('.main-area h1', 'คำสั่งซื้อจากศูนย์บริการ', 'สำนักงานใหญ่ใช้หน้านี้รับคำสั่งซื้อสินค้าและอะไหล่จากศูนย์บริการ'),
      step('#restock-orders-table, .main-area table, .main-area .card', 'สถานะคำสั่งซื้อ', 'ตารางแสดงคำสั่งซื้อและสถานะ ตั้งแต่ขอซื้อ เตรียมของ จัดส่ง จนรับของ เลื่อนตารางด้วยแถบเลื่อนด้านล่าง'),
      step('#restock-scroll-dock, .main-area table, .main-area .card', 'ดำเนินการทีละขั้น', 'การยืนยันจัดส่งหรือยกเลิกต้องตรวจรายการแล้วกดเองทุกครั้ง  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/manager/restock-orders': [
      step('.main-area h1', 'สั่งซื้อสินค้าจากสำนักงานใหญ่', 'ผู้จัดการสาขาใช้หน้านี้สั่งสินค้าและอะไหล่จากสำนักงานใหญ่'),
      step('#restockForm', 'สร้างคำสั่งซื้อ', 'เลือกสินค้า ตรวจจำนวนคงเหลือ แล้วใส่จำนวนที่ต้องการ  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
      step('.main-area table + h2, .main-area table', 'ติดตามคำสั่งซื้อของศูนย์', 'ดูสถานะคำสั่งซื้อของศูนย์ และยืนยันรับของเมื่อสินค้ามาถึงจริง'),
    ],
    '/admin/settlements': [
      step('.main-area h1', 'รายงานยอดขายฝากขาย', 'ตรวจรายงานยอดขายและการชำระเงินสินค้าฝากขายที่ศูนย์บริการส่งเข้ามา'),
      step('.main-area table, .main-area .card', 'ตรวจสอบกระทบยอด', 'เปิดรายงานแต่ละเดือนเพื่อตรวจกระทบยอดก่อนยืนยัน  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/manager/settlements': [
      step('.main-area h1', 'รายงานยอดขายฝากขาย', 'ศูนย์บริการสรุปยอดขายสินค้าฝากขายและการชำระเงินให้สำนักงานใหญ่เป็นรายเดือน'),
      step('.main-area form', 'รายงานเดือนปัจจุบัน', 'ตรวจยอดเดือนปัจจุบัน แล้วส่งรายงานเมื่อข้อมูลครบ  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
      step('.main-area table, .main-area .card', 'ประวัติรายงาน', 'ดูรายงานเดือนก่อนหน้าและสถานะการกระทบยอด'),
    ],
    '/manager/approvals': [
      step('.main-area h1', 'อนุมัติเบิกอะไหล่ราคาสูง', 'อะไหล่ที่ราคาเกินเกณฑ์ต้องให้ผู้จัดการอนุมัติก่อนตัดสต็อก'),
      step('.main-area table, .main-area .card', 'ตรวจก่อนอนุมัติ', 'ตรวจงานซ่อม อะไหล่ จำนวน และราคา แล้วเลือกอนุมัติหรือไม่อนุมัติเอง  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/manager/csat': [
      step('.main-area h1', 'ความพึงพอใจลูกค้า', 'หน้านี้รวมคะแนนและความเห็นที่ลูกค้าให้หลังปิดงานซ่อม'),
      step('.main-area table', 'อ่านความเห็น', 'ใช้คะแนนและความเห็นเพื่อติดตามคุณภาพบริการของสาขา'),
    ],
    '/admin/maintenance-plans': [
      step('.main-area h1', 'แผนบำรุงรักษา', 'กำหนดงานดูแลเครื่องตามรอบวันหรือชั่วโมงใช้งาน แยกตามประเภทเครื่อง'),
      step('.main-area form', 'เพิ่มแผนใหม่', 'ระบุชื่องาน ประเภทเครื่อง และรอบการดูแล  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
      step('.main-area table', 'แผนทั้งหมด', 'ตรวจ แก้ไข หรือปิดใช้งานแผนเดิม ระบบใช้แผนเหล่านี้แจ้งเตือนลูกค้าเมื่อถึงรอบ'),
    ],
    '/admin/checklist-items': [
      step('.main-area h1', 'Checklist ก่อนพิมพ์', 'รายการตรวจสอบที่ลูกค้าและช่างใช้ก่อนเริ่มพิมพ์งาน'),
      step('.main-area form', 'เพิ่มรายการตรวจสอบ', 'เพิ่มรายการใหม่ตามประเภทเครื่อง  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
      step('.main-area table', 'รายการทั้งหมด', 'จัดลำดับ แก้ไข หรือปิดใช้งานรายการตรวจสอบ'),
    ],
    '/admin/users': [
      step('.main-area h1', 'ผู้ใช้งาน', 'จัดการบัญชีพนักงานและสิทธิ์การใช้งานตามบทบาทและสาขา'),
      step('.main-area form', 'สร้างบัญชีใหม่', 'กำหนดบทบาทและสาขาให้ตรงกับหน้าที่จริง ตั้งรหัสผ่านที่ปลอดภัย  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
      step('.main-area table', 'รายชื่อผู้ใช้', 'ตรวจบทบาท สาขา และสถานะ ระงับบัญชีที่ไม่ใช้แล้วแทนการลบ'),
    ],
    '/admin/centers': [
      step('.main-area h1', 'ศูนย์บริการ', 'ข้อมูลสาขา ที่อยู่ พิกัด และประเภทงานที่รับ รวมถึงบัญชีรับชำระของสำนักงานใหญ่'),
      step('.main-area form', 'เพิ่มหรือแก้ไขสาขา', 'ตรวจข้อมูลสาขาให้ถูกต้อง เพราะใช้แสดงบนหน้าแรกและในเอกสาร  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/admin/activities': [
      step('.main-area h1', 'ShareSpace', 'พื้นที่แบ่งปันกิจกรรมและไฟล์ให้ทีมและลูกค้า'),
      step('#activityFilterForm', 'ค้นหากิจกรรม', 'กรองกิจกรรมตามคำค้นหรือสถานะ'),
      step('#activitiesList, .main-area .card', 'จัดการกิจกรรม', 'สร้าง แก้ไข เผยแพร่ หรือซ่อนกิจกรรม ตรวจไฟล์ก่อนเผยแพร่ทุกครั้ง  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/sharespace': [
      step('.main-area h1', 'ShareSpace', 'ดูกิจกรรมและไฟล์ที่ทีมแบ่งปัน เปิดรายการเพื่ออ่านหรือดาวน์โหลด'),
    ],
    '/admin/odoo-sync': [
      step('.main-area h1', 'ซิงก์ข้อมูลไป Odoo', 'หน้านี้แสดงผลการซิงก์ลูกค้า สินค้า และผู้ใช้ไปยัง Odoo'),
      step('.main-area table', 'ตรวจผลการซิงก์', 'ตรวจรายการที่สำเร็จและไม่สำเร็จ ปุ่มซิงก์จะส่งข้อมูลไป Odoo จริง ให้กดเมื่อผู้ดูแลระบบอนุมัติเท่านั้น Demo จะไม่กดแทน'),
    ],
    '/admin/reports': [
      step('.main-area h1', 'รายงาน', 'รวมรายงานการซ่อม ช่าง อะไหล่ ยอดขาย และใบแจ้งหนี้'),
      step('#reportCenterDisplay, .main-area form', 'เลือกสาขาและช่วงวันที่', 'เลือกสาขาและช่วงวันที่ก่อนอ่านรายงาน'),
      step('#ticketReportTable, .main-area table', 'อ่านรายงาน', 'คลิกตัวเลขเพื่อดูรายละเอียด ส่วนรายงานใบแจ้งหนี้ใช้ติ๊กว่าลงบัญชีแล้ว  Demo ไม่กดบันทึกหรือส่งแบบฟอร์มแทนคุณ'),
    ],
    '/admin/commission-report': [
      step('.main-area h1', 'ค่าคอมมิชชั่นช่าง', 'สรุปค่าคอมมิชชั่นพิเศษของช่างและหัวหน้าช่างตามงวด'),
      step('.main-area table', 'ตรวจรายละเอียด', 'ตรวจจำนวนเคสและค่าแรงก่อนจ่าย และพิมพ์ใบสรุปได้จากหน้านี้'),
    ],
    '/tech/tasks': [
      step('.main-area h1', 'งานของฉัน', 'ช่างเห็นงานซ่อมที่ได้รับมอบหมาย เรียงตามสถานะ'),
      step('.main-area table', 'เปิดงานเพื่อทำต่อ', 'คลิกงานเพื่ออ่านอาการ บันทึกผลซ่อม เบิกอะไหล่ และเปลี่ยนสถานะ ทุกขั้นต้องกดยืนยันเอง'),
    ],
    '/tech/report': [
      step('.main-area h1', 'รายงานของฉัน', 'สรุปงานที่ทำในช่วงที่เลือก แยกตามสถานะ'),
      step('.main-area table', 'คอมมิชชั่นและอะไหล่', 'ดูค่าคอมมิชชั่นงวดปัจจุบัน อะไหล่ที่เบิกใช้ และรายการงานทั้งหมด'),
    ],
    '/track': [
      step('.main-area form', 'เช็กสถานะงานซ่อม', 'กรอกข้อมูลค้นหาตามช่องที่แสดง เพื่อดูสถานะงานซ่อมเหมือนที่ลูกค้าเห็น'),
      step('.main-area', 'อ่านผลการค้นหา', 'ตรวจข้อมูลเครื่องและสถานะที่ระบบแสดง ถ้าไม่พบงานให้ตรวจข้อมูลค้นหาอีกครั้ง'),
    ],
  };

  PAGES['/field-service'] = [
    step('#field-service-live h1', 'บริการนอกสถานที่', 'หน้านี้แสดงใบงานจริงตามสิทธิ์และสาขาของคุณ คู่มือแนะนำจะไม่บันทึกหรือเปลี่ยนสถานะงานแทนคุณ'),
    step('.fsl .fsd-summary, .fsl .fsd-card', 'คิวนัดหมายและสถานะ', 'ตรวจวันนัด ลูกค้า เครื่อง และช่าง เปิดใบงานเพื่อบันทึกรายงานและทำงานตามขั้นตอน'),
    step('.fsl .fsd-head nav', 'สร้างใบงานและวางแผน', 'ผู้ประสานงานสร้างใบงานและมอบหมายช่างได้ เลือกแผนการเดินทางเพื่อเรียงจุดแวะ และกดบันทึกด้วยตนเองเมื่อพร้อม'),
  ];

  // Sidebar order for this role, without the guide; only menus that have a tour (or the field-service tab tour).
  const menu = Array.prototype.map.call(document.querySelectorAll('.sidebar nav a'), function (a) { return a.getAttribute('href'); })
    .filter(function (href, i, all) { return href && all.indexOf(href) === i && !/^\/guide/.test(href) && (PAGES[href] || href === '/field-service'); });
  function stored(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  function nextMenu() { const i = menu.indexOf(path); return i >= 0 && i < menu.length - 1 ? menu[i + 1] : null; }
  function goNext() { const next = nextMenu(); if (!next) return false; store('staff-demo-resume', next); location.assign(next); return true; }

  // The isolated example page retains its own tab tour. Operational pages use read-only instructions.
  if (path === '/field-service/demo') {
    el('bar').hidden = true;
    if (stored('staff-demo-resume') === path) {
      store('staff-demo-resume', '');
      const tryStart = function (n) {
        const t = window.FieldServiceTour;
        if (t && t.startAll) t.startAll(function () { goNext(); });
        else if (n < 40) setTimeout(function () { tryStart(n + 1); }, 50);
      };
      tryStart(0);
    }
    window.StaffDemo = { menu: menu, pages: PAGES };
    return;
  }
  const steps = PAGES[path] || [];
  window.StaffDemo = { menu: menu, pages: PAGES };
  if (!steps.length) return;
  el('bar').hidden = false;

  let index = -1, muted = false, paused = false, timer = null, watchdog = null, version = 0, audio = null, manifest = {};
  const manifestReady = (typeof fetch === 'function' ? fetch('/static/staff-demo-voice/manifest.json') : Promise.reject())
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
  function play() {
    cancel(); if (index < 0 || paused) return;
    const token = version, text = steps[index].text;
    if (muted) { captions(text, 'ปิดเสียงอยู่'); return; }
    manifestReady.then(function () {
      if (token !== version || paused || index < 0) return;
      const file = manifest[text];
      if (!file || !/^[a-f0-9]{16}\.mp3$/.test(file)) { captions(text, 'ยังไม่มีไฟล์เสียงต้นแบบสำหรับขั้นนี้'); return; }
      audio = new Audio('/static/staff-demo-voice/' + file);
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
  function clearHighlight() { Array.prototype.forEach.call(document.querySelectorAll('.staff-demo-target'), function (n) { n.classList.remove('staff-demo-target'); }); }
  function visibleTarget(selector) {
    const list = Array.prototype.slice.call(document.querySelectorAll(selector));
    return list.find(function (n) { return !n.getClientRects || n.getClientRects().length; }) || document.querySelector('.main-area h1') || el('bar');
  }
  function show(i) {
    index = i; setPaused(false);
    const s = steps[i];
    clearHighlight();
    el('panel').hidden = false;
    el('step').textContent = 'สาธิต ' + (i + 1) + ' / ' + steps.length;
    el('title').textContent = s.title;
    el('text').textContent = s.text;
    el('prev').disabled = i === 0;
    el('next').textContent = i === steps.length - 1 ? (el('all').checked && nextMenu() ? 'เมนูถัดไป →' : 'จบหน้านี้') : 'ถัดไป →';
    const target = visibleTarget(s.target);
    target.classList.add('staff-demo-target');
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (target.scrollIntoView) target.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    play();
  }
  function stop(message) {
    index = -1; setPaused(false); cancel(); clearHighlight();
    el('panel').hidden = true; store('staff-demo-resume', '');
    note(message || 'กด “Demo แนะนำหน้านี้” เพื่อฟังคำแนะนำ พร้อมคำอธิบายบนจอ'); el('start').focus();
  }
  function advance() {
    if (index < 0) return;
    if (index < steps.length - 1) { show(index + 1); return; }
    if (el('all').checked) { cancel(); if (goNext()) return; }
    stop(nextMenu() ? 'จบการสาธิตหน้านี้แล้ว' : 'จบ Demo ทุกเมนูแล้ว กด Demo เพื่อเล่นอีกครั้ง');
  }
  function setMute(v) { muted = v; el('mute').checked = v; el('panel-mute').checked = v; store('staff-demo-muted', v ? '1' : '0'); if (index >= 0 && !paused) play(); }

  el('start').addEventListener('click', function () { show(0); });
  el('pause').addEventListener('click', function () {
    if (index < 0) return;
    setPaused(!paused);
    if (paused) { cancel(); note('พักเล่นอยู่'); } else play();
  });
  el('next').addEventListener('click', advance);
  el('prev').addEventListener('click', function () { if (index > 0) show(index - 1); });
  el('close').addEventListener('click', function () { stop(); });
  ['mute', 'panel-mute'].forEach(function (id) { el(id).addEventListener('change', function () { setMute(el(id).checked); }); });
  el('all').checked = stored('staff-demo-all') !== '0';
  el('all').addEventListener('change', function () { store('staff-demo-all', el('all').checked ? '1' : '0'); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && index >= 0 && !document.querySelector('dialog[open]')) stop(); });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden && index >= 0 && !paused) { setPaused(true); cancel(); note('หยุดเพราะซ่อนแท็บ กดเล่นต่อเมื่อกลับมา'); }
  });
  window.addEventListener('pagehide', cancel);
  setMute(stored('staff-demo-muted') === '1');
  if (stored('staff-demo-resume') === path) { store('staff-demo-resume', ''); show(0); }
})();
