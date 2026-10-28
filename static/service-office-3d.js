import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';

/* Original procedural 3D room. It only consumes the host page's authorized snapshot. */
export function createOffice3D(host, hooks) {
  const Core=window.Office3DCore;
  if(!Core)throw new Error('scene planner unavailable');
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
  const canvas=renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label','สำนักงาน 3D ลากเพื่อหมุน ใช้สองนิ้วซูม หรือใช้ปุ่มลูกศรและเครื่องหมายบวกลบ');
  canvas.dataset.sceneReady='true';
  const overlay=document.createElement('div');overlay.className='office-3d-labels';
  const metrics=document.createElement('div');metrics.className='office-3d-metrics';metrics.setAttribute('aria-label','สรุปงานในฉาก 3D');
  host.replaceChildren(canvas,overlay,metrics);
  const scene=new THREE.Scene();scene.background=new THREE.Color('#e5e9e6');
  const camera=new THREE.PerspectiveCamera(38,1,.1,150);camera.position.set(29,29,36);
  const controls=new OrbitControls(camera,canvas);controls.target.set(2,1,3);controls.enableDamping=true;controls.dampingFactor=.1;controls.minDistance=18;controls.maxDistance=60;controls.maxPolarAngle=Math.PI*.46;controls.minPolarAngle=.3;
  controls.update();
  scene.add(new THREE.HemisphereLight('#fff9df','#9caaa0',1.6));
  const sun=new THREE.DirectionalLight('#fff0d4',2.2);sun.position.set(-10,22,14);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);sun.shadow.camera.left=-20;sun.shadow.camera.right=20;sun.shadow.camera.top=20;sun.shadow.camera.bottom=-20;sun.shadow.normalBias=.06;scene.add(sun);
  const mats=new Map(),geos=new Map();
  const material=color=>{if(!mats.has(color))mats.set(color,new THREE.MeshStandardMaterial({color,roughness:.82}));return mats.get(color);};
  function geo(kind,args){const key=kind+args.join(',');if(!geos.has(key))geos.set(key,new THREE[kind](...args));return geos.get(key);}
  function mesh(parent,kind,args,color,x,y,z,shadow=true){const m=new THREE.Mesh(geo(kind,args),material(color));m.position.set(x,y,z);m.castShadow=shadow;m.receiveShadow=true;parent.add(m);return m;}
  const box=(p,x,y,z,w,h,d,c,shadow=true)=>mesh(p,'BoxGeometry',[w,h,d],c,x,y,z,shadow);
  const ball=(p,x,y,z,r,c)=>mesh(p,'SphereGeometry',[r,10,8],c,x,y,z);
  const cyl=(p,x,y,z,r,h,c)=>mesh(p,'CylinderGeometry',[r,r,h,10],c,x,y,z);
  // Industrial maker shop: concrete, marked bays, tool walls and heavy workbenches.
  box(scene,0,-.36,0,26.5,.65,18.6,'#384b50');
  box(scene,0,0,0,26,.08,18,'#a6adaa',false);
  for(let x=-12;x<=12;x+=4)box(scene,x,.046,0,.025,.008,18,'#8d9895',false);
  for(let z=-8;z<=8;z+=4)box(scene,0,.046,z,26,.008,.025,'#8d9895',false);
  box(scene,0,2.65,-9.2,26.4,5.4,.25,'#c4ccc8');box(scene,-13.15,2.65,0,.25,5.4,18.6,'#657f7e');
  [-12,-4,4,12].forEach(x=>{box(scene,x,2.65,-8.96,.22,5.3,.3,'#465c60');box(scene,x,5,-8.5,3,.12,.6,'#f1e6c9');});
  box(scene,0,4.7,-8.95,26,.13,.15,'#626e70');
  for(let i=0;i<3;i++){
    const x=-8+i*8;box(scene,x,3.6,-8.96,4.8,1.7,.1,'#394f58');box(scene,x,3.6,-8.88,4.5,1.4,.08,'#a3c5ca');box(scene,x,3.6,-8.8,.08,1.45,.1,'#4b6369');
  }
  // Yellow safety boundaries keep the central walking aisle visibly clear.
  [-1.2,1.2].forEach(z=>box(scene,0,.06,z,25,.018,.08,'#e8ba4b',false));
  for(let x=-11;x<12;x+=2)box(scene,x,.065,0,.7,.018,.08,'#e5d7ad',false);
  function rack(x,z){
    [-.85,.85].forEach(dx=>[-.4,.4].forEach(dz=>box(scene,x+dx,1.6,z+dz,.09,3.2,.09,'#45585c')));
    for(let level=0;level<4;level++){
      const y=.2+level*.85;box(scene,x,y,z,1.9,.12,1,'#b67a3e');
      [-.5,.5].forEach((dx,j)=>{box(scene,x+dx,y+.28,z,.72,.45,.7,j?'#c89c63':'#4e8989');box(scene,x+dx,y+.29,z+.36,.28,.12,.025,'#eee3c9');});
    }
  }
  rack(-11.8,-6.6);rack(-11.8,5.8);rack(11.8,-6.8);
  function pegboard(x,z){
    box(scene,x,2.9,z,3.6,1.5,.12,'#3e555b');
    for(let j=0;j<7;j++){
      const px=x-1.4+j*.46;box(scene,px,2.84,z+.12,.065,.55,.08,'#c9d3ce');
      box(scene,px,2.62,z+.14,.16,.24,.12,j%2?'#df9a43':'#529b96');
      if(j%2===0)box(scene,px,3.16,z+.12,.32,.1,.1,'#b5c4bf');
    }
  }
  Core.stations.forEach((s,i)=>{
    const bay=['#7eaaa8','#99a2b0','#c7ae69','#7aa69a','#7da4b2','#b6a280'][i];
    box(scene,s.x,.065,s.z,6,.025,4.2,bay,false);
    [-3,3].forEach(dx=>box(scene,s.x+dx,.09,s.z,.07,.018,4.2,'#e5bb53',false));
    // Deep steel benches with lower storage rather than classroom desks and chairs.
    box(scene,s.x,1.4,s.z,5.5,.25,2.1,'#856747');box(scene,s.x,1.54,s.z,5.6,.055,2.16,'#c3b18b');
    [-2.45,2.45].forEach(dx=>[-.8,.8].forEach(dz=>box(scene,s.x+dx,.7,s.z+dz,.18,1.4,.18,'#354e54')));
    box(scene,s.x,.35,s.z,5.2,.12,1.8,'#51686b');
    box(scene,s.x+1.95,.88,s.z,1.1,.9,1.65,'#3c696d');
    for(let j=0;j<3;j++){box(scene,s.x+1.95,.6+j*.27,s.z+ .84,1,.035,.025,'#b2c3be');box(scene,s.x+1.95,.71+j*.27,s.z+.88,.34,.045,.05,'#d7d5bc');}
    if(s.z<0)pegboard(s.x,s.z-1.3);
    // Diagnostic screen and task lamp are wall mounted, leaving the bench for repairs.
    box(scene,s.x+2,2.12,s.z-.6,.9,.65,.1,'#253f48');box(scene,s.x+2,2.12,s.z-.54,.76,.5,.025,'#66adac');
    box(scene,s.x+2.45,2,s.z+.5,.055,.9,.055,'#465a60');box(scene,s.x+2.2,2.43,s.z+.5,.6,.1,.25,'#e8b754');
    if(i===2)rack(s.x-2,s.z+.25);
    if(i===5){for(let j=0;j<3;j++){box(scene,s.x-1+j*.8,1.84,s.z,.64,.48,.6,'#bc8d56');box(scene,s.x-1+j*.8,2.085,s.z,.12,.01,.61,'#e7d3a5');}}
    if(i===3){
      const spool=cyl(scene,s.x-2.1,1.91,s.z-.55,.3,.22,'#dca84e');spool.rotation.x=Math.PI/2;
      box(scene,s.x-.7,1.62,s.z+.7,.8,.1,.35,'#435e66');
    }
  });
  // Mobile tool trolley and packing pallet in the front service area.
  box(scene,-8,.8,7,1.8,1.2,.9,'#a45d44');box(scene,-8,1.46,7,1.95,.12,1,'#354e54');
  for(let j=0;j<3;j++)box(scene,-8,.45+j*.35,7.47,1.5,.04,.06,'#d8c5a0');
  [-.65,.65].forEach(dx=>[-.32,.32].forEach(dz=>ball(scene,-8+dx,.15,7+dz,.15,'#263d43')));
  for(let j=0;j<5;j++)box(scene,8+j*.45,.14,7,.35,.22,2,'#92744e');
  [[8.3,7],[9.2,7.3],[8.7,6.5]].forEach(([x,z])=>{box(scene,x,.65,z,.8,.8,.7,'#bb905c');box(scene,x,1.06,z,.13,.02,.72,'#e2c58e');});
  // Customer-facing extension and exterior loading lane (scenery, not live headcounts).
  box(scene,0,-.2,12,26,.4,6,'#7e8f88');box(scene,0,.02,12,26,.06,6,'#d0c4a8');
  box(scene,17,-.17,2.5,7,.4,25,'#4c5a60');
  for(let z=-8;z<15;z+=3)box(scene,17,.045,z,.12,.025,1.5,'#eee2ad',false);
  box(scene,13.3,.03,5,1,.18,17,'#afb5aa');
  for(let j=0;j<5;j++)box(scene,14.2,.065,5+j*.42,1.5,.025,.22,'#e4c160',false);
  // Reception counter, computer and intake tray.
  box(scene,-8, .8,11,6,1.6,1.3,'#315e62');box(scene,-8,1.66,11,6.2,.16,1.5,'#c8ad7f');
  box(scene,-9,2.1,10.8,1,.7,.12,'#243e49');box(scene,-9,2.1,10.88,.85,.54,.03,'#78b7af');
  box(scene,-6,1.82,11,.8,.14,.55,'#e3d6b6');
  // Open customer lounge, low glass partitions and a viewing screen.
  box(scene,1,.075,12,9,.04,5,'#91aaa0');
  [-3.5,5.5].forEach(x=>{box(scene,x,1.1,12,.12,2.1,5,'#a7c7c1');box(scene,x,2.2,12,.18,.1,5,'#42666a');});
  box(scene,1,1.1,14,4.6,.45,1,'#527d75');box(scene,1,1.65,14.45,4.6,1,.18,'#527d75');
  box(scene,1,.72,12.6,2,.14,1,'#bb9b6e');box(scene,1,.36,12.6,.18,.7,.6,'#405d61');
  box(scene,1,2.6,9.6,2.7,1.5,.12,'#244651');box(scene,1,2.6,9.68,2.4,1.2,.03,'#64a79f');
  for(let j=0;j<3;j++)box(scene,.2+j*.65,2.45,9.71,.38,.2+j*.18,.03,'#cee2bc');
  // Loading door, ramp and delivery truck beside the ready-to-ship station.
  box(scene,11,1.7,8.5,3.8,3.4,.15,'#536d70');box(scene,11,1.6,8.6,3.3,3.05,.08,'#a7b5ad');
  for(let j=0;j<7;j++)box(scene,11,.3+j*.43,8.66,3.3,.035,.03,'#718985');
  box(scene,12.5,.12,10,4,.22,2,'#86968d');
  const truck=new THREE.Group();scene.add(truck);truck.position.set(17,0,9);
  box(truck,0,1.65,0,2.9,2.9,5,'#e5dfcf');box(truck,0,1.05,3.3,2.9,1.85,2,'#d79b42');
  box(truck,0,1.73,4.32,2.55,.8,.05,'#4e8290');box(truck,0,.45,1,2.8,.3,8,'#354851');
  [-1.5,1.5].forEach(x=>[-1.6,3].forEach(z=>{const wheel=cyl(truck,x,.55,z,.54,.24,'#263b42');wheel.rotation.z=Math.PI/2;}));
  [-1,1].forEach(x=>box(truck,x,.85,4.37,.45,.25,.08,'#fff1b6'));
  const sceneryPeople=[];
  function person(color,x,z,route,title){
    const g=new THREE.Group();scene.add(g);g.position.set(x,.08,z);
    mesh(g,'CapsuleGeometry',[.26,.43,3,8],color,0,1.12,0);ball(g,0,1.78,0,.25,'#d8ac87');
    const hair=ball(g,0,1.9,-.03,.25,'#3e4240');hair.scale.y=.5;
    const legs=[];[-1,1].forEach(side=>{const leg=new THREE.Group();leg.position.set(side*.14,.8,0);g.add(leg);cyl(leg,0,-.3,0,.1,.6,'#354953');box(leg,0,-.65,.06,.23,.14,.35,'#243c43');legs.push(leg);cyl(g,side*.35,1.1,0,.08,.6,color);ball(g,side*.35,.77,0,.09,'#d8ac87');});
    sceneryPeople.push({g,legs,route:route||[],next:0,position:{x,z},phase:0,title});
  }
  person('#4e928c',-8,9.8); // Receptionist behind the intake counter.
  person('#304e69',-10,0,[{x:-10,z:0},{x:0,z:0},{x:10,z:0},{x:10,z:7},{x:4,z:7},{x:-10,z:7}],'ผู้จัดการ · ฉากประกอบ');
  person('#bb795b',-.8,11,[{x:-.8,z:11},{x:3.8,z:11},{x:3.8,z:13},{x:-.8,z:13}]);
  person('#b3a15c',3,13,[{x:3,z:13},{x:-2,z:13},{x:-2,z:10.6},{x:3,z:10.6}]);
  person('#cc9b40',12,11,[{x:12,z:11},{x:14,z:11},{x:14,z:8},{x:12,z:8}]);
  const dynamic=new THREE.Group();scene.add(dynamic);
  let actors=[],markers=[],lastPlan=null,paused=false,visible=true,inView=true,frame=0,lastTime=0,renderTime=0,disposed=false;
  function button(label,cls,fn){const b=document.createElement('button');b.type='button';b.className=cls;b.textContent=label;b.addEventListener('click',fn);overlay.appendChild(b);return b;}
  function marker(element,x,y,z){markers.push({element,point:new THREE.Vector3(x,y,z)});}
  function avatar(w,index){
    const group=new THREE.Group(),body=new THREE.Group();group.add(body);dynamic.add(group);
    const color=Core.stations[w.stops[0]].color;
    const leftLeg=new THREE.Group(),rightLeg=new THREE.Group();leftLeg.position.set(-.14,.8,0);rightLeg.position.set(.14,.8,0);body.add(leftLeg,rightLeg);
    cyl(leftLeg,0,-.31,0,.1,.62,'#364c59');cyl(rightLeg,0,-.31,0,.1,.62,'#364c59');box(leftLeg,0,-.66,.07,.23,.13,.36,'#253c43');box(rightLeg,0,-.66,.07,.23,.13,.36,'#253c43');
    mesh(body,'CapsuleGeometry',[.26,.43,3,8],color,0,1.12,0);
    ball(body,0,1.79,0,.25,'#e2b48d');const hair=ball(body,0,1.89,-.025,.254,'#54483c');hair.scale.y=.6;cyl(body,0,1.99,0,.27,.09,color);box(body,0,1.97,.19,.4,.045,.28,color);
    const arms=[];[-1,1].forEach(side=>{const arm=new THREE.Group();arm.position.set(side*.34,1.4,0);body.add(arm);cyl(arm,0,-.25,0,.075,.5,color);ball(arm,0,-.52,0,.085,'#e2b48d');arms.push(arm);});
    const stop=w.stops[0],position=Core.workpoint(stop,((index%3)-1)*.6);group.position.set(position.x,.08,position.z);
    const name=button(w.name,'office-3d-person',()=>hooks.onTicket(w.jobs[0],name));name.setAttribute('aria-label',w.name+' · เปิดงาน #'+w.jobs[0].ticket_id);
    const actor={group,body,leftLeg,rightLeg,arms,name,w,position,path:[],stop:0,wait:3+index*.7,phase:index,offset:((index%3)-1)*.6};actors.push(actor);return actor;
  }
  function update(config){
    lastPlan=Core.plan(config.tickets,config.statuses);dynamic.clear();actors=[];markers=[];overlay.replaceChildren();metrics.replaceChildren();
    lastPlan.rooms.forEach(r=>{
      const panel=document.createElement('div');panel.className='office-3d-station';overlay.appendChild(panel);
      const room=button(String(r.index+1).padStart(2,'0')+' · '+r.name+'  '+r.jobs.length+' งาน','office-3d-zone',()=>hooks.onStage(config.stage===r.status?'':r.status));room.style.setProperty('--zone',r.color);room.setAttribute('aria-pressed',String(config.stage===r.status));panel.appendChild(room);marker(panel,r.x,3.8,r.z-.4);
      const pins=document.createElement('div');pins.className='office-3d-job-list';panel.appendChild(pins);
      r.jobs.slice(0,4).forEach((t,i)=>{
        const x=r.x-1.8+i*.9,z=r.z;const printer=new THREE.Group();dynamic.add(printer);
        box(printer,x,1.7,z,.72,.18,.7,'#506971');[-.3,.3].forEach(dx=>[-.28,.28].forEach(dz=>box(printer,x+dx,2.12,z+dz,.055,.8,.055,'#354b4f')));box(printer,x,2.52,z,.72,.07,.68,'#8b9c96');box(printer,x,1.87,z,.54,.045,.55,r.color);
        const pin=button('#'+t.ticket_id,'office-3d-job',()=>hooks.onTicket(t,pin));pin.style.setProperty('--zone',r.color);pin.setAttribute('aria-label','เปิดงาน #'+t.ticket_id+' '+t.model);pins.appendChild(pin);
        box(printer,x,2.3,z,.65,.055,.07,'#354b4f');box(printer,x,2.19,z,.16,.2,.18,r.color);
      });
      if(r.jobs.length>4){const more=button('+'+(r.jobs.length-4)+' งาน','office-3d-more',()=>hooks.onStage(r.status));panel.appendChild(more);}
    });
    lastPlan.workers.forEach(avatar);
    sceneryPeople.forEach(p=>{if(p.title){p.label=document.createElement('span');p.label.className='office-3d-scenery';p.label.textContent=p.title;overlay.appendChild(p.label);}});
    [['รับเครื่อง / ต้อนรับ',-8,3.2,11],['ห้องพักลูกค้า',1,3.8,12],['ทางออก / รถรับสินค้า',14,4,10]].forEach(([title,x,y,z])=>{
      const label=document.createElement('span');label.className='office-3d-scenery';label.textContent=title+' · ฉากประกอบ';overlay.appendChild(label);marker(label,x,y,z);
    });
    [['งานทั้งหมด',lastPlan.jobs],['ช่างผู้รับผิดชอบ',lastPlan.technicians],['รออะไหล่',lastPlan.waiting],['รอส่งมอบ',lastPlan.dispatch]].forEach(([label,n])=>{const item=document.createElement('span'),count=document.createElement('strong');count.textContent=n;item.append(count,document.createTextNode(label));metrics.appendChild(item);});
    render();
  }
  const projected=new THREE.Vector3();
  function place(element,point){projected.copy(point).project(camera);const shown=projected.z>-1&&projected.z<1&&Math.abs(projected.x)<1.2&&Math.abs(projected.y)<1.2;element.hidden=!shown;if(shown){element.style.left=((projected.x+1)*50)+'%';element.style.top=((-projected.y+1)*50)+'%';}}
  function render(){if(disposed||!visible||!inView||document.hidden)return;renderer.render(scene,camera);sceneryPeople.forEach(p=>{if(p.label)place(p.label,new THREE.Vector3(p.g.position.x,2.8,p.g.position.z));});markers.forEach(m=>place(m.element,m.point));actors.forEach(a=>place(a.name,new THREE.Vector3(a.group.position.x,2.6,a.group.position.z)));}
  function tick(now){
    frame=0;if(disposed||!visible||!inView||document.hidden)return;
    const dt=Math.min(.05,lastTime?(now-lastTime)/1000:0);lastTime=now;
    if(!paused)actors.forEach(a=>{
      if(!a.path.length){a.wait-=dt;if(a.wait<=0){a.stop=(a.stop+1)%a.w.stops.length;const dest=Core.workpoint(a.w.stops[a.stop],a.offset);a.path=Core.route(a.position,dest);a.wait=6+a.phase*.3;}}
      if(a.path.length){const target=a.path[0],dx=target.x-a.position.x,dz=target.z-a.position.z;if(Math.hypot(dx,dz)>.01)a.group.rotation.y=Math.atan2(dx,dz);const next=Core.move(a.position,a.path,dt*1.25);a.position=next.position;a.path=next.path;a.group.position.set(a.position.x,.08,a.position.z);a.phase+=dt*8;const swing=Math.sin(a.phase)*.45;a.leftLeg.rotation.x=swing;a.rightLeg.rotation.x=-swing;a.arms[0].rotation.x=-swing;a.arms[1].rotation.x=swing;
      }else{a.leftLeg.rotation.x=a.rightLeg.rotation.x=0;a.arms[0].rotation.x=Math.sin(now/400+a.phase)*.1;a.arms[1].rotation.x=-.25;}
    });
    if(!paused)sceneryPeople.forEach(p=>{
      if(!p.route.length)return;
      const target=p.route[p.next],dx=target.x-p.position.x,dz=target.z-p.position.z;
      if(Math.hypot(dx,dz)<.05){p.next=(p.next+1)%p.route.length;return;}
      p.g.rotation.y=Math.atan2(dx,dz);p.position=Core.move(p.position,[target],dt*.85).position;p.g.position.set(p.position.x,.08,p.position.z);
      p.phase+=dt*7;p.legs[0].rotation.x=Math.sin(p.phase)*.4;p.legs[1].rotation.x=-Math.sin(p.phase)*.4;
    });
    controls.target.x=THREE.MathUtils.clamp(controls.target.x,-10,10);controls.target.z=THREE.MathUtils.clamp(controls.target.z,-7,7);controls.update();
    if(now-renderTime>=33){renderTime=now;render();}
    if(!paused&&(actors.length||sceneryPeople.length)||controls.enableDamping&&cameraMotion){frame=requestAnimationFrame(tick);}else lastTime=0;
    cameraMotion=false;
  }
  let cameraMotion=false;
  function wake(){if(!frame&&!disposed&&visible&&inView&&!document.hidden)frame=requestAnimationFrame(tick);}
  controls.addEventListener('change',()=>{cameraMotion=true;wake();});controls.addEventListener('start',()=>{cameraMotion=true;wake();});
  const resize=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;if(w&&h){camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);render();wake();}});resize.observe(host);
  const intersection=new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;if(inView){lastTime=0;wake();}else if(frame){cancelAnimationFrame(frame);frame=0;}});intersection.observe(host);
  function setVisible(v){visible=v;if(!v&&frame){cancelAnimationFrame(frame);frame=0;}if(v){lastTime=0;render();wake();}}
  function setPaused(v){paused=v;render();wake();}
  function reset(){camera.position.set(29,29,36);controls.target.set(2,1,3);controls.update();render();wake();}
  function zoom(delta){const v=camera.position.clone().sub(controls.target).multiplyScalar(delta>0?.86:1.16);v.clampLength(18,60);camera.position.copy(controls.target).add(v);controls.update();render();wake();}
  const key=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','=','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home')reset();else if(['+','=','-'].includes(e.key))zoom(e.key==='-'?-1:1);else{const v=camera.position.clone().sub(controls.target);if(e.key==='ArrowLeft'||e.key==='ArrowRight')v.applyAxisAngle(new THREE.Vector3(0,1,0),e.key==='ArrowLeft'?.15:-.15);else v.y=THREE.MathUtils.clamp(v.y+(e.key==='ArrowUp'?2:-2),8,45);camera.position.copy(controls.target).add(v);controls.update();render();wake();}}};canvas.addEventListener('keydown',key);
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();if(disposed)return;setVisible(false);hooks.onUnavailable();});
  function dispose(){disposed=true;if(frame)cancelAnimationFrame(frame);resize.disconnect();intersection.disconnect();controls.dispose();geos.forEach(g=>g.dispose());mats.forEach(m=>m.dispose());renderer.dispose();host.replaceChildren();}
  return {update(config){update(config);wake();},setVisible,setPaused,reset,zoom,dispose};
}
