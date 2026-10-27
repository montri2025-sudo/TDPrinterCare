/* Original office-simulator overlay. The illustration is scenery, never a source of operational data. */
(function (root) {
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const rooms=[
    {x:230,y:400,wx:310,wy:547,name:'รับเครื่อง',accent:'#407ea0'},
    {x:210,y:125,wx:292,wy:318,name:'ตรวจวิเคราะห์',accent:'#8161aa'},
    {x:585,y:532,wx:740,wy:646,name:'รออะไหล่',accent:'#b27c25'},
    {x:585,y:125,wx:587,wy:346,name:'ซ่อมเครื่อง',accent:'#2f8772'},
    {x:995,y:183,wx:1030,wy:370,name:'ทดสอบคุณภาพ',accent:'#38849d'},
    {x:995,y:455,wx:1030,wy:620,name:'พร้อมส่งมอบ',accent:'#6d78ad'}
  ];
  function metrics(tickets){return {jobs:tickets.length,technicians:new Set(tickets.filter(t=>t.assigned_tech_id!=null).map(t=>String(t.assigned_tech_id))).size,waiting:tickets.filter(t=>t.status==='Waiting for Parts').length,dispatch:tickets.filter(t=>t.status==='Resolved/Closed'&&t.handover_status==='pending').length};}
  function render(svg,config){
    const {tickets,statuses,labels,stage,zoom,readOnly,onStage,onTicket}=config;
    svg.replaceChildren();
    function node(tag,attrs,parent,content){const n=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,String(v)));if(content!=null)n.textContent=String(content);if(parent)parent.appendChild(n);return n;}
    function text(g,x,y,t,size=12,color='#34463f',weight=600){return node('text',{x,y,fill:color,'font-size':size,'font-weight':weight,'text-anchor':'middle'},g,t);}
    function rect(g,x,y,w,h,fill,rx=0,attrs={}){return node('rect',{x,y,width:w,height:h,fill,rx,...attrs},g);}
    function action(g,name,fn,cls){g.setAttribute('role','button');g.setAttribute('tabindex','0');g.setAttribute('aria-label',name);g.setAttribute('class',cls);g.addEventListener('click',fn);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();fn();}});}
    function worker(g,x,y,t,color,variant){
      const wrap=node('g',{'aria-hidden':'true',transform:`translate(${x},${y})`},g);
      node('ellipse',{cx:0,cy:2,rx:18,ry:6,fill:'#594936',opacity:.25},wrap);
      const body=node('g',{class:'service-worker',style:'animation-delay:-'+variant+'s'},wrap);
      // Original pixel character with cap, face, overalls and animated work gesture.
      const pixel=(px,py,w,h,c)=>rect(body,px,py,w,h,c);
      pixel(-10,-22,8,20,'#32423f');pixel(3,-22,8,20,'#32423f');
      pixel(-12,-4,11,6,'#24302d');pixel(2,-4,12,6,'#24302d');
      pixel(-14,-49,28,29,color);pixel(-10,-44,20,17,'#e7e2c8');pixel(-7,-44,4,23,color);pixel(4,-44,4,23,color);
      const arms=node('g',{class:'service-worker-arm'},body);rect(arms,-20,-43,7,19,color);rect(arms,14,-43,7,19,color);rect(arms,-20,-25,7,7,'#e2b38d');rect(arms,14,-25,7,7,'#e2b38d');
      pixel(-12,-71,24,23,'#e2b38d');pixel(-14,-75,28,11,'#413c35');pixel(-14,-66,5,10,'#413c35');pixel(9,-66,5,10,'#413c35');
      pixel(-7,-60,3,3,'#303b36');pixel(5,-60,3,3,'#303b36');pixel(-3,-53,7,2,'#ad745c');pixel(-14,-77,29,7,color);pixel(-5,-71,23,4,color);
      const name=String(t.tech_name||'ช่างที่รับผิดชอบ');rect(wrap,-57,13,114,25,'#fffdf5',10,{stroke:color,'stroke-width':1.2});text(wrap,0,30,name.length>16?name.slice(0,15)+'…':name,11,color,700);
    }
    node('title',{},svg,'สำนักงานบริการ · คลิกป้ายห้องหรือเลขงานเพื่อเปิดข้อมูลจริง');
    node('desc',{},svg,'เฟอร์นิเจอร์และเครื่องในภาพเป็นฉากประกอบ ป้ายเลขงานและชื่อช่างเท่านั้นที่อ้างอิงข้อมูลจริง ตัวละครไม่ใช่ตำแหน่งที่ตรวจจับจริง');
    rect(svg,0,0,1200,900,'#f7f1e5',0,{class:'studio-backdrop'});
    const g=node('g',{transform:`translate(${600*(1-zoom)},${400*(1-zoom)}) scale(${zoom})`},svg);
    node('image',{href:'/static/office-assets/service-studio.webp',x:0,y:0,width:1200,height:800,preserveAspectRatio:'xMidYMid meet','aria-hidden':'true'},g);
    rooms.forEach((r,i)=>{
      const jobs=tickets.filter(t=>t.status===statuses[i]);
      const rg=node('g',{opacity:!stage||stage===statuses[i]?1:.3},g);
      if(stage===statuses[i])node('ellipse',{cx:r.wx,cy:r.wy+3,rx:82,ry:29,fill:r.accent,'fill-opacity':.2,stroke:r.accent,'stroke-width':2,'stroke-dasharray':'5 5'},rg);
      const card=node('g',{},rg);action(card,r.name+' '+jobs.length+' งาน',()=>onStage(stage===statuses[i]?'':statuses[i]),'scene-room studio-zone'+(stage===statuses[i]?' selected':''));card.setAttribute('aria-pressed',String(stage===statuses[i]));
      rect(card,r.x-100,r.y-30,200,61,'#fffdf7',14,{stroke:r.accent,'stroke-width':stage===statuses[i]?3:1.4,'fill-opacity':.96});
      rect(card,r.x-89,r.y-18,32,32,r.accent,10);text(card,r.x-73,r.y+4,String(i+1).padStart(2,'0'),13,'#ffffff',800);
      text(card,r.x+15,r.y-5,r.name,15,r.accent,800);text(card,r.x+15,r.y+16,jobs.length+' งาน'+(jobs.length?' · คลิกดูรายการ':' · พร้อมรับงาน'),10,'#626b5e');
      if(!jobs.length){const n=text(rg,r.x,r.y+48,'ยังไม่มีงานในห้องนี้',10,'#4f5b4d');n.setAttribute('class','studio-empty-label');}
      jobs.slice(0,4).forEach((t,j)=>{
        const b=node('g',{},rg);action(b,'เปิดงาน #'+t.ticket_id+' '+t.model,()=>onTicket(t,b),'scene-machine service-machine studio-job');
        node('title',{},b,'#'+t.ticket_id+' · '+t.model+' · '+labels[t.status]);
        const x=r.x-87+(j%2)*90,y=r.y+39+Math.floor(j/2)*29;
        rect(b,x,y,84,25,'#fffdf7',8,{stroke:r.accent,'stroke-width':1.2});node('circle',{cx:x+11,cy:y+12.5,r:3,fill:r.accent,class:t.status==='Waiting for Parts'?'service-alert':''},b);text(b,x+47,y+17,'#'+t.ticket_id,11,r.accent,800);
      });
      const assigned=[...new Map(jobs.filter(t=>t.assigned_tech_id!=null).map(t=>[String(t.assigned_tech_id),t])).values()];
      assigned.slice(0,2).forEach((t,j)=>worker(rg,r.wx+j*74,r.wy+j*40,t,r.accent,i+j));
      if(jobs.length>4)text(rg,r.x,r.y+112,'+'+(jobs.length-4)+' งาน · ดูทั้งหมดในห้อง',11,r.accent,700);
    });
    const m=metrics(tickets);const hud=node('g',{'aria-label':'จอมอนิเตอร์สรุปงานในตัวกรอง'},svg);
    rect(hud,22,806,1156,77,'#fffdf7',16,{stroke:'#dacdb8',class:'studio-monitor'});
    text(hud,146,837,readOnly?'YOUR SERVICE DESK':'SERVICE STUDIO',13,'#49765f',800);text(hud,146,860,'ข้อมูล ณ เวลาเปิดหน้า',10,'#72776b');
    [['งานทั้งหมด',m.jobs],['ช่างผู้รับผิดชอบ',m.technicians],['รออะไหล่',m.waiting],['รอส่งมอบ',m.dispatch]].forEach(([name,n],i)=>{text(hud,395+i*208,838,n,24,'#365f4e',800);text(hud,395+i*208,864,name,11,'#5c6659');});
  }
  const api={render,metrics};if(typeof module==='object'&&module.exports)module.exports=api;else root.ServiceOfficeScene=api;
})(typeof window!=='undefined'?window:globalThis);
