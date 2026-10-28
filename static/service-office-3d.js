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
  const scene=new THREE.Scene();scene.background=new THREE.Color('#f2ecdf');
  const camera=new THREE.PerspectiveCamera(38,1,.1,150);camera.position.set(20,20,24);
  const controls=new OrbitControls(camera,canvas);controls.target.set(0,1,0);controls.enableDamping=true;controls.dampingFactor=.1;controls.minDistance=18;controls.maxDistance=60;controls.maxPolarAngle=Math.PI*.46;controls.minPolarAngle=.3;
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
  box(scene,0,-.36,0,26.5,.65,18.6,'#728577');
  for(let i=0;i<27;i++)box(scene,-13+i,0,0,.98,.08,18,['#cfae7d','#d8b98a','#cfb389','#e0c398'][i%4],false);
  box(scene,0,2.65,-9.2,26.4,5.4,.25,'#d7d0b7');box(scene,-13.15,2.65,0,.25,5.4,18.6,'#bfc7b3');
  box(scene,0,.25,-9,26,.35,.15,'#7d8873');box(scene,-13,.25,0,.15,.35,18,'#7d8873');
  for(let i=0;i<5;i++){
    const x=-10+i*5;box(scene,x,3.1,-9.01,3.3,2.8,.08,'#50685f');box(scene,x,3.1,-8.94,3.04,2.52,.08,'#b9d7d5');box(scene,x,3.1,-8.85,.07,2.55,.1,'#64766a');box(scene,x,3.1,-8.85,3.1,.07,.1,'#64766a');box(scene,x,1.63,-8.7,3.5,.13,.5,'#eee5cf');
  }
  const clock=cyl(scene,-12.9,3.7,-1,.55,.12,'#f6edda');clock.rotation.z=Math.PI/2;const clockHand=box(scene,-12.8,3.8,-1,.08,.4,.04,'#556552');
  function plant(x,z){cyl(scene,x,.36,z,.33,.7,'#e7ddc5');cyl(scene,x,1,z,.05,1.2,'#7b7b52');for(let j=0;j<5;j++){const a=j*Math.PI*.4;const leaf=ball(scene,x+Math.cos(a)*.25,1.3+j*.1,z+Math.sin(a)*.25,.32,j%2?'#63916c':'#85a06e');leaf.scale.set(.7,1.5,.6);}}
  [[-12,8],[12,8],[-12,-8],[12,-8],[-4,-8],[4,-8]].forEach(([x,z])=>plant(x,z));
  Core.stations.forEach((s,i)=>{
    box(scene,s.x,.08,s.z,6,.035,4.2,['#bcced1','#c9c1d7','#d8c7a3','#b6ccbe','#b7cdd3','#c7c6d8'][i],false);
    box(scene,s.x,1.45,s.z,5.4,.18,1.75,'#e4ca96');
    [-2.35,2.35].forEach(x=>[-.65,.65].forEach(z=>box(scene,s.x+x,.7,s.z+z,.12,1.4,.12,'#53675f')));
    box(scene,s.x+2,2.12,s.z,1,.7,.11,'#3d5051');box(scene,s.x+2,2.12,s.z+.067,.85,.55,.035,'#6ea8b2');box(scene,s.x+2,1.73,s.z,.1,.3,.1,'#53675f');
    box(scene,s.x+1.85,.78,s.z+(s.z<0?1.2:-1.2),.7,.15,.7,'#6a806e');box(scene,s.x+1.85,1.2,s.z+(s.z<0?1.5:-1.5),.7,.8,.13,'#6a806e');cyl(scene,s.x+1.85,.4,s.z+(s.z<0?1.2:-1.2),.07,.7,'#667574');
    if(i===2){for(let shelf=0;shelf<3;shelf++){box(scene,s.x-2.3,.6+shelf*.6,s.z+.6,.8,.09,1,'#7b8c75');for(let j=0;j<2;j++)box(scene,s.x-2.3,.85+shelf*.6,s.z+.36+j*.45,.5,.35,.32,j?'#c3ad80':'#759b8c');}}
    if(i===5){for(let j=0;j<3;j++){box(scene,s.x-1+j*.8,1.78,s.z,.64,.48,.6,'#c9a574');box(scene,s.x-1+j*.8,2.025,s.z,.12,.01,.61,'#e7d3a5');}}
  });
  // Meeting/acceptance corner, separate from the six workstations.
  cyl(scene,10,.9,7,.95,.12,'#d6d4b2');cyl(scene,10,.45,7,.12,.8,'#687b67');
  for(let j=0;j<4;j++){const a=j*Math.PI/2;box(scene,10+Math.cos(a)*1.3,.6,7+Math.sin(a)*1.3,.55,.12,.55,'#7b8c71');}
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
    [['งานทั้งหมด',lastPlan.jobs],['ช่างผู้รับผิดชอบ',lastPlan.technicians],['รออะไหล่',lastPlan.waiting],['รอส่งมอบ',lastPlan.dispatch]].forEach(([label,n])=>{const item=document.createElement('span'),count=document.createElement('strong');count.textContent=n;item.append(count,document.createTextNode(label));metrics.appendChild(item);});
    render();
  }
  const projected=new THREE.Vector3();
  function place(element,point){projected.copy(point).project(camera);const shown=projected.z>-1&&projected.z<1&&Math.abs(projected.x)<1.2&&Math.abs(projected.y)<1.2;element.hidden=!shown;if(shown){element.style.left=((projected.x+1)*50)+'%';element.style.top=((-projected.y+1)*50)+'%';}}
  function render(){if(disposed||!visible||!inView||document.hidden)return;renderer.render(scene,camera);markers.forEach(m=>place(m.element,m.point));actors.forEach(a=>place(a.name,new THREE.Vector3(a.group.position.x,2.6,a.group.position.z)));}
  function tick(now){
    frame=0;if(disposed||!visible||!inView||document.hidden)return;
    const dt=Math.min(.05,lastTime?(now-lastTime)/1000:0);lastTime=now;
    if(!paused)actors.forEach(a=>{
      if(!a.path.length){a.wait-=dt;if(a.wait<=0){a.stop=(a.stop+1)%a.w.stops.length;const dest=Core.workpoint(a.w.stops[a.stop],a.offset);a.path=Core.route(a.position,dest);a.wait=6+a.phase*.3;}}
      if(a.path.length){const target=a.path[0],dx=target.x-a.position.x,dz=target.z-a.position.z;if(Math.hypot(dx,dz)>.01)a.group.rotation.y=Math.atan2(dx,dz);const next=Core.move(a.position,a.path,dt*1.25);a.position=next.position;a.path=next.path;a.group.position.set(a.position.x,.08,a.position.z);a.phase+=dt*8;const swing=Math.sin(a.phase)*.45;a.leftLeg.rotation.x=swing;a.rightLeg.rotation.x=-swing;a.arms[0].rotation.x=-swing;a.arms[1].rotation.x=swing;
      }else{a.leftLeg.rotation.x=a.rightLeg.rotation.x=0;a.arms[0].rotation.x=Math.sin(now/400+a.phase)*.1;a.arms[1].rotation.x=-.25;}
    });
    controls.target.x=THREE.MathUtils.clamp(controls.target.x,-10,10);controls.target.z=THREE.MathUtils.clamp(controls.target.z,-7,7);controls.update();
    if(now-renderTime>=33){renderTime=now;render();}
    if(!paused&&actors.length||controls.enableDamping&&cameraMotion){frame=requestAnimationFrame(tick);}else lastTime=0;
    cameraMotion=false;
  }
  let cameraMotion=false;
  function wake(){if(!frame&&!disposed&&visible&&inView&&!document.hidden)frame=requestAnimationFrame(tick);}
  controls.addEventListener('change',()=>{cameraMotion=true;wake();});controls.addEventListener('start',()=>{cameraMotion=true;wake();});
  const resize=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;if(w&&h){camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);render();wake();}});resize.observe(host);
  const intersection=new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;if(inView){lastTime=0;wake();}else if(frame){cancelAnimationFrame(frame);frame=0;}});intersection.observe(host);
  function setVisible(v){visible=v;if(!v&&frame){cancelAnimationFrame(frame);frame=0;}if(v){lastTime=0;render();wake();}}
  function setPaused(v){paused=v;render();wake();}
  function reset(){camera.position.set(20,20,24);controls.target.set(0,1,0);controls.update();render();wake();}
  function zoom(delta){const v=camera.position.clone().sub(controls.target).multiplyScalar(delta>0?.86:1.16);v.clampLength(18,60);camera.position.copy(controls.target).add(v);controls.update();render();wake();}
  const key=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','=','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home')reset();else if(['+','=','-'].includes(e.key))zoom(e.key==='-'?-1:1);else{const v=camera.position.clone().sub(controls.target);if(e.key==='ArrowLeft'||e.key==='ArrowRight')v.applyAxisAngle(new THREE.Vector3(0,1,0),e.key==='ArrowLeft'?.15:-.15);else v.y=THREE.MathUtils.clamp(v.y+(e.key==='ArrowUp'?2:-2),8,45);camera.position.copy(controls.target).add(v);controls.update();render();wake();}}};canvas.addEventListener('keydown',key);
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();if(disposed)return;setVisible(false);hooks.onUnavailable();});
  function dispose(){disposed=true;if(frame)cancelAnimationFrame(frame);resize.disconnect();intersection.disconnect();controls.dispose();geos.forEach(g=>g.dispose());mats.forEach(m=>m.dispose());renderer.dispose();host.replaceChildren();}
  return {update(config){update(config);wake();},setVisible,setPaused,reset,zoom,dispose};
}
