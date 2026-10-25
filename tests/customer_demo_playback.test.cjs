const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('static/customer-demo.js','utf8');
const texts=[...source.matchAll(/step\('[^']*','[^']*','([^']*)'\)/g)].map(m=>m[1]);
function setup(path='/customer/dashboard',rejectAudio=false){
 const nodes=new Map(),events={},pending=new Map(),storage=new Map(),audios=[],navigations=[];let seq=0;
 function node(id){if(!nodes.has(id))nodes.set(id,{hidden:true,checked:false,textContent:'',classList:{add(){},remove(){}},getClientRects:()=>[{}],scrollIntoView(){},focus(){},addEventListener(name,fn){this[name]=fn;}});return nodes.get(id);}
 const context={location:{pathname:path,assign:p=>navigations.push(p)},document:{hidden:false,getElementById:id=>node(id),querySelectorAll:()=>[node('target')],querySelector:()=>null,addEventListener:(name,fn)=>events[name]=fn},window:{matchMedia:()=>({matches:true}),addEventListener(){}},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},fetch:async()=>({ok:true,json:async()=>Object.fromEntries(texts.map(t=>[t,'0123456789abcdef.mp3']))}),Audio:class{constructor(){audios.push(this);}play(){return rejectAudio?Promise.reject(Error('blocked')):Promise.resolve();}pause(){this.stopped=true;}},setTimeout:(fn,ms)=>{pending.set(++seq,{fn,ms});return seq;},clearTimeout:id=>pending.delete(id)};
 vm.runInNewContext(source,context);
 return {node,events,pending,audios,navigations,context,flush:()=>new Promise(resolve=>setImmediate(resolve)),tick(){const next=[...pending].sort((a,b)=>a[1].ms-b[1].ms)[0];assert.ok(next,'timer exists');pending.delete(next[0]);next[1].fn();}};
}
test('recorded narration advances only after ended; pause and close cancel stale events',async()=>{
 const env=setup();env.node('customer-demo-all').checked=true;env.node('customer-demo-start').click();await env.flush();
 assert.equal(env.audios.length,1);assert.match(env.node('customer-demo-step').textContent,/1 \/ 5/);
 const oldEnd=env.audios[0].onended;env.node('customer-demo-pause').click();oldEnd();assert.equal(env.pending.size,0);
 env.node('customer-demo-pause').click();await env.flush();env.audios.at(-1).onended();env.tick();await env.flush();assert.match(env.node('customer-demo-step').textContent,/2 \/ 5/);
 env.node('customer-demo-close').click();assert.equal(env.pending.size,0);assert.equal(env.node('customer-demo-tour').hidden,true);
});
test('muted tour continues across menus without submitting forms',async()=>{
 const env=setup();env.node('customer-demo-all').checked=true;env.node('customer-demo-mute').checked=true;env.node('customer-demo-mute').change();env.node('customer-demo-start').click();await env.flush();
 for(let i=0;i<5;i++){env.tick();await env.flush();}assert.deepEqual(env.navigations,['/customer/office']);assert.equal(env.audios.length,0);
});
test('autoplay rejection exposes resume; background tab pauses progression',async()=>{
 const env=setup('/customer/dashboard',true);env.node('customer-demo-start').click();await env.flush();assert.equal(env.node('customer-demo-pause').textContent,'เล่นต่อ');assert.equal(env.pending.size,0);
 env.context.document.hidden=true;env.events.visibilitychange();assert.equal(env.pending.size,0);
});
test('guide has no visible demo',()=>{const env=setup('/guide');assert.equal(env.node('customer-demo-bar').hidden,true);});
