/* Pure, bounded scene planning. No network, storage or writes. */
(function(root){
  'use strict';
  const stations=[{x:-8,z:4,name:'รับเครื่อง',color:'#5596ba'},{x:-8,z:-4,name:'ตรวจวิเคราะห์',color:'#9382c6'},{x:0,z:4,name:'รออะไหล่',color:'#c49b52'},{x:0,z:-4,name:'ซ่อมเครื่อง',color:'#4d9b86'},{x:8,z:-4,name:'ทดสอบคุณภาพ',color:'#5d9fb2'},{x:8,z:4,name:'พร้อมส่งมอบ',color:'#888dbc'}];
  function plan(tickets,statuses){
    const rooms=stations.map((s,i)=>({...s,index:i,status:statuses[i],jobs:tickets.filter(t=>t.status===statuses[i])}));
    const people=new Map();
    tickets.forEach(t=>{const index=statuses.indexOf(t.status);if(index<0||t.assigned_tech_id==null)return;const id=String(t.assigned_tech_id);if(!people.has(id))people.set(id,{id,name:t.tech_name||'ช่างที่รับผิดชอบ',jobs:[],stops:[]});const w=people.get(id);w.jobs.push(t);if(!w.stops.includes(index))w.stops.push(index);});
    return {rooms,workers:[...people.values()].slice(0,12),jobs:tickets.length,technicians:people.size,waiting:rooms[2].jobs.length,dispatch:rooms[5].jobs.filter(t=>t.handover_status==='pending').length};
  }
  function workpoint(index,offset=0){const s=stations[index];return {x:s.x+offset,z:s.z<0?-2:2};}
  // All inter-desk movement goes through the open center aisle, never through workbenches.
  function route(from,to){return [{x:from.x,z:0},{x:to.x,z:0},{x:to.x,z:to.z}].filter((p,i,a)=>i===0||p.x!==a[i-1].x||p.z!==a[i-1].z);}
  function move(position,path,distance){let p={...position},next=path.map(v=>({...v}));distance=Math.max(0,Number.isFinite(distance)?distance:0);while(next.length&&distance>0){const target=next[0],dx=target.x-p.x,dz=target.z-p.z,len=Math.hypot(dx,dz);if(len<=distance){p={...target};next.shift();distance-=len;}else{p={x:p.x+dx/len*distance,z:p.z+dz/len*distance};distance=0;}}return {position:p,path:next};}
  const api={stations,plan,workpoint,route,move};if(typeof module==='object'&&module.exports)module.exports=api;else root.Office3DCore=api;
})(typeof window!=='undefined'?window:globalThis);
