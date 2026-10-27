const {test}=require('node:test');
const assert=require('node:assert/strict');
const scene=require('../static/service-office-scene.js');
const statuses=['New','Diagnosing','Waiting for Parts','In Repair','Testing','Resolved/Closed'];
class Element {
  constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.events={};}
  setAttribute(k,v){this.attrs[k]=String(v);}
  appendChild(n){this.children.push(n);}
  replaceChildren(){this.children=[];}
  addEventListener(k,v){this.events[k]=v;}
}
function render(tickets,config={}){
  global.document={createElementNS:(_,tag)=>new Element(tag)};
  const svg=new Element('svg');const opened=[],stages=[];
  scene.render(svg,{tickets,statuses,labels:Object.fromEntries(statuses.map(s=>[s,s])),stage:'',zoom:1,readOnly:false,onTicket:t=>opened.push(t.ticket_id),onStage:s=>stages.push(s),...config});
  const nodes=[];function walk(n){nodes.push(n);n.children.forEach(walk);}walk(svg);
  return{svg,nodes,opened,stages};
}
const ticket=(id,status='In Repair',tech=1)=>({ticket_id:id,status,model:'Printer',assigned_tech_id:tech,tech_name:'Technician',handover_status:'unrecorded'});
test('empty office has six accessible rooms and no fictional machines or workers',()=>{
  const r=render([]);
  assert.equal(r.nodes.filter(n=>n.attrs.role==='button').length,6);
  assert.equal(r.nodes.filter(n=>n.attrs.class==='service-worker').length,0);
  assert.equal(r.nodes.filter(n=>/service-machine/.test(n.attrs.class||'')).length,0);
  assert.ok(r.nodes.some(n=>n.textContent==='ยังไม่มีงานในห้องนี้'));
});
test('room and machine actions use the real selected ticket; keyboard supports Enter and Space',()=>{
  const r=render([ticket(42)]);
  const machine=r.nodes.find(n=>/service-machine/.test(n.attrs.class||''));
  machine.events.keydown({key:'Enter',preventDefault(){},stopPropagation(){}});
  assert.deepEqual(r.opened,[42]);
  const room=r.nodes.find(n=>n.attrs['aria-label']==='ซ่อมเครื่อง 1 งาน');
  room.events.keydown({key:' ',preventDefault(){},stopPropagation(){}});
  assert.deepEqual(r.stages,['In Repair']);
  assert.equal(r.nodes.filter(n=>n.attrs.class==='service-worker').length,1);
});
test('large job sets keep rendering bounded while monitor counts remain complete',()=>{
  const jobs=Array.from({length:1000},(_,i)=>ticket(i,statuses[i%6],i%10));
  const r=render(jobs);
  assert.equal(r.nodes.filter(n=>/service-machine/.test(n.attrs.class||'')).length,24);
  assert.equal(r.nodes.filter(n=>n.attrs.class==='service-worker').length,12);
  assert.ok(r.nodes.length<1500);
  assert.deepEqual(scene.metrics(jobs),{jobs:1000,technicians:10,waiting:167,dispatch:0});
});
test('unassigned jobs do not invent staff; dispatch requires pending handover; text stays literal',()=>{
  const t={...ticket(3,'Resolved/Closed',null),model:'<img onerror=alert(1)>',handover_status:'pending'};
  const r=render([t],{readOnly:true});
  assert.equal(r.nodes.filter(n=>n.attrs.class==='service-worker').length,0);
  assert.deepEqual(scene.metrics([t]),{jobs:1,technicians:0,waiting:0,dispatch:1});
  assert.ok(r.nodes.some(n=>String(n.textContent).includes(t.model)));
  assert.ok(r.nodes.every(n=>!Object.keys(n.attrs).some(k=>/^on/.test(k))));
  assert.ok(r.nodes.some(n=>n.textContent==='YOUR SERVICE DESK'));
});
