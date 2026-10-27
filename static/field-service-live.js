/* Real records arrive already scoped by the server. All writes use explicit CSRF-protected forms. */
(function () {
  'use strict';
  const byId = id => document.getElementById(id);
  function element(tag, text, attrs) {
    const e = document.createElement(tag); if (text != null) e.textContent = text;
    Object.keys(attrs || {}).forEach(k => e.setAttribute(k, attrs[k])); return e;
  }
  const create = byId('fsl-create-data');
  if (create) {
    const data = JSON.parse(create.textContent), customer = byId('fsl-customer'), devices = byId('fsl-device');
    customer.addEventListener('change', function () {
      devices.replaceChildren(element('option', 'เลือกเครื่อง', { value: '' }));
      data.devices.filter(d => String(d.customer_id) === customer.value).forEach(d => devices.append(element('option', d.model + ' · ' + d.device_sn, { value: d.device_sn })));
      const c = data.customers.find(c => String(c.customer_id) === customer.value);
      byId('fsl-address').value = c ? (c.address || '') : ''; byId('fsl-phone').value = c ? (c.phone || '') : '';
    });
    const center = byId('fsl-center'), tech = byId('fsl-tech');
    function filterTechs() { Array.from(tech.options).forEach(o => { o.disabled = !!o.value && o.dataset.center !== center.value; }); if (tech.selectedOptions[0] && tech.selectedOptions[0].disabled) tech.value = ''; }
    center.addEventListener('change', filterTechs); filterTechs();
    byId('fsl-date').addEventListener('change', function () { byId('fsl-start').required = !!this.value; byId('fsl-end').required = !!this.value; });
  }
  const planData = byId('fsl-plan-data');
  if (!planData) return;
  const data = JSON.parse(planData.textContent), form = byId('fsl-plan-form'), C = window.FieldServiceCore;
  const pool = new Map(data.jobs.map(j => [j.job_id, j])); let order = data.payload.order.slice();
  const ns = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, text) { const n = document.createElementNS(ns, tag); Object.keys(attrs).forEach(k => n.setAttribute(k, attrs[k])); if (text != null) n.textContent = text; return n; }
  function dirty() { byId('fsl-dirty').textContent = 'มีการเปลี่ยนแปลงที่ยังไม่ได้บันทึก'; render(); }
  function button(text, label, fn, disabled) { const b = element('button', text, {type:'button','aria-label':label}); b.disabled = !!disabled; b.addEventListener('click',fn); return b; }
  function render() {
    byId('fsl-order').value = JSON.stringify(order);
    const candidate = byId('fsl-candidate'); candidate.replaceChildren();
    data.jobs.filter(j => !order.includes(j.job_id)).forEach(j => candidate.append(element('option',j.customer_name+' · '+j.site+' · '+j.start_time,{value:j.job_id})));
    byId('fsl-add-stop').disabled = !candidate.options.length || order.length >= 30;
    const stops = byId('fsl-stops'); stops.replaceChildren();
    order.forEach((id,i) => {
      const j=pool.get(id), li=element('li');
      li.append(element('a',j.customer_name+' · '+j.site,{href:'/field-service/jobs/'+id}),element('p',j.start_time+'–'+j.end_time+' · บริการ '+j.service_minutes+' นาที'));
      function move(n) { const target=i+n; [order[i],order[target]]=[order[target],order[i]]; dirty(); }
      li.append(button('↑','เลื่อน '+j.site+' ขึ้น',()=>move(-1),i===0),button('↓','เลื่อน '+j.site+' ลง',()=>move(1),i===order.length-1),button('นำออก','นำ '+j.site+' ออกจากแผน',()=>{order.splice(i,1);dirty();}));
      stops.append(li);
    });
    if (!order.length) stops.append(element('li','ยังไม่มีจุดแวะ เลือกใบงานแล้วกดเพิ่ม'));
    draw();
  }
  function draw() {
    const map=byId('fsl-map'); map.replaceChildren(); const warnings=byId('fsl-warnings'); warnings.replaceChildren();
    const c=data.center;
    const hasCoords=p=>p && p.latitude!=null && p.longitude!=null && Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude));
    const selected=order.map(id=>pool.get(id)), positioned=selected.filter(hasCoords);
    const valid=hasCoords(c) && selected.every(hasCoords);
    const lat0=hasCoords(c)?Number(c.latitude):(positioned[0]?Number(positioned[0].latitude):0);
    const lng0=hasCoords(c)?Number(c.longitude):(positioned[0]?Number(positioned[0].longitude):0);
    const project=p=>({x:(Number(p.longitude)-lng0)*111.32*Math.cos(lat0*Math.PI/180),y:(Number(p.latitude)-lat0)*110.57});
    let result=null;
    if (valid && order.length && C) {
      const start=Object.assign({id:'HQ'},project(c));
      const routeStops=selected.map(j=>Object.assign({id:j.job_id,window:[j.start_time,j.end_time],serviceMin:j.service_minutes},project(j)));
      result=C.planRoute({start: start,stops:routeStops,end:form.elements.end.value,departAt:form.elements.depart.value,workEnd:form.elements.work_end.value});
      byId('fsl-totals').textContent='ประมาณ '+result.totalKm+' กม. · เดินทาง '+C.fmtDuration(result.travelMin)+' · บริการ '+C.fmtDuration(result.serviceMin)+' · จบประมาณ '+C.fmt(result.endAt)+' (ประมาณจากพิกัด ไม่คิดจราจร)';
      result.warnings.forEach(w=>warnings.append(element('li',w.text.replace(/FS-[a-f0-9]{32}/g,id=>pool.has(id)?pool.get(id).site:id))));
    } else {
      byId('fsl-totals').textContent=order.length?'ยังคำนวณระยะทางและเวลาถึงไม่ได้ กรุณาระบุพิกัดสาขาและจุดแวะให้ครบ':'เลือกจุดแวะเพื่อวางแผน';
      if (C) C.overlaps(selected.map(j=>({id:j.job_id,window:[j.start_time,j.end_time]}))).forEach(w=>warnings.append(element('li',w.text.replace(/FS-[a-f0-9]{32}/g,id=>pool.has(id)?pool.get(id).site:id))));
    }
    const points=[];
    if(hasCoords(c)) points.push(Object.assign({label:'S',name:c.name},project(c)));
    selected.forEach((j,i)=>{if(hasCoords(j)) points.push(Object.assign({label:String(i+1),name:j.site,id:j.job_id},project(j)));});
    if(!points.length) { map.append(svg('text',{x:30,y:180},'ยังไม่มีพิกัดสำหรับแสดงผัง')); return; }
    const xs=points.map(p=>p.x),ys=points.map(p=>p.y),minX=Math.min(...xs),minY=Math.min(...ys),dx=Math.max(.1,Math.max(...xs)-minX),dy=Math.max(.1,Math.max(...ys)-minY);
    points.forEach(p=>{p.px=45+(p.x-minX)/dx*510;p.py=355-(p.y-minY)/dy*310;});
    // Dashed lines are only waypoint order, never represented as driving roads.
    if(valid && points.length>1) map.append(svg('polyline',{points:points.map(p=>p.px+','+p.py).join(' '),fill:'none',stroke:'#6485a0','stroke-width':3,'stroke-dasharray':'7 7'}));
    points.forEach(p=>{
      const group=svg(p.id?'a':'g',p.id?{href:'/field-service/jobs/'+p.id,'aria-label':p.label+' '+p.name}:{});
      group.append(svg('title',{},p.label+' '+p.name),svg('circle',{cx:p.px,cy:p.py,r:20}),svg('text',{x:p.px,y:p.py+5,'text-anchor':'middle',class:'pin-label'},p.label));map.append(group);
    });
  }
  byId('fsl-add-stop').addEventListener('click',()=>{const id=byId('fsl-candidate').value;if(id && !order.includes(id)){order.push(id);dirty();}});
  ['depart','work_end','end'].forEach(name=>form.elements[name].addEventListener('change',dirty));
  form.addEventListener('submit',()=>{byId('fsl-order').value=JSON.stringify(order);});render();
})();
