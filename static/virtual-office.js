/* Virtual Office: server-authorized updates, text-only rendering of ticket data. */
(function () {
  'use strict';
  const source = document.getElementById('office-data');
  if (!source) return;
  const data = JSON.parse(source.textContent);
  const byId = new Map(data.tickets.map(ticket => [String(ticket.ticket_id), ticket]));
  const el = id => document.getElementById(id);
  const dialog = el('office-dialog');
  const form = el('office-update-form');
  const readOnly = data.readOnly === true;
  let selected = null;
  let stage = '';
  let openingButton = null;
  let submitting = false;
  const value = input => input == null || input === '' ? '—' : String(input);
  const text = (id, content) => { el(id).textContent = value(content); };
  function option(select, label, id) {
    const item = document.createElement('option');
    item.value = id;
    item.textContent = label;
    select.appendChild(item);
  }
  const centers = new Map();
  const technicians = new Map();
  data.tickets.forEach(ticket => {
    centers.set(ticket.center_id == null ? 'central' : String(ticket.center_id), ticket.center_name || 'ส่วนกลาง');
    if (ticket.assigned_tech_id != null) technicians.set(String(ticket.assigned_tech_id), ticket.tech_name || 'ช่าง #' + ticket.assigned_tech_id);
  });
  centers.forEach((name, id) => option(el('office-center'), name, id));
  technicians.forEach((name, id) => option(el('office-tech'), name, id));

  // Both renderers consume the same authorized snapshot. All writes stay in the existing dialog.
  let sceneZoom = 1, sceneMode = '3d', scene3D = null, scene3DLoading = false, latestScene = null;
  let sceneMotionPaused = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const openSceneTicket = (ticket, trigger) => {
    const desk = document.querySelector('.office-desk[data-ticket-id="'+ticket.ticket_id+'"]');
    if (desk) openTicket(desk, trigger);
  };
  function setSceneMode(mode, message) {
    sceneMode = mode;
    const active3D = mode === '3d' && !!scene3D;
    if (el('office-3d')) el('office-3d').hidden = !active3D;
    el('office-scene').toggleAttribute('hidden', active3D);
    if (scene3D) scene3D.setVisible(active3D && !document.hidden && !dialog.open);
    ['3d','2d'].forEach(v => { if(el('office-mode-'+v)) el('office-mode-'+v).setAttribute('aria-pressed', String(v===mode)); });
    if (el('office-render-note')) el('office-render-note').textContent = message || (active3D ? 'ลากเพื่อหมุนห้อง · ใช้ปุ่มลูกศรเมื่อโฟกัสฉาก' : mode==='3d' ? 'กำลังเตรียมสำนักงาน 3D · แสดงภาพเดิมระหว่างรอ' : 'โหมดภาพสำนักงาน · คลิกป้ายเลขงานเพื่อดูรายละเอียด');
  }
  function drawOfficeScene(tickets) {
    const svg = el('office-scene');
    if (!svg || !window.ServiceOfficeScene) return;
    latestScene = {tickets, statuses:data.statuses, labels:data.labels, stage, zoom:sceneZoom, readOnly};
    if (sceneMode === '2d' || !scene3D) window.ServiceOfficeScene.render(svg, {...latestScene, onStage:chooseStage, onTicket:openSceneTicket});
    if (sceneMode !== '3d' || !el('office-3d')) return;
    if (scene3D) { scene3D.update(latestScene); setSceneMode('3d'); return; }
    if (scene3DLoading) return;
    scene3DLoading = true;
    import(el('office-3d').dataset.module).then(module => {
      if (sceneMode !== '3d') return;
      scene3D = module.createOffice3D(el('office-3d'), {
        onStage:chooseStage, onTicket:openSceneTicket,
        onUnavailable:() => { setSceneMode('2d','3D หยุดทำงาน · เปลี่ยนเป็นภาพสำนักงานให้แล้ว'); if(scene3D){scene3D.dispose();scene3D=null;} drawOfficeScene(latestScene.tickets); }
      });
      scene3D.setPaused(sceneMotionPaused);
      setSceneMode('3d'); scene3D.update(latestScene);
    }).catch(error => { console.warn('[office-3d] Unable to initialize', error); if (scene3D) { scene3D.dispose(); scene3D=null; } setSceneMode('2d','เครื่องนี้เปิด 3D ไม่ได้ · ใช้ภาพสำนักงานแทนได้ตามปกติ'); })
      .finally(() => {scene3DLoading=false;});
  }
  ['3d','2d'].forEach(mode => {if(el('office-mode-'+mode)) el('office-mode-'+mode).addEventListener('click',()=>{setSceneMode(mode);if(latestScene)drawOfficeScene(latestScene.tickets);});});
  function sceneSummary(tickets) {
    const uniqueMachines=items=>new Set(items.map(t=>t.device_sn)).size;
    const reception=tickets.filter(t=>t.status==='New');
    const waiting=tickets.filter(t=>['New','Diagnosing','Waiting for Parts'].includes(t.status));
    const repairing=tickets.filter(t=>['In Repair','Testing'].includes(t.status));
    const dispatch=tickets.filter(t=>t.status==='Resolved/Closed'&&t.handover_status==='pending');
    const unknown=tickets.filter(t=>t.status==='Resolved/Closed'&&t.handover_status==='unrecorded');
    text('office-customer-count',readOnly ? data.devices.length : new Set(reception.map(t=>t.customer_id)).size);
    text('office-waiting-count',uniqueMachines(waiting));
    text('office-repair-count',uniqueMachines(repairing));
    text('office-dispatch-count',uniqueMachines(dispatch));
    text('office-front-summary',new Set(reception.map(t=>t.customer_id)).size+' รายในคิว · '+uniqueMachines(reception)+' เครื่องรอรับงาน');
    text('office-task-count',tickets.length+' งานในตัวกรองนี้');
    const list=el('office-dispatch-list');list.replaceChildren();
    [['รอจัดส่ง / นัดรับ',dispatch,'pending'],['ยังไม่ระบุการส่งมอบ',unknown,'unrecorded']].forEach(([label,items,kind])=>{
      const heading=document.createElement('p');heading.textContent=label+' · '+items.length+' งาน';heading.className='dispatch-group '+kind;list.appendChild(heading);
      if(!items.length){const empty=document.createElement('small');empty.textContent='ไม่มีงานในกลุ่มนี้';list.appendChild(empty);}
      items.slice(0,4).forEach(ticket=>{
        const button=document.createElement('button');button.type='button';button.textContent='#'+ticket.ticket_id+' · '+ticket.model+' ↗';
        button.addEventListener('click',()=>{const desk=document.querySelector('.office-desk[data-ticket-id="'+ticket.ticket_id+'"]');if(desk)openTicket(desk);});list.appendChild(button);
      });
      if(items.length>4){const more=document.createElement('button');more.textContent='ดูงานซ่อมเสร็จทั้งหมด →';more.type='button';more.addEventListener('click',()=>chooseStage('Resolved/Closed'));list.appendChild(more);}
    });
  }

  function applyFilters() {
    const search = el('office-search').value.trim().toLocaleLowerCase();
    const center = el('office-center').value;
    const tech = el('office-tech').value;
    const device = el('office-device') ? el('office-device').value : '';
    let visible = 0;
    const visibleTickets = [];
    document.querySelectorAll('.office-room').forEach(room => {
      let count = 0;
      room.hidden = !!stage && room.dataset.roomStatus !== stage;
      room.querySelectorAll('[data-ticket-id]').forEach(button => {
        const ticket = byId.get(button.dataset.ticketId);
        const ticketCenter = ticket.center_id == null ? 'central' : String(ticket.center_id);
        const haystack = [ticket.ticket_id, '#' + ticket.ticket_id, ticket.customer_name, ticket.model, ticket.device_sn, ticket.tech_name, ticket.issue_category].join(' ').toLocaleLowerCase();
        const matches = (!device || device === ticket.device_sn) && (!search || haystack.includes(search)) && (!center || center === ticketCenter) &&
          (!tech || (tech === 'unassigned' ? ticket.assigned_tech_id == null : tech === String(ticket.assigned_tech_id)));
        button.hidden = !matches;
        if (matches) { count++; if (!room.hidden) visibleTickets.push(ticket); }
      });
      room.querySelector('[data-room-count]').textContent = count;
      const empty = room.querySelector('.room-empty');
      empty.hidden = count > 0;
      empty.querySelector('p').textContent = search || center || tech || device ? 'ไม่พบงานที่ตรงกับตัวกรอง' : 'ยังไม่มีงานในโซนนี้';
      if (!room.hidden) visible += count;
    });
    el('office-shown-count').textContent = 'แสดง ' + visible + ' / ' + data.tickets.length + ' งาน';
    drawOfficeScene(visibleTickets);
    sceneSummary(visibleTickets);
    if (readOnly) {
      const currentDevice = data.devices.find(item => item.sn === device);
      const currentJob = data.tickets.find(ticket => ticket.device_sn === device);
      text('office-device-location', currentDevice ? currentDevice.model + ' · ' + currentDevice.sn + ' — ' +
        (currentJob ? 'ขั้นตอนปัจจุบัน: ' + currentDevice.label : 'ยังไม่มีงานซ่อม เครื่องนี้จึงยังไม่ปรากฏในห้องทำงาน') :
        'เลือกเครื่องของคุณด้านบนเพื่อเน้นห้องที่เครื่องอยู่ในขั้นตอนปัจจุบัน');
    }
    document.querySelectorAll('[data-customer-device]').forEach(button => {
      const active = !!device && button.dataset.customerDevice === device;
      button.classList.toggle('is-selected', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }
  if (el('office-device')) el('office-device').addEventListener('change', () => chooseStage(''));
  document.querySelectorAll('[data-customer-device]').forEach(button => button.addEventListener('click', () => {
    el('office-device').value = button.dataset.customerDevice;
    const job = data.tickets.find(ticket => ticket.device_sn === button.dataset.customerDevice);
    chooseStage(job ? job.status : '');
  }));
  ['office-search', 'office-center', 'office-tech'].forEach(id => {
    el(id).addEventListener(id === 'office-search' ? 'input' : 'change', applyFilters);
  });
  const stageButtons = document.querySelectorAll('[data-stage]');
  function chooseStage(newStage) {
    stage = newStage;
    stageButtons.forEach(button => {
      const active = button.dataset.stage === stage;
      button.classList.toggle('is-selected', active);
      button.setAttribute('aria-pressed', String(active));
    });
    applyFilters();
  }
  stageButtons.forEach(button => button.addEventListener('click', () => chooseStage(button.dataset.stage)));
  el('office-reset').addEventListener('click', () => {
    ['office-search', 'office-center', 'office-tech', 'office-device'].forEach(id => { if (el(id)) el(id).value = ''; });
    chooseStage('');
  });
  el('office-refresh').addEventListener('click', () => window.location.reload());
  el('office-front-filter').addEventListener('click', () => chooseStage('New'));
  function zoomScene(delta) { if(sceneMode==='3d'&&scene3D){scene3D.zoom(delta);return;} sceneZoom = Math.max(.75, Math.min(1.5, sceneZoom + delta)); applyFilters(); }
  el('office-zoom-in').addEventListener('click', () => zoomScene(.15));
  el('office-zoom-out').addEventListener('click', () => zoomScene(-.15));
  el('office-zoom-reset').addEventListener('click', () => {if(sceneMode==='3d'&&scene3D){scene3D.reset();return;}sceneZoom = 1; applyFilters();});
  const motionButton = el('office-motion');
  if (motionButton) {
    let paused = sceneMotionPaused;
    const updateMotion = () => {
      sceneMotionPaused = !!paused;
      el('office-scene').classList.toggle('scene-static', !!paused);
      if(scene3D)scene3D.setPaused(!!paused);
      motionButton.setAttribute('aria-pressed', String(!!paused));
      motionButton.textContent = paused ? '▶ การเคลื่อนไหว' : 'Ⅱ หยุดภาพเคลื่อนไหว';
    };
    motionButton.addEventListener('click', () => { paused = !paused; updateMotion(); });
    document.addEventListener('visibilitychange', () => {el('office-scene').classList.toggle('scene-hidden', document.hidden);if(scene3D)scene3D.setVisible(!document.hidden&&sceneMode==='3d'&&!dialog.open);});
    updateMotion();
  }


  function changeSummary() {
    if (!selected || readOnly) return;
    const newStatus = el('office-edit-status').value;
    const newTech = el('office-edit-tech').value;
    const changedStatus = newStatus !== selected.status;
    const changedTech = newTech !== String(selected.assigned_tech_id || '');
    const handover = el('office-edit-handover');
    const closing = newStatus === 'Resolved/Closed';
    el('office-handover-field').hidden = !closing;
    if (!closing) handover.value = 'unrecorded';
    else if (selected.status !== 'Resolved/Closed' && handover.value === 'unrecorded') handover.value = 'pending';
    const changedHandover = handover.value !== (selected.handover_status || 'unrecorded');
    const changes = [];
    if (changedStatus) changes.push(data.labels[selected.status] + ' → ' + data.labels[newStatus]);
    if (changedTech) changes.push('มอบหมาย: ' + el('office-edit-tech').selectedOptions[0].textContent);
    if (changedHandover) changes.push('ส่งมอบ: ' + handover.selectedOptions[0].textContent);
    el('office-save').disabled = submitting || !(changedStatus || changedTech || changedHandover);
    text('office-change-summary', changes.length ? 'พร้อมบันทึก · ' + changes.join(' / ') : 'ยังไม่มีการเปลี่ยนแปลง');
  }
  function openTicket(button, focusTarget) {
    selected = byId.get(button.dataset.ticketId);
    if (!selected) return;
    openingButton = focusTarget || button;
    submitting = false;
    if (form) el('office-save').textContent = 'บันทึกการเปลี่ยนแปลง';
    text('office-detail-title', 'งานซ่อม #' + selected.ticket_id);
    text('office-detail-model', selected.model);
    text('office-detail-customer', selected.customer_name + ' · ' + value(selected.issue_category));
    text('office-detail-status', data.labels[selected.status]);
    text('office-detail-sn', selected.device_sn);
    text('office-detail-center', selected.center_name || 'ส่วนกลาง');
    text('office-detail-created', selected.created_at);
    text('office-detail-booking', selected.booking_date ? selected.booking_date + ' ' + value(selected.booking_time_slot) : 'ไม่ได้ระบุวันนัด');
    text('office-detail-description', selected.description || selected.issue_category || 'ยังไม่มีรายละเอียดเพิ่มเติม');
    const currentIndex = data.statuses.indexOf(selected.status);
    el('office-detail-steps').replaceChildren();
    data.statuses.forEach((status, index) => {
      const item = document.createElement('li');
      const number = document.createElement('span');
      number.textContent = index + 1;
      item.appendChild(number);
      item.appendChild(document.createTextNode(data.labels[status]));
      if (index === currentIndex) {
        item.className = 'is-current';
        item.setAttribute('aria-current', 'step');
      }
      el('office-detail-steps').appendChild(item);
    });
    if (!readOnly) {
    el('office-edit-status').value = selected.status;
    el('office-edit-handover').value = selected.handover_status || 'unrecorded';
    el('office-expected-handover').value = selected.handover_status || 'unrecorded';
    const techSelect = el('office-edit-tech');
    techSelect.replaceChildren();
    option(techSelect, '— ยังไม่มอบหมาย —', '');
    data.techs.filter(tech => (tech.active && (selected.center_id == null || tech.center_id === selected.center_id)) || tech.id === selected.assigned_tech_id)
      .forEach(tech => option(techSelect, tech.name + (tech.active ? '' : ' (ระงับบัญชี)'), tech.id));
    if (selected.assigned_tech_id != null && !data.techs.some(tech => tech.id === selected.assigned_tech_id)) {
      option(techSelect, selected.tech_name || 'ช่างเดิม', selected.assigned_tech_id);
    }
    techSelect.value = String(selected.assigned_tech_id || '');
    form.action = '/admin/ticket/' + selected.ticket_id + '/update';
    el('office-expected-status').value = selected.status;
    el('office-expected-tech').value = String(selected.assigned_tech_id || '');
    const returnUrl = new URL(data.returnUrl, window.location.origin);
    returnUrl.searchParams.set('updated', selected.ticket_id);
    el('office-return-url').value = returnUrl.pathname + returnUrl.search;
    el('office-full-detail').href = '/admin/ticket/' + selected.ticket_id;
    const nextStatus = data.statuses[currentIndex + 1];
    el('office-next').hidden = !nextStatus;
    el('office-next').textContent = nextStatus ? 'ขั้นตอนถัดไป: ' + data.labels[nextStatus] + ' →' : '';
    el('office-next').onclick = () => {
      el('office-edit-status').value = nextStatus;
      changeSummary();
    };
    }
    el('office-full-detail').href = (readOnly ? '/customer/ticket/' : '/admin/ticket/') + selected.ticket_id;
    if (readOnly) text('office-customer-handover', 'การส่งมอบ: ' + ({unrecorded:'ยังไม่ระบุการส่งมอบ',pending:'รอจัดส่ง / นัดรับ',shipped:'จัดส่งแล้ว',collected:'รับเครื่องที่ร้านแล้ว'}[selected.handover_status] || 'ยังไม่ระบุ'));
    const history = el('office-history');
    history.replaceChildren();
    if (!selected.history.length) {
      const empty = document.createElement('li');
      empty.textContent = 'ยังไม่มีประวัติการเปลี่ยนสถานะที่บันทึกไว้';
      history.appendChild(empty);
    }
    selected.history.slice().reverse().forEach(entry => {
      const item = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = entry.status;
      const detail = document.createElement('span');
      detail.textContent = entry.at + (entry.by ? ' · ' + entry.by : '');
      item.append(title, detail);
      if (entry.note) {
        const note = document.createElement('p');
        note.textContent = entry.note;
        item.appendChild(note);
      }
      history.appendChild(item);
    });
    changeSummary();
    if(scene3D)scene3D.setVisible(false);
    dialog.showModal();
    dialog.querySelector('.office-detail-body').scrollTop = 0;
  }
  document.querySelectorAll('[data-ticket-id]').forEach(button => button.addEventListener('click', () => openTicket(button)));
  if (!readOnly) {
  el('office-edit-status').addEventListener('change', changeSummary);
  el('office-edit-tech').addEventListener('change', changeSummary);
  el('office-edit-handover').addEventListener('change', changeSummary);
  }
  el('office-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    }
  });
  dialog.addEventListener('close', () => { if(scene3D)scene3D.setVisible(sceneMode==='3d'&&!document.hidden); if (openingButton) openingButton.focus(); });
  window.addEventListener('pagehide', () => {if(scene3D){scene3D.dispose();scene3D=null;}});
  window.addEventListener('pageshow', event => {if(event.persisted&&latestScene)drawOfficeScene(latestScene.tickets);});
  if (form) form.addEventListener('submit', event => {
    if (submitting || el('office-save').disabled) { event.preventDefault(); return; }
    submitting = true;
    el('office-save').disabled = true;
    el('office-save').textContent = 'กำลังบันทึก…';
  });
  const updated = new URLSearchParams(window.location.search).get('updated');
  if (!readOnly && updated && /^\d+$/.test(updated)) {
    text('office-notice', 'บันทึกงาน #' + updated + ' แล้ว · สถานะและผู้รับผิดชอบอัปเดตเรียบร้อย');
    el('office-notice').hidden = false;
    const cleanUrl = new URL(window.location.href);
    cleanUrl.searchParams.delete('updated');
    window.history.replaceState(null, '', cleanUrl.pathname + cleanUrl.search);
  }
  applyFilters();
})();
