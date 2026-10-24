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

  // Bounded SVG scene: at most four machine icons per room, no renderer loop or polling.
  let sceneZoom = 1;
  const roomLayout = [
    {index: 0, x: 15, y: 292, name: 'รับงาน / เตรียมซ่อม', color: '#5485a2'},
    {index: 1, x: 15, y: 18, name: 'ตรวจวิเคราะห์', color: '#7c73b4'},
    {index: 2, x: 365, y: 292, name: 'คลังอะไหล่ / รออะไหล่', color: '#b39a56'},
    {index: 3, x: 365, y: 18, name: 'ห้องซ่อมเครื่อง', color: '#359d94'},
    {index: 4, x: 715, y: 18, name: 'ห้องทดสอบคุณภาพ', color: '#3d8eb3'},
    {index: 5, x: 715, y: 292, name: 'ซ่อมเสร็จ / เตรียมส่งมอบ', color: '#528f7d'}
  ];
  function sceneNode(tag, attrs, parent, content) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (content != null) node.textContent = content;
    if (parent) parent.appendChild(node);
    return node;
  }
  function project(x, y, z = 0) { return [600 + (x - 525) * (0.75 + y * 0.00055), 115 + y * 0.72 - z]; }
  function polygon(points, fill, parent, stroke = '#3c596a') {
    return sceneNode('polygon', {points: points.map(p => p.join(',')).join(' '), fill, stroke, 'stroke-width': 1}, parent);
  }
  function block(parent, x, y, width, depth, height, colors) {
    const top = [project(x,y,height),project(x+width,y,height),project(x+width,y+depth,height),project(x,y+depth,height)];
    polygon([top[3],top[2],project(x+width,y+depth),project(x,y+depth)], colors[1], parent);
    polygon([top[1],top[2],project(x+width,y+depth),project(x+width,y)], colors[2], parent);
    polygon(top, colors[0], parent);
  }
  function sceneLabel(parent, x, y, title, subtitle, color) {
    const group = sceneNode('g', {'pointer-events':'none'}, parent);
    sceneNode('rect', {x:x-95,y:y-23,width:190,height:43,rx:7,fill:'#16354c',stroke:color,'stroke-width':1.3},group);
    sceneNode('text', {x,y:y-5,'text-anchor':'middle',fill:'#e8f1f8','font-size':13,'font-weight':650},group,title);
    sceneNode('text', {x,y:y+11,'text-anchor':'middle',fill:'#94c4ce','font-size':9},group,subtitle);
  }
  function plant(parent, x, y) {
    block(parent,x,y,14,14,15,['#b1c8c2','#6d8581','#8da29a']);
    const p=project(x+7,y+7,33);
    polygon([[p[0]-12,p[1]],[p[0]-5,p[1]-12],[p[0]+6,p[1]-14],[p[0]+14,p[1]-2],[p[0]+5,p[1]+9],[p[0]-7,p[1]+7]],'#68a78a',parent,'#87bfa0');
  }
  function person(parent,x,y,color,label) {
    const p=project(x,y);
    sceneNode('ellipse',{cx:p[0],cy:p[1]+3,rx:11,ry:4,fill:'#08121f',opacity:.6},parent);
    sceneNode('path',{d:`M${p[0]-5} ${p[1]-18} L${p[0]-7} ${p[1]-3} L${p[0]+6} ${p[1]-3} L${p[0]+5} ${p[1]-18}Z`,fill:color,stroke:'#7ea3b3'},parent);
    sceneNode('circle',{cx:p[0],cy:p[1]-25,r:6,fill:'#c8cbd9',stroke:'#e6e2e0'},parent);
    if(label)sceneNode('text',{x:p[0],y:p[1]+16,'text-anchor':'middle',fill:'#b4c9d3','font-size':8},parent,label);
  }
  function machine(parent, x, y, ticket, color) {
    const button=sceneNode('g', {role:'button',tabindex:0,'aria-label':'เปิดงาน #'+ticket.ticket_id+' '+ticket.model,class:'scene-machine'+(readOnly?' customer-machine':'')},parent);
    block(button,x,y,52,49,9,['#486375','#23394a','#304b5c']);
    block(button,x+5,y+5,40,35,49,['#648290','#223b4c','#325363']);
    const a=project(x+10,y+41,39), b=project(x+39,y+41,39), c=project(x+39,y+41,16), d=project(x+10,y+41,16);
    polygon([a,b,c,d],'#0c2330',button,'#84a3a9');
    const nozzle=project(x+25,y+42,35);
    sceneNode('path',{d:`M${nozzle[0]} ${nozzle[1]}v10`,stroke:color,'stroke-width':3},button);
    const light=project(x+39,y+42,46);
    sceneNode('circle',{cx:light[0],cy:light[1],r:2.5,fill:color},button);
    const label=project(x+25,y+60);
    sceneNode('rect',{x:label[0]-31,y:label[1]-5,width:62,height:19,rx:4,fill:'#102432',stroke:color},button);
    sceneNode('text',{x:label[0],y:label[1]+8,'text-anchor':'middle',fill:'#d9eaf0','font-size':9,'font-weight':600},button,'#'+ticket.ticket_id);
    const open=() => {
      const desk = document.querySelector('.office-desk[data-ticket-id="'+ticket.ticket_id+'"]');
      if(desk) openTicket(desk);
    };
    button.addEventListener('click',event=>{event.stopPropagation();open();});
    button.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();open();}});
  }
  function drawOfficeScene(tickets) {
    const svg=el('office-scene');
    if(!svg)return;
    svg.replaceChildren();
    sceneNode('title',{},svg,'แผนผังสถานะงานซ่อม คลิกห้องหรือเครื่องเพื่อจัดการงาน');
    const group=sceneNode('g',{id:'office-scene-content',transform:`translate(${600*(1-sceneZoom)},${350*(1-sceneZoom)}) scale(${sceneZoom})`},svg);
    block(group,-8,-8,1068,720,6,['#2b4554','#071320','#0c2131']);
    polygon([project(0,0,75),project(1050,0,75),project(1050,0),project(0,0)],'#213d4b',group,'#507181');
    // Wide aisle joins reception, work rooms and dispatch.
    polygon([project(0,263),project(1050,263),project(1050,286),project(0,286)],'#254a54',group,'#416971');
    sceneNode('path',{d:'M'+project(25,275).join(' ')+'L'+project(1020,275).join(' '),stroke:'#80b5ae','stroke-dasharray':'10 15',opacity:.5},group);
    roomLayout.slice().sort((a,b)=>a.y-b.y).forEach(room=>{
      const currentTickets=tickets.filter(t=>t.status===data.statuses[room.index]);
      const roomGroup=sceneNode('g',{class:'scene-room'+(stage===data.statuses[room.index]?' selected':''),role:'button',tabindex:0,'aria-label':room.name+' '+currentTickets.length+' งาน'},group);
      const selectedRoom = !stage || stage===data.statuses[room.index];
      roomGroup.setAttribute('opacity',selectedRoom?1:.38);
      polygon([project(room.x,room.y),project(room.x+320,room.y),project(room.x+320,room.y+240),project(room.x,room.y+240)],room.color,roomGroup,'#729f9c').setAttribute('fill-opacity','.2');
      polygon([project(room.x,room.y,53),project(room.x,room.y+240,53),project(room.x,room.y+240),project(room.x,room.y)],'#8cb5bc',roomGroup,'#83b8c1').setAttribute('fill-opacity','.09');
      polygon([project(room.x+320,room.y,53),project(room.x+320,room.y+240,53),project(room.x+320,room.y+240),project(room.x+320,room.y)],'#8cb5bc',roomGroup,'#83b8c1').setAttribute('fill-opacity','.09');
      block(roomGroup,room.x+30,room.y+20,118,25,24,['#6b959c','#304852','#456974']);
      const monitor=project(room.x+90,room.y+30,43);
      sceneNode('rect',{x:monitor[0]-12,y:monitor[1]-8,width:25,height:17,rx:2,fill:'#0d2635',stroke:room.color},roomGroup);
      const items=currentTickets.slice(0,4);
      items.forEach((ticket,i)=>machine(roomGroup,room.x+28+(i%2)*150,room.y+78+Math.floor(i/2)*85,ticket,room.color));
      if(!items.length){
        block(roomGroup,room.x+175,room.y+95,75,38,23,['#577581','#263f4a','#3c5662']);
        const empty=project(room.x+160,room.y+200);
        sceneNode('text',{x:empty[0],y:empty[1],'text-anchor':'middle',fill:'#6a8796','font-size':10},roomGroup,'ไม่มีงานในห้องนี้');
      }
      const assigned=currentTickets.find(t=>t.tech_name);
      if(assigned)person(roomGroup,room.x+270,room.y+164,room.color,assigned.tech_name.slice(0,12));
      if(currentTickets.length>4){const more=project(room.x+270,room.y+220);sceneNode('text',{x:more[0],y:more[1],fill:'#b6d9db','font-size':10,'text-anchor':'middle'},roomGroup,'+'+(currentTickets.length-4)+' งาน');}
      const label=project(room.x+160,room.y,68);
      sceneLabel(roomGroup,label[0],label[1],String(room.index+1).padStart(2,'0')+' · '+room.name,currentTickets.length+' งาน  /  '+data.labels[data.statuses[room.index]],room.color);
      const choose=()=>chooseStage(stage===data.statuses[room.index]?'':data.statuses[room.index]);
      roomGroup.addEventListener('click',choose);
      roomGroup.addEventListener('keydown',event=>{if(event.target===roomGroup&&(event.key==='Enter'||event.key===' ')){event.preventDefault();choose();}});
    });
    // Storefront facade: counters and people are symbolic representations of queued records.
    block(group,15,558,650,130,3,['#3a515b','#1d3542','#314957']);
    block(group,55,573,320,34,34,['#849d9f','#4a6870','#537d80']);
    for(let i=0;i<8;i++)block(group,55+i*40,567,40,43,72,[i%2?'#386d78':'#c5b578',i%2?'#29545d':'#9f935c','#234755']);
    const frontLabel=project(213,570,105);
    sceneLabel(group,frontLabel[0],frontLabel[1],'TD PRINT CARE · หน้าร้าน',readOnly?'คิวรับบริการเฉพาะของคุณ':'คิวรับบริการ / รับเครื่องซ่อม','#42b9ab');
    const customers=new Set(tickets.filter(t=>t.status==='New').map(t=>t.customer_id)).size;
    for(let i=0;i<Math.min(customers,5);i++)person(group,100+i*60,651,['#549caa','#bb975e','#8480ad'][i%3]);
    const queue=project(482,630,10);
    sceneNode('text',{x:queue[0],y:queue[1],fill:'#b4d3d9','font-size':14,'font-weight':600,'text-anchor':'middle'},group,readOnly ? tickets.filter(t=>t.status==='New').length+' เครื่องของคุณรอรับงาน' : customers+' รายในคิวรับงาน');
    sceneNode('text',{x:queue[0],y:queue[1]+20,fill:'#7199a7','font-size':9,'text-anchor':'middle'},group,'อ้างอิงจากงานใหม่ในระบบ');
    block(group,713,558,320,130,3,['#3c4b60','#1c2e42','#2e4055']);
    const dispatch=tickets.filter(t=>t.status==='Resolved/Closed'&&t.handover_status==='pending');
    for(let i=0;i<Math.min(dispatch.length,5);i++)block(group,740+(i%3)*75,590+Math.floor(i/3)*55,45,38,30,['#bcac78','#8e8054','#a69665']);
    const shipLabel=project(870,575,90);
    sceneLabel(group,shipLabel[0],shipLabel[1],'จุดรอจัดส่ง / นัดรับ',new Set(dispatch.map(t=>t.device_sn)).size+' เครื่องรอส่งมอบ','#ae9cc8');
    [[0,0],[350,0],[700,0],[1040,0],[0,275],[1040,275],[0,695],[345,695],[700,695],[1040,695]].forEach(([x,y])=>plant(group,x,y));
    const caption=sceneNode('text',{x:600,y:735,'text-anchor':'middle',fill:'#607e91','font-size':11},svg,readOnly?'แสดงเฉพาะเครื่องของคุณ · ตำแหน่งในขั้นตอนงาน ไม่ใช่พิกัดที่ตรวจจับจริง':'แผนผังเชิงสัญลักษณ์จากสถานะงาน · รูปคนแทนคิว / ผู้รับผิดชอบ ไม่ใช่การแสดงตำแหน่งจริง');
  }
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
  function zoomScene(delta) { sceneZoom = Math.max(.75, Math.min(1.5, sceneZoom + delta)); applyFilters(); }
  el('office-zoom-in').addEventListener('click', () => zoomScene(.15));
  el('office-zoom-out').addEventListener('click', () => zoomScene(-.15));
  el('office-zoom-reset').addEventListener('click', () => {sceneZoom = 1; applyFilters();});

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
  function openTicket(button) {
    selected = byId.get(button.dataset.ticketId);
    if (!selected) return;
    openingButton = button;
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
  dialog.addEventListener('close', () => { if (openingButton) openingButton.focus(); });
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
