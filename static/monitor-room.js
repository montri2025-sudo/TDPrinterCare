/* Static-on-demand SVG monitors. Reuses existing scoped dashboard aggregates. */
(function () {
  'use strict';
  const source = document.getElementById('monitor-room-data');
  if (!source) return;
  const data = JSON.parse(source.textContent);
  const colors = ['#55d9bd','#66b9f2','#b49cf0','#edb866','#e786a5','#94c9c7'];
  const number = n => Number.isFinite(Number(n)) ? Number(n) : 0;
  const fmt = n => number(n).toLocaleString('th-TH',{maximumFractionDigits:1});
  function node(tag,parent,text,className) {
    const item=document.createElement(tag);
    if(text!=null)item.textContent=String(text);
    if(className)item.className=className;
    if(parent)parent.appendChild(item);
    return item;
  }
  function svgNode(tag,attrs,parent,text) {
    const item=document.createElementNS('http://www.w3.org/2000/svg',tag);
    Object.entries(attrs).forEach(([key,value])=>item.setAttribute(key,String(value)));
    if(text!=null)item.textContent=String(text);
    parent.appendChild(item);return item;
  }
  function svg(parent,label,height=160) {
    const item=svgNode('svg',{viewBox:'0 0 360 '+height,role:'img','aria-label':label},parent);
    svgNode('title',{},item,label);return item;
  }
  function legend(parent,series) {
    const wrap=node('span',parent,null,'monitor-legend');
    series.forEach((entry,index)=>{const item=node('span',wrap);const dot=node('i',item);dot.style.background=colors[index%colors.length];node('span',item,entry.label);});
  }
  function lineChart(parent,series,labels,unit) {
    const chart=svg(parent,'แนวโน้ม '+series.map(s=>s.label).join(' / ')+' หน่วย '+unit,175);
    const values=series.flatMap(s=>s.values.map(number));
    const high=Math.max(1,...values),low=Math.min(0,...values);
    const x=index=>40+index*300/Math.max(labels.length-1,1);
    const y=value=>130-(number(value)-low)/(high-low)*105;
    for(let i=0;i<=3;i++) {
      const level=low+(high-low)*i/3;
      svgNode('line',{x1:40,y1:y(level),x2:340,y2:y(level),stroke:'#274457','stroke-width':1},chart);
      svgNode('text',{x:34,y:y(level)+3,'text-anchor':'end',fill:'#7195ac','font-size':8},chart,Math.abs(level)>=1000?fmt(level/1000)+'k':fmt(level));
    }
    series.forEach((entry,index)=>{
      const points=entry.values.map((v,i)=>x(i)+','+y(v)).join(' ');
      svgNode('polyline',{points,fill:'none',stroke:colors[index%colors.length],'stroke-width':2.5,'stroke-linejoin':'round'},chart);
      entry.values.forEach((v,i)=>svgNode('circle',{cx:x(i),cy:y(v),r:2.5,fill:colors[index%colors.length]},chart));
    });
    labels.forEach((label,index)=>svgNode('text',{x:x(index),y:150,'text-anchor':'middle',fill:'#88a7b8','font-size':8},chart,String(label)));
    if(!values.some(v=>v!==0))svgNode('text',{x:190,y:80,'text-anchor':'middle',fill:'#a7bdc9','font-size':11},chart,'ยังไม่มีค่ามากกว่าศูนย์ในช่วงนี้');
    legend(parent,series);
  }
  function bars(parent,entries,unit,expanded) {
    const shown=entries.slice(0,expanded?12:5);
    const chart=svg(parent,'เปรียบเทียบ '+unit,Math.max(145,shown.length*27+18));
    const maximum=Math.max(1,...shown.map(e=>number(e.value)));
    shown.forEach((entry,index)=>{
      const y=15+index*27;
      svgNode('text',{x:0,y:y+7,fill:'#9fb9c9','font-size':10},chart,String(entry.label).slice(0,expanded?25:18));
      svgNode('rect',{x:140,y:y-3,width:175,height:12,rx:3,fill:'#1d3d51'},chart);
      svgNode('rect',{x:140,y:y-3,width:number(entry.value)/maximum*175,height:12,rx:3,fill:colors[index%colors.length]},chart);
      svgNode('text',{x:354,y:y+7,fill:'#d3e8f1','font-size':10,'text-anchor':'end'},chart,fmt(entry.value));
    });
    if(!shown.length)svgNode('text',{x:180,y:70,'text-anchor':'middle',fill:'#8caabb','font-size':12},chart,'ยังไม่มีข้อมูล');
  }
  const statusEntries=data.statusLabels.map((label,index)=>({label,value:number(data.statusCounts[index])}));
  const total=statusEntries.reduce((sum,e)=>sum+e.value,0);
  const closed=number(data.statusCounts[data.statusCounts.length-1]);
  const panels={
    jobs:{title:'งานเข้าเทียบงานปิด',period:'แนวโน้มรายเดือน · หน่วย: งาน',headers:['เดือน','งานเข้า','งานปิด'],
      rows:data.months.map((month,i)=>[month,number(data.created[i]),number(data.closed[i])]),
      render:parent=>lineChart(parent,[{label:'งานเข้า',values:data.created},{label:'งานปิด',values:data.closed}],data.months,'งาน')},
    status:{title:'สัดส่วนสถานะงาน',period:'ตั๋วที่รับระหว่าง '+data.from+' ถึง '+data.to+' · หน่วย: งาน',headers:['สถานะ','งาน'],rows:statusEntries.map(e=>[e.label,e.value]),
      render:parent=>{
        const chart=svg(parent,'สัดส่วนสถานะงานทั้งหมด '+total+' งาน',175);
        const radius=53,circ=2*Math.PI*radius;let offset=0;
        svgNode('circle',{cx:92,cy:84,r:radius,fill:'none',stroke:'#203e51','stroke-width':15},chart);
        statusEntries.forEach((entry,index)=>{
          if(total>0&&entry.value>0){const length=entry.value/total*circ;svgNode('circle',{cx:92,cy:84,r:radius,fill:'none',stroke:colors[index],'stroke-width':15,'stroke-dasharray':length+' '+(circ-length),'stroke-dashoffset':-offset,transform:'rotate(-90 92 84)'},chart);offset+=length;}
          svgNode('circle',{cx:180,cy:20+index*25,r:3,fill:colors[index]},chart);
          svgNode('text',{x:190,y:24+index*25,fill:'#9eb9c9','font-size':10},chart,entry.label);
          svgNode('text',{x:350,y:24+index*25,fill:'#d4e8ef','text-anchor':'end','font-size':11},chart,entry.value);
        });
        svgNode('text',{x:92,y:87,'text-anchor':'middle',fill:'#dceef4','font-size':29,'font-weight':650},chart,total);
        svgNode('text',{x:92,y:107,'text-anchor':'middle',fill:'#8bafbf','font-size':10},chart,total?'งานในช่วงวัน':'ยังไม่มีงาน');
      }},
    workload:{title:'ภาระงานของทีมช่าง',period:'ตั๋วที่ยังไม่ปิดในปัจจุบัน · หน่วย: งาน · แสดงกราฟสูงสุด 12 คน ตัวเลขทั้งหมดอยู่ในตาราง',headers:['ช่าง','งานค้าง'],
      rows:data.workload.map(w=>[w.name,number(w.count)]),render:(parent,expanded)=>bars(parent,data.workload.map(w=>({label:w.name,value:w.count})).sort((a,b)=>b.value-a.value),'งาน',expanded)},
    revenue:{title:'ยอดขายแยกกลุ่มสินค้า',period:'แนวโน้มรายเดือน · หน่วย: บาท · FDM / Resin / วัสดุพิมพ์',headers:['เดือน','FDM (บาท)','Resin (บาท)','วัสดุพิมพ์ (บาท)'],
      rows:data.months.map((month,i)=>[month,number(data.fdm[i]),number(data.resin[i]),number(data.materials[i])]),
      render:parent=>lineChart(parent,[{label:'FDM',values:data.fdm},{label:'Resin',values:data.resin},{label:'วัสดุพิมพ์',values:data.materials}],data.months,'บาท')},
    repair:{title:'ประสิทธิภาพงานซ่อม',period:'ตั๋วที่รับระหว่าง '+data.from+' ถึง '+data.to+' · สัดส่วนปิดงานเป็นของชุดงานนี้ ไม่ใช่ SLA',headers:['ตัวชี้วัด','ค่า','หน่วย'],
      rows:[['ระยะเวลาซ่อมเฉลี่ย',data.averageDays==null?'ยังไม่มีข้อมูล':data.averageDays,'วัน'],['งานปิดในชุดที่เลือก',closed,'งาน'],['งานทั้งหมดในชุดที่เลือก',total,'งาน'],['สัดส่วนงานปิด',total?Math.round(closed/total*1000)/10:'ยังไม่มีข้อมูล','%']],
      render:parent=>{
        const metric=node('span',parent,null,'monitor-kpi');node('strong',metric,data.averageDays==null?'—':fmt(data.averageDays));node('span',metric,'วัน · ระยะเวลาซ่อมเฉลี่ย');
        const progress=node('span',parent,null,'monitor-progress');const fill=node('i',progress);fill.style.width=(total?closed/total*100:0)+'%';
        node('span',parent,total?'ปิดงาน '+closed+' / '+total+' งาน · '+fmt(closed/total*100)+'%':'ยังไม่มีงานในช่วงวันที่เลือก','monitor-kpi-caption');
      }},
    attention:{title:'รายการที่ต้องติดตาม',period:'ยังไม่มอบหมาย: ชุดงานตามช่วงวัน · การชำระเงิน / สต็อก / นัดหมาย: ปัจจุบัน',headers:['รายการ','จำนวน','ขอบเขต'],
      rows:[['ยังไม่มอบหมายช่าง',data.unassigned,'งานตามช่วงวันที่'],['รอตรวจการชำระเงิน',data.pendingPayments,'รายการปัจจุบัน'],['รายการสต็อกถึงจุดสั่งซื้อ',data.lowStock,'รายการปัจจุบัน'],['นัดหมายวันนี้',data.todayBookings,'งานวันนี้']],
      render:(parent,expanded)=>bars(parent,[{label:'ยังไม่มอบหมาย',value:data.unassigned},{label:'รอตรวจชำระ',value:data.pendingPayments},{label:'สต็อกถึงจุดสั่งซื้อ',value:data.lowStock},{label:'นัดหมายวันนี้',value:data.todayBookings}],'รายการ / งาน',expanded)}
  };
  Object.entries(panels).forEach(([key,panel])=>panel.render(document.getElementById('monitor-chart-'+key),false));
  const dialog=document.getElementById('monitor-dialog');let opener=null;
  function openMonitor(button) {
    const panel=panels[button.dataset.monitor];if(!panel)return;
    opener=button;
    document.getElementById('monitor-detail-title').textContent=panel.title;
    document.getElementById('monitor-detail-context').textContent=data.scope+' · '+panel.period;
    const chart=document.getElementById('monitor-detail-chart');chart.replaceChildren();panel.render(chart,true);
    const table=document.getElementById('monitor-detail-table');table.replaceChildren();
    const head=node('thead',table);const row=node('tr',head);panel.headers.forEach(label=>{const cell=node('th',row,label);cell.scope='col';});
    const body=node('tbody',table);panel.rows.forEach(values=>{const tr=node('tr',body);values.forEach(value=>node('td',tr,typeof value==='number'?fmt(value):value));});
    dialog.showModal();
  }
  document.querySelectorAll('[data-monitor]').forEach(button=>button.addEventListener('click',()=>openMonitor(button)));
  document.getElementById('monitor-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(opener)opener.focus();});
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  document.getElementById('monitor-reports').addEventListener('toggle',event=>{if(event.target.open)window.dispatchEvent(new Event('resize'));});
})();
