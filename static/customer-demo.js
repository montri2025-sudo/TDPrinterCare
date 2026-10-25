/* Read-only customer tours: no form submission or customer records in speech. */
(function(){
'use strict';
const el=id=>document.getElementById('customer-demo-'+id),path=location.pathname;
if(!el('bar')||/^\/guide(?:\/|$)/.test(path))return;
const step=(target,title,text)=>({target,title,text});
let steps=[];
if(path==='/customer/dashboard')steps=[
step('#factory-counts','จำนวนเครื่องแต่ละประเภท','การ์ดแสดงจำนวนเครื่องที่ลงทะเบียนในบัญชีของคุณ แยกเอฟดีเอ็ม เรซิน เครื่องล้างและอบ และอุปกรณ์อื่น คลิกประเภทเพื่อกรองรายการ'),
step('#factory-floor','เดินชมโรงงานของคุณ','แต่ละห้องรวมเครื่องตามประเภท คลิกเครื่องเพื่อดูหมายเลข ชั่วโมงใช้งาน งานซ่อม และรายการดูแล ห้องเป็นภาพแทนข้อมูลในระบบ'),
step('#factory-legend','สีสถานะเครื่อง','สีเขียวคือพร้อมตามบันทึก สีฟ้าคือมีงานซ่อม สีส้มกะพริบช้าคือถึงรอบบำรุงรักษา สีเทาคือเลิกใช้หรือขายต่อ ใช้ปุ่มหยุดไฟกะพริบได้'),
step('#factory-maintenance','เครื่องที่ถึงรอบดูแล','ด้านข้างรวมเครื่องที่ถึงรอบบำรุงรักษา แม้มีงานซ่อมอยู่ด้วย คลิกเครื่องเพื่ออ่านรายละเอียด'),
step('#factory-actions','เลือกทำงานต่อ','เปิดเวอร์ชวลออฟฟิศเพื่อติดตามงานซ่อม หรือเลือกบำรุงรักษา แจ้งซ่อม และเพิ่มเครื่องได้จากเมนูนี้')];
else if(path==='/customer/office')steps=[
step('#office-title','Virtual Office ของฉัน','ห้องแสดงขั้นตอนงานซ่อมของเครื่องในบัญชีของคุณ ข้อมูลเป็นสถานะที่เจ้าหน้าที่บันทึก'),
step('#office-scene, #office-floor','ติดตามเครื่องตามห้อง','เลือกห้องหรือขั้นตอนเพื่อกรองงาน เลือกเครื่องหรือการ์ดงานเพื่ออ่านรายละเอียดและประวัติ'),
step('#office-refresh','อัปเดตงานล่าสุด','กดอัปเดตข้อมูลเมื่อต้องการโหลดสถานะล่าสุด หน้านี้ใช้ติดตามงานของคุณ')];
else if(path==='/customer/maintenance')steps=[
step('.main-area .grid','ภาพรวมการบำรุงรักษา','ดูจำนวนเครื่องที่พร้อมใช้งาน ถึงรอบดูแล และกำลังซ่อมจากสรุปด้านบน'),
step('.main-area .grid + .grid, .main-area .card','ตรวจรายการดูแล','การ์ดเครื่องแสดงหมายเลข ชั่วโมงสะสม และงานที่ถึงรอบ ตรวจรายละเอียดก่อนเริ่มดูแล'),
step('a[href$="/maintenance/log"]','บันทึกหลังทำงานจริง','ใช้บันทึกบำรุงรักษาหลังดูแลเครื่องเสร็จแล้ว เปิดประวัติเพื่อตรวจงานที่ผ่านมา หรือเริ่มงานพิมพ์เพื่อบันทึกการใช้งาน Demo ไม่บันทึกแทนคุณ')];
else if(path==='/customer/tickets')steps=[
step('.main-area h1','ตั๋วซ่อมของฉัน','หน้านี้รวบรวมงานซ่อมที่เกี่ยวข้องกับบัญชีของคุณ'),
step('.main-area table','เลือกงานที่ต้องการติดตาม','ตรวจหมายเลขตั๋ว เครื่อง และสถานะ แล้วคลิกงานเพื่อดูรายละเอียด หากยังไม่มีงานให้ใช้เมนูแจ้งซ่อมใหม่')];
else if(path==='/customer/new')steps=[
step('#branch-map, #branch-list','เลือกสาขารับบริการ','เลือกสาขาบนแผนที่หรือรายการสาขา ปุ่มค้นหาสาขาใกล้คุณจะใช้ตำแหน่งเมื่อคุณเลือกและอนุญาตเท่านั้น'),
step('select[name="device_sn"]','เลือกเครื่องและเวลาบริการ','เลือกเครื่องที่ต้องการแจ้งซ่อม เครื่องที่มีตั๋วค้างจะเลือกซ้ำไม่ได้ เลือกแจ้งทันทีหรือจองวันและเวลา'),
step('textarea[name="description"]','อธิบายปัญหา','เลือกประเภทปัญหาและบรรยายอาการ แนบรูปหรือวิดีโอตามข้อจำกัดที่แสดง'),
step('.main-area form button[type="submit"]','ตรวจสอบก่อนส่ง','ตรวจเครื่อง สาขา อาการ และวันนัดให้ครบ แล้วกดส่งเรื่องด้วยตนเอง Demo จะไม่ส่งคำร้อง')];
else if(path==='/customer/devices/new')steps=[
step('.main-area h1','เครื่องพิมพ์ของฉัน','หน้านี้ใช้ลงทะเบียนเครื่องและดูเครื่องที่มีอยู่ในบัญชี'),
step('.main-area form','กรอกข้อมูลเครื่อง','ระบุหมายเลขเครื่อง รุ่น ประเภท และวันที่ซื้อหรือหมดประกันตามข้อมูลจริง ตรวจหมายเลขเครื่องก่อนบันทึก'),
step('.main-area table','ตรวจเครื่องที่ลงทะเบียน','รายการด้านล่างแสดงเครื่องที่บันทึกแล้ว หากไม่มีเครื่องรายการจะยังว่าง Demo ไม่เพิ่มเครื่องให้เอง')];
else if(/^\/customer\/ticket\/\d+$/.test(path))steps=[
step('.ticket-hero','สถานะตั๋วซ่อม','ดูสถานะปัจจุบันของเครื่องและคำแนะนำขั้นตอนถัดไป'),
step('.main-area h2','รายละเอียดและประวัติ','เลื่อนอ่านภาพแนบ ประวัติการดำเนินงาน ใบเสนอราคา และเอกสารที่มีในตั๋วนี้'),
step('.main-area','การดำเนินการของคุณ','ปุ่มแก้ไข ยกเลิก หรือประเมินจะแสดงตามเงื่อนไขงาน ตรวจรายละเอียดก่อนยืนยันทุกครั้ง Demo ไม่กดปุ่มเหล่านี้แทนคุณ')];
else if(path==='/track')steps=[step('.main-area form','ค้นหาสถานะงานซ่อม','กรอกข้อมูลค้นหาตามช่องที่แสดง แล้วกดค้นหาเพื่อดูสถานะของงาน'),step('.main-area','อ่านผลการค้นหา','ตรวจข้อมูลเครื่องและสถานะที่ระบบแสดง หากไม่พบงานให้ตรวจข้อมูลค้นหาหรือติดต่อสาขาที่รับบริการ')];
else if(path==='/notifications')steps=[step('.main-area','การแจ้งเตือน','ตรวจรายการแจ้งเตือนและเลือกเรื่องที่ต้องการอ่าน เพื่อเปิดรายละเอียดที่เกี่ยวข้อง')];
else if(/^\/device\//.test(path))steps=[step('.main-area','ประวัติและการดูแลเครื่อง','ตรวจหมายเลขเครื่องและข้อมูลการใช้งานก่อนดำเนินการ'),step('.main-area form, .main-area table','บันทึกข้อมูลจริง','หากหน้านี้มีแบบฟอร์ม ให้กรอกเมื่อทำงานจริงเสร็จและตรวจข้อมูลก่อนบันทึก หากเป็นประวัติ ใช้ตรวจรายการที่ผ่านมา Demo ไม่ส่งแบบฟอร์ม')];
if(!steps.length)return;
el('bar').hidden=false;
const menuPaths=['/customer/dashboard','/customer/office','/customer/maintenance','/customer/tickets','/customer/new','/customer/devices/new','/track'];
let index=-1,voice=null,muted=false,paused=false,timer=null,watchdog=null,version=0,audio=null,manifest={};
function stored(key){try{return sessionStorage.getItem(key);}catch(e){return null;}}
function store(key,value){try{sessionStorage.setItem(key,value);}catch(e){}}
muted=stored('customer-demo-muted')==='1';
el('all').checked=stored('customer-demo-all')!=='0';
el('all').addEventListener('change',()=>store('customer-demo-all',el('all').checked?'1':'0'));
const synth=('speechSynthesis' in window&&'SpeechSynthesisUtterance' in window)?window.speechSynthesis:null;
const manifestReady=fetch('/static/customer-demo-voice/manifest.json').then(r=>r.ok?r.json():{}).then(data=>{manifest=data;}).catch(()=>{});
function cancel(){version++;clearTimeout(timer);clearTimeout(watchdog);timer=null;watchdog=null;if(audio){audio.pause();audio.onended=null;audio.onerror=null;audio=null;}if(synth)synth.cancel();}
function voices(){const available=synth?synth.getVoices().filter(v=>/^th(?:-|_)/i.test(v.lang)&&v.localService):[];voice=available.find(v=>/male|ชาย|niwat|pattara/i.test(v.name))||available[0]||null;}
function note(text){el('note').textContent=text;}
function waitTime(text){return Math.max(6000,Math.min(45000,text.length*110));}
function schedule(delay){clearTimeout(timer);timer=setTimeout(()=>{if(index>=0&&!paused&&!document.hidden)advance();},delay);}
function browserVoice(text,token){
if(!voice||!synth){note('เสียงไม่พร้อม ใช้คำบรรยายไทยและเลื่อนต่ออัตโนมัติ');schedule(waitTime(text));return;}
const utterance=new SpeechSynthesisUtterance(text);utterance.voice=voice;utterance.lang='th-TH';utterance.rate=.9;
utterance.onend=()=>{if(token===version){clearTimeout(watchdog);schedule(1000);}};
utterance.onerror=()=>{if(token===version){clearTimeout(watchdog);schedule(waitTime(text));}};
synth.speak(utterance);watchdog=setTimeout(()=>{if(token===version){synth.cancel();schedule(1000);}},Math.max(45000,waitTime(text)*3));
}
async function playStep(){
cancel();if(index<0||paused)return;const token=version,text=steps[index].text;
if(muted){note('ปิดเสียงอยู่ · Demo เลื่อนต่ออัตโนมัติ');schedule(waitTime(text));return;}
await manifestReady;if(token!==version||paused||index<0)return;
const file=manifest[text];
if(file&&/^[a-f0-9]{16}\.mp3$/.test(file)){
audio=new Audio('/static/customer-demo-voice/'+file);audio.preload='auto';
audio.onended=()=>{if(token===version){clearTimeout(watchdog);schedule(1000);}};
audio.onerror=()=>{if(token===version){clearTimeout(watchdog);browserVoice(text,token);}};
try{await audio.play();if(token===version){note('เสียงบรรยายภาษาไทย · เลื่อนต่อเมื่อพูดจบ');watchdog=setTimeout(()=>{if(token===version){cancel();schedule(1000);}},180000);}}
catch(e){if(token===version){paused=true;cancel();el('pause').textContent='เล่นต่อ';note('กดเล่นต่อเพื่ออนุญาตเสียงบรรยาย');}}
}else{note('เสียงภาษาไทย · Demo เลื่อนต่อเมื่อพูดจบ');browserVoice(text,token);}
}
function syncMute(value){muted=value;el('mute').checked=value;el('tour-mute').checked=value;store('customer-demo-muted',value?'1':'0');if(index>=0&&!paused)playStep();}
syncMute(muted);voices();if(synth)synth.addEventListener('voiceschanged',voices);
function clear(){document.querySelectorAll('.customer-demo-target').forEach(n=>n.classList.remove('customer-demo-target'));}
function show(i){index=i;paused=false;el('pause').textContent='พักเล่น';clear();const entry=steps[i];el('tour').hidden=false;el('step').textContent='สาธิต '+(i+1)+' / '+steps.length;el('title').textContent=entry.title;el('text').textContent=entry.text;el('prev').disabled=i===0;el('next').textContent=i===steps.length-1?'จบหน้านี้ / ถัดไป →':'ถัดไป →';const target=[...document.querySelectorAll(entry.target)].find(n=>n.getClientRects().length)||document.querySelector('.main-area h1')||el('bar');target.classList.add('customer-demo-target');target.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});playStep();}
function stop(){index=-1;paused=false;cancel();clear();el('tour').hidden=true;store('customer-demo-resume','');el('start').focus();}
function advance(){if(index<0)return;if(index<steps.length-1){show(index+1);return;}const current=menuPaths.indexOf(path);if(el('all').checked&&current>=0&&current<menuPaths.length-1){cancel();store('customer-demo-resume',menuPaths[current+1]);location.assign(menuPaths[current+1]);}else{stop();note('จบการสาธิตแล้ว กด Demo เพื่อเล่นอีกครั้ง');}}
el('start').addEventListener('click',()=>{voices();show(0);el('next').focus({preventScroll:true});});
el('pause').addEventListener('click',()=>{paused=!paused;el('pause').textContent=paused?'เล่นต่อ':'พักเล่น';if(paused)cancel();else playStep();});
el('next').addEventListener('click',advance);el('prev').addEventListener('click',()=>{if(index>0)show(index-1);});el('close').addEventListener('click',stop);
['mute','tour-mute'].forEach(id=>el(id).addEventListener('change',()=>syncMute(el(id).checked)));
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&index>=0&&!document.querySelector('dialog[open]'))stop();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&index>=0){paused=true;cancel();el('pause').textContent='เล่นต่อ';}});window.addEventListener('pagehide',cancel);
if(stored('customer-demo-resume')===path){store('customer-demo-resume','');show(0);}
})();
