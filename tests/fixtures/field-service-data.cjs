/* Field-service Demo: FICTIONAL companies, people and machines only.
 * Nothing here comes from the ServicePro database. Phone numbers use a reserved-looking 02-000-xxxx
 * pattern and serials start with DEMO-. Customer coordinates are points on public roads near the service
 * centre chosen for the Demo — they are not the locations of any real company. Must match DEMO_POINTS in
 * field_service_google.py (checked by tests). */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FieldServiceData = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function addDays(iso, days) {
    const d = new Date(iso + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }

  const CHECKLISTS = {
    install: ['ตรวจพื้นที่ ไฟเลี้ยง และระบายอากาศ', 'ประกอบเครื่องและปรับระดับฐาน', 'ทดสอบพิมพ์ชิ้นงานตัวอย่าง', 'สอนการใช้งานเบื้องต้นให้ผู้ใช้'],
    inspection: ['ตรวจสภาพภายนอกและสายไฟ', 'ตรวจการเคลื่อนที่ของแกน', 'ตรวจอุณหภูมิหัวฉีดและฐานพิมพ์', 'สรุปข้อเสนอแนะให้ลูกค้า'],
    repair: ['ยืนยันอาการกับผู้ใช้', 'ตรวจหาสาเหตุ', 'แก้ไขหรือเปลี่ยนชิ้นส่วน', 'ทดสอบหลังซ่อม'],
    maintenance: ['ทำความสะอาดภายในเครื่อง', 'หล่อลื่นแกนและราง', 'ตรวจความตึงสายพาน', 'ปรับเทียบและพิมพ์ทดสอบ'],
  };
  const TOOLS = {
    install: ['ชุดไขควงและประแจหกเหลี่ยม', 'ระดับน้ำ', 'เส้นพลาสติกสำหรับทดสอบ'],
    inspection: ['มัลติมิเตอร์', 'เทอร์โมมิเตอร์อินฟราเรด', 'ไฟฉาย'],
    repair: ['ชุดเครื่องมือช่าง', 'หัวแร้ง', 'มัลติมิเตอร์'],
    maintenance: ['ผ้าไมโครไฟเบอร์', 'จาระบีสำหรับราง', 'แปรงทำความสะอาด'],
  };

  // Fictional customers are placed on public roads around the service centre (not real company sites).
  // x/y = km offsets from HQ (equirectangular), used by the simulated estimate and the offline SVG plan.
  function project(points) {
    const lat0 = points.HQ.lat, lng0 = points.HQ.lng, k = Math.cos(lat0 * Math.PI / 180);
    Object.keys(points).forEach(function (id) {
      const p = points[id];
      p.x = Math.round((p.lng - lng0) * 111.32 * k * 100) / 100;
      p.y = Math.round((p.lat - lat0) * 110.57 * 100) / 100;
    });
  }

  /** points (optional): {id:{lat,lng}} from the server config, e.g. a corrected HQ position. */
  function build(today, points) {
    const D = function (n) { return addDays(today, n); };
    const center = { id: 'HQ', name: 'ศูนย์บริการ (จุดเริ่มต้นโดยประมาณ)', lat: 13.8270, lng: 100.6680 };
    const techs = [
      { id: 'T1', name: 'ช่างอนันต์', skills: 'FDM ติดตั้ง/ซ่อม' },
      { id: 'T2', name: 'ช่างบุษบา', skills: 'Resin บำรุงรักษา' },
      { id: 'T3', name: 'ช่างชาตรี', skills: 'ตรวจเช็ก/ซ่อม' },
    ];
    const customers = {
      C1: { id: 'C1', name: 'บริษัท สมมติพลาสติก จำกัด', site: 'โรงงานบางสมมติ 1', address: 'นิคมอุตสาหกรรมจำลอง ซอย 3 (ที่อยู่สมมติ)', contact: 'คุณกานดา (ตัวละครสมมติ)', phone: '02-000-0101', lat: 13.853, lng: 100.713 },
      C2: { id: 'C2', name: 'บริษัท เดโมเมดิคอล จำกัด', site: 'อาคารผลิตอุปกรณ์การแพทย์จำลอง', address: 'ถนนตัวอย่าง 12 (ที่อยู่สมมติ)', contact: 'คุณธนา (ตัวละครสมมติ)', phone: '02-000-0102', lat: 13.846, lng: 100.604 },
      C3: { id: 'C3', name: 'บริษัท ตัวอย่างออโตพาร์ท จำกัด', site: 'โรงงานชิ้นส่วนยานยนต์จำลอง', address: 'นิคมทดลอง แปลง B7 (ที่อยู่สมมติ)', contact: 'คุณวิภา (ตัวละครสมมติ)', phone: '02-000-0103', lat: 13.799, lng: 100.751 },
      C4: { id: 'C4', name: 'หจก. ทดลองโมลด์', site: 'โรงงานแม่พิมพ์จำลอง', address: 'ซอยเดโม 5 (ที่อยู่สมมติ)', contact: 'คุณสมชาย (ตัวละครสมมติ)', phone: '02-000-0104', lat: 13.779, lng: 100.667 },
      C5: { id: 'C5', name: 'บริษัท จำลองเอดูเทค จำกัด', site: 'ศูนย์ฝึกอบรมจำลอง', address: 'อาคารสมมติ ชั้น 4 (ที่อยู่สมมติ)', contact: 'คุณพิมพ์ (ตัวละครสมมติ)', phone: '02-000-0105', lat: 13.896, lng: 100.656 },
    };
    // Factory floor layout for the customer view (C1). Machines are fictional.
    const factories = {
      C1: [
        { id: 'M1', model: 'Demo FDM X300', serial: 'DEMO-FDM-0001', zone: 'ไลน์ผลิต A', jobId: 'FS-1001' },
        { id: 'M2', model: 'Demo FDM X300', serial: 'DEMO-FDM-0002', zone: 'ไลน์ผลิต A', jobId: 'FS-1011' },
        { id: 'M3', model: 'Demo Resin R5', serial: 'DEMO-RSN-0003', zone: 'ห้องเรซิน', jobId: 'FS-1006' },
        { id: 'M4', model: 'Demo Wash W2', serial: 'DEMO-WSH-0004', zone: 'ห้องเรซิน', jobId: null },
      ],
    };

    function job(id, type, customerId, techId, date, window, serviceMin, status, machine, symptom, history, extra) {
      return Object.assign({
        id: id, type: type, customerId: customerId, techId: techId, date: date, window: window,
        serviceMin: serviceMin, status: status, machine: machine, symptom: symptom, history: history,
        checklist: CHECKLISTS[type], tools: TOOLS[type], parts: [], report: null, rescheduled: 0,
      }, extra || {});
    }
    function h(at, from, to, note, actor) { return { at: at, from: from, to: to, note: note || '', actor: actor || 'ผู้ประสานงานสมมติ' }; }
    const t0 = D(0), ym1 = D(-1), ym2 = D(-2);
    const assignedHistory = function (at) { return [h(at + ' 09:00', null, 'requested', 'รับคำขอทางโทรศัพท์ (สมมติ)'), h(at + ' 09:20', 'requested', 'awaiting_schedule'), h(at + ' 10:00', 'awaiting_schedule', 'assigned', 'ยืนยันนัดกับลูกค้าแล้ว')]; };

    const jobs = [
      job('FS-1001', 'install', 'C1', 'T1', t0, ['09:00', '10:00'], 120, 'assigned',
        { model: 'Demo FDM X300', serial: 'DEMO-FDM-0001' }, 'ติดตั้งเครื่องใหม่และสอนใช้งาน', assignedHistory(D(-3)),
        { parts: [{ name: 'หัวฉีด 0.4 มม. (สำรอง)', qty: 1 }] }),
      job('FS-1002', 'inspection', 'C3', 'T1', t0, ['11:30', '12:30'], 45, 'assigned',
        { model: 'Demo FDM X500', serial: 'DEMO-FDM-0105' }, 'ตรวจเช็กประจำไตรมาส', assignedHistory(D(-4))),
      job('FS-1003', 'maintenance', 'C2', 'T1', t0, ['13:00', '14:00'], 60, 'assigned',
        { model: 'Demo Resin R5', serial: 'DEMO-RSN-0201' }, 'บำรุงรักษาตามรอบ 500 ชั่วโมง', assignedHistory(D(-5)),
        { parts: [{ name: 'ฟิล์ม FEP (อะไหล่จำลอง)', qty: 1 }] }),
      job('FS-1004', 'repair', 'C4', 'T1', t0, ['15:30', '16:00'], 90, 'preparing',
        { model: 'Demo FDM X300', serial: 'DEMO-FDM-0310' }, 'แกน Z มีเสียงดังและชั้นงานเหลื่อม',
        assignedHistory(D(-2)).concat([h(D(-1) + ' 16:00', 'assigned', 'preparing', 'เตรียมสกรูแกน Z สำรอง')]),
        { parts: [{ name: 'สกรูแกน Z (อะไหล่จำลอง)', qty: 1 }, { name: 'ข้อต่อเพลา (อะไหล่จำลอง)', qty: 1 }] }),
      job('FS-1012', 'inspection', 'C5', 'T1', t0, ['10:30', '11:30'], 40, 'assigned',
        { model: 'Demo FDM Mini', serial: 'DEMO-FDM-0412' }, 'ตรวจเช็กก่อนเปิดคอร์สอบรม (ยังไม่ได้ใส่ในแผนเดินทาง)', assignedHistory(D(-1))),
      job('FS-1005', 'repair', 'C5', 'T2', t0, ['10:00', '11:00'], 90, 'in_service',
        { model: 'Demo Resin R5', serial: 'DEMO-RSN-0420' }, 'จอ LCD แสดงภาพไม่ครบ',
        assignedHistory(D(-2)).concat([h(t0 + ' 08:00', 'assigned', 'preparing'), h(t0 + ' 09:15', 'preparing', 'traveling'), h(t0 + ' 10:05', 'traveling', 'in_service', '', 'ช่างบุษบา')])),
      job('FS-1006', 'maintenance', 'C1', 'T2', t0, ['14:00', '15:00'], 60, 'waiting_parts',
        { model: 'Demo Resin R5', serial: 'DEMO-RSN-0003' }, 'บำรุงรักษาและเปลี่ยนถาดเรซิน',
        assignedHistory(D(-6)).concat([h(D(-1) + ' 11:00', 'assigned', 'preparing'), h(D(-1) + ' 15:00', 'preparing', 'waiting_parts', 'ถาดเรซินรุ่นนี้หมด รอของเข้าคลัง (สมมติ)')]),
        { parts: [{ name: 'ถาดเรซิน (อะไหล่จำลอง)', qty: 1 }] }),
      job('FS-1007', 'install', 'C2', null, D(2), ['09:00', '12:00'], 150, 'awaiting_schedule',
        { model: 'Demo FDM X500', serial: 'DEMO-FDM-0520' }, 'ติดตั้งเครื่องเพิ่ม 1 เครื่อง',
        [h(D(-1) + ' 13:00', null, 'requested', 'ลูกค้าส่งคำขอทางอีเมล (สมมติ)'), h(D(-1) + ' 13:30', 'requested', 'awaiting_schedule')]),
      job('FS-1008', 'inspection', 'C5', null, null, null, 45, 'requested',
        { model: 'Demo FDM Mini', serial: 'DEMO-FDM-0413' }, 'เครื่องพิมพ์ช้าลงผิดปกติ',
        [h(t0 + ' 08:40', null, 'requested', 'ลูกค้าแจ้งผ่านโทรศัพท์ (สมมติ)')]),
      job('FS-1010', 'maintenance', 'C4', 'T3', t0, ['09:30', '10:30'], 60, 'traveling',
        { model: 'Demo FDM X300', serial: 'DEMO-FDM-0311' }, 'บำรุงรักษาตามรอบ',
        assignedHistory(D(-3)).concat([h(t0 + ' 08:10', 'assigned', 'preparing'), h(t0 + ' 08:55', 'preparing', 'traveling', '', 'ช่างชาตรี')])),
      job('FS-1009', 'repair', 'C3', 'T3', ym1, ['13:00', '14:00'], 75, 'completed',
        { model: 'Demo FDM X500', serial: 'DEMO-FDM-0106' }, 'หัวฉีดอุดตัน',
        assignedHistory(D(-4)).concat([h(ym1 + ' 12:00', 'assigned', 'preparing'), h(ym1 + ' 12:20', 'preparing', 'traveling'), h(ym1 + ' 13:05', 'traveling', 'in_service'), h(ym1 + ' 14:10', 'in_service', 'awaiting_acceptance'), h(ym1 + ' 14:25', 'awaiting_acceptance', 'completed', 'ลูกค้าลงชื่อรับงาน (สมมติ)')]),
        { report: 'ล้างหัวฉีดและเปลี่ยนท่อ PTFE ทดสอบพิมพ์ผ่าน 2 ชิ้น แนะนำให้ทำความสะอาดทุก 200 ชั่วโมง (รายงานจำลอง)' }),
      job('FS-1011', 'inspection', 'C1', 'T3', ym2, ['10:00', '11:00'], 45, 'completed',
        { model: 'Demo FDM X300', serial: 'DEMO-FDM-0002' }, 'ตรวจเช็กประจำเดือน',
        assignedHistory(D(-6)).concat([h(ym2 + ' 09:00', 'assigned', 'preparing'), h(ym2 + ' 09:30', 'preparing', 'traveling'), h(ym2 + ' 10:02', 'traveling', 'in_service'), h(ym2 + ' 10:50', 'in_service', 'awaiting_acceptance'), h(ym2 + ' 11:00', 'awaiting_acceptance', 'completed', 'ผ่านการตรวจรับ (สมมติ)')]),
        { report: 'เครื่องทำงานปกติ ความตึงสายพานอยู่ในเกณฑ์ แนะนำเปลี่ยนแผ่นฐานพิมพ์ในรอบหน้า (รายงานจำลอง)' }),
    ];

    // Initial route for ช่างอนันต์ today: order deliberately NOT by time so the Demo can show a late warning.
    const route = {
      techId: 'T1', date: t0, departAt: '08:30', workEnd: '17:30', end: 'return',
      order: ['FS-1001', 'FS-1003', 'FS-1002', 'FS-1004'], locked: {}, stopStatus: {},
    };
    const all = { HQ: center };
    Object.keys(customers).forEach(function (k) { all[k] = customers[k]; });
    Object.keys(points || {}).forEach(function (k) { if (all[k] && points[k]) { all[k].lat = Number(points[k].lat); all[k].lng = Number(points[k].lng); } });
    project(all);
    return { today: t0, center: center, techs: techs, customers: customers, factories: factories, jobs: jobs, route: route };
  }

  return { build: build, addDays: addDays, CHECKLISTS: CHECKLISTS };
});
