/* Owner-only factory. Guided demo is read-only and advances only on user input. */
(function () {
  'use strict';
  const source=document.getElementById('factory-data');if(!source)return;
  const data=JSON.parse(source.textContent),el=id=>document.getElementById(id);
  const bySerial=new Map(data.devices.map(device=>[device.sn,device]));
  let selectedType='',opener=null;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  let blinkPaused=reduced.matches;
  function openMachine(button) {
    const device=bySerial.get(button.dataset.factorySn);if(!device)return;opener=button;
    el('factory-machine-title').textContent=device.model;el('factory-machine-sn').textContent=device.sn+' · '+device.type;
    el('factory-machine-status').textContent=device.statusLabel+' · สะสม '+device.hours+' ชั่วโมง'+(device.due?' · มีงานบำรุงรักษาถึงรอบ':'');
    const tasks=el('factory-machine-tasks');tasks.replaceChildren();
    device.tasks.forEach(task=>{const li=document.createElement('li');const title=document.createElement('strong');title.textContent=task.name;const detail=document.createElement('p');detail.textContent=task.detail;li.append(title,detail);tasks.appendChild(li);});
    if(!device.tasks.length){const li=document.createElement('li');li.textContent=['sold','decommissioned'].includes(device.status)?'เครื่องนี้ไม่รวมการคำนวณรอบบำรุงรักษา':'ยังไม่มีงานบำรุงรักษาที่ถึงรอบตามข้อมูลปัจจุบัน';tasks.appendChild(li);}
    el('factory-machine-history').href='/device/'+encodeURIComponent(device.sn)+'/history';
    el('factory-machine-ticket').hidden=!device.ticketId;
    if(device.ticketId)el('factory-machine-ticket').href='/customer/ticket/'+device.ticketId;
    el('factory-machine-dialog').showModal();
  }
  document.querySelectorAll('[data-factory-sn]').forEach(button=>button.addEventListener('click',()=>openMachine(button)));
  const due=data.devices.filter(device=>device.due);
  el('factory-due-count').textContent=due.length+' เครื่องถึงรอบดูแล · รวมเครื่องที่มีงานซ่อม';
  due.forEach(device=>{const button=document.createElement('button');button.type='button';const title=document.createElement('strong');title.textContent=device.model;const sn=document.createElement('small');sn.textContent=device.sn;const detail=document.createElement('span');detail.textContent=device.tasks.length+' งานดูแลถึงรอบ';button.append(title,sn,detail);button.addEventListener('click',()=>{const target=[...document.querySelectorAll('[data-factory-sn]')].find(item=>item.dataset.factorySn===device.sn);if(target)openMachine(target);});el('factory-due-list').appendChild(button);});
  if(!due.length){const text=document.createElement('p');text.textContent='ยังไม่มีเครื่องที่ถึงรอบบำรุงรักษาตามข้อมูลที่บันทึก';el('factory-due-list').appendChild(text);}
  function filter() {
    const term=el('factory-search').value.trim().toLocaleLowerCase(),status=el('factory-filter').value;let count=0;
    document.querySelectorAll('[data-factory-zone]').forEach(zone=>{
      zone.hidden=!!selectedType&&zone.dataset.factoryZone!==selectedType;let zoneCount=0;
      zone.querySelectorAll('[data-factory-sn]').forEach(button=>{const device=bySerial.get(button.dataset.factorySn);const match=(!term||(device.sn+' '+device.model).toLocaleLowerCase().includes(term))&&(!status||(status==='due'?device.due:status==='inactive'?['sold','decommissioned'].includes(device.status):device.status===status));button.hidden=!match;if(match){zoneCount++;if(!zone.hidden)count++;}});
      zone.querySelector('.factory-zone-empty').hidden=zoneCount>0;
    });el('factory-visible-count').textContent='แสดง '+count+' / '+data.devices.length+' เครื่อง';
    document.querySelectorAll('[data-factory-type]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.factoryType===selectedType)));
  }
  document.querySelectorAll('[data-factory-type]').forEach(button=>button.addEventListener('click',()=>{selectedType=selectedType===button.dataset.factoryType?'':button.dataset.factoryType;filter();}));
  el('factory-search').addEventListener('input',filter);el('factory-filter').addEventListener('change',filter);
  el('factory-reset').addEventListener('click',()=>{selectedType='';el('factory-search').value='';el('factory-filter').value='';filter();});
  function blink(){document.querySelector('.factory').classList.toggle('blink-paused',blinkPaused||document.hidden);el('factory-blink').setAttribute('aria-pressed',String(blinkPaused));el('factory-blink').textContent=blinkPaused?'เปิดไฟกะพริบ':'หยุดไฟกะพริบ';}
  el('factory-blink').addEventListener('click',()=>{blinkPaused=!blinkPaused;blink();});
  reduced.addEventListener('change',()=>{blinkPaused=reduced.matches;blink();});
  document.addEventListener('visibilitychange',()=>{blink();});
  el('factory-machine-close').addEventListener('click',()=>el('factory-machine-dialog').close());
  el('factory-machine-dialog').addEventListener('close',()=>{if(opener)opener.focus();});
  el('factory-legacy').addEventListener('toggle',event=>{if(event.target.open)window.dispatchEvent(new Event('resize'));});
  filter();blink();
})();
