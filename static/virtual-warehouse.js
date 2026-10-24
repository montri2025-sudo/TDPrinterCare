/* Virtual shelves are a read-only stock visualization. Stock forms remain separate. */
(function () {
  'use strict';
  const source=document.getElementById('warehouse-data');if(!source)return;
  const data=JSON.parse(source.textContent), products=data.products;
  const el=id=>document.getElementById(id), search=el('warehouse-search');
  let mode='all',groupLimit=9,selected=null,opener=null;
  const slotLimits=new Map();
  const format=n=>Number(n).toLocaleString('th-TH');
  function node(tag,parent,text,className) {
    const item=document.createElement(tag);if(text!=null)item.textContent=String(text);
    if(className)item.className=className;if(parent)parent.appendChild(item);return item;
  }
  const locations=[...new Set(products.map(p=>p.location))].sort((a,b)=>a.localeCompare(b));
  locations.forEach(location=>{const option=node('option',el('warehouse-location'),location);option.value=location;});
  function productButton(parent,product) {
    const button=node('button',parent,null,'warehouse-box'+(product.low?' is-low':'')+(product.bestSeller?' is-best':''));button.type='button';
    button.setAttribute('aria-label',product.name+' คงเหลือ '+product.stock+' แนะนำสั่งเพิ่ม '+product.suggested);
    node('span',button,'▣','box-symbol');node('strong',button,product.name);node('small',button,product.sku);
    const stock=node('span',button,null,'box-stock');node('b',stock,format(product.stock));node('span',stock,'คงเหลือ');
    const badges=node('span',button,null,'box-badges');
    if(product.low)node('i',badges,product.stock<=0?'หมดสต็อก':'สต็อกต่ำ','badge-low');
    if(product.bestSeller)node('i',badges,'ขายดี','badge-best');
    if(product.suggested)node('i',badges,'สั่งเพิ่ม '+format(product.suggested),'badge-order');
    button.addEventListener('click',()=>openProduct(product,button));
  }
  function openProduct(product,button) {
    selected=product;opener=button;
    el('warehouse-product-title').textContent=product.name;
    el('warehouse-product-sku').textContent=product.sku;
    el('warehouse-product-location').textContent='ตำแหน่ง: '+product.location;
    const metrics=el('warehouse-product-metrics');metrics.replaceChildren();
    [['คงเหลือ',product.stock],['จุดสั่งซื้อ',product.reorder],['ขายเดือนนี้',product.soldMonth],['ขาย + เบิกใช้ 30 วัน',product.used30],['คาดว่าจะใช้ถึงสิ้นเดือน',product.forecast],['แนะนำสั่งเพิ่ม',product.suggested],['ของสั่งค้าง (ยังไม่หัก)',product.incoming]].forEach(([label,value])=>{
      const row=node('div',metrics);node('dt',row,label);node('dd',row,format(value)+' หน่วย');
    });el('warehouse-dialog').showModal();
  }
  function render() {
    const term=search.value.trim().toLocaleLowerCase(),location=el('warehouse-location').value;
    const filtered=products.filter(p=>(!term||[p.sku,p.name,p.location].join(' ').toLocaleLowerCase().includes(term))&&(!location||p.location===location)&&
      (mode==='all'||(mode==='low'&&p.low)||(mode==='best'&&p.bestSeller)||(mode==='order'&&p.suggested>0)));
    el('warehouse-total').textContent=format(filtered.length);
    el('warehouse-low').textContent=format(filtered.filter(p=>p.low).length);
    el('warehouse-best').textContent=format(filtered.filter(p=>p.bestSeller).length);
    el('warehouse-order').textContent=format(filtered.filter(p=>p.suggested>0).length);
    el('warehouse-units').textContent='SKU · รวม '+format(filtered.reduce((sum,p)=>sum+p.suggested,0))+' หน่วยคละสินค้า';
    el('warehouse-showing').textContent=filtered.length+' / '+products.length+' SKU';
    el('warehouse-screen-skus').textContent=format(filtered.length);
    el('warehouse-screen-stock').textContent=format(filtered.reduce((sum,p)=>sum+p.stock,0));
    el('warehouse-screen-sales').textContent=format(filtered.reduce((sum,p)=>sum+p.soldMonth,0));
    el('warehouse-screen-order').textContent=format(filtered.reduce((sum,p)=>sum+p.suggested,0));
    const screenRows=el('warehouse-screen-rows');screenRows.replaceChildren();
    const summaryRows=filtered.slice().sort((a,b)=>Number(b.low)-Number(a.low)||b.suggested-a.suggested||b.soldMonth-a.soldMonth);
    summaryRows.slice(0,6).forEach(product=>{
      const tr=node('tr',screenRows);const nameCell=node('td',tr);const link=node('button',nameCell,product.name);link.type='button';
      link.addEventListener('click',()=>openProduct(product,link));node('small',nameCell,product.sku);
      node('td',tr,format(product.stock),product.low?'stock-text-low':'');node('td',tr,format(product.soldMonth));node('td',tr,format(product.suggested),'stock-text-order');
    });
    if(!summaryRows.length){const tr=node('tr',screenRows);const cell=node('td',tr,'ไม่มีสินค้าในตัวกรองนี้');cell.colSpan=4;}
    el('warehouse-screen-caption').textContent=summaryRows.length>6?'แสดง 6 / '+summaryRows.length+' SKU · เรียงสต็อกต่ำและรายการแนะนำสั่งเพิ่มก่อน':'แสดง '+summaryRows.length+' SKU ตามตัวกรอง';
    const groups=new Map();filtered.forEach(p=>{if(!groups.has(p.location))groups.set(p.location,[]);groups.get(p.location).push(p);});
    const racks=el('warehouse-racks');racks.replaceChildren();
    if(!filtered.length){const empty=node('div',racks,null,'warehouse-empty');node('strong',empty,'ไม่พบสินค้าในตัวกรองนี้');node('p',empty,products.length?'ลองค้นหาหรือเลือกสถานะอื่น':'ยังไม่มีสินค้าที่มีสิทธิ์เข้าถึง');}
    [...groups.entries()].slice(0,groupLimit).forEach(([location,items],index)=>{
      const rack=node('section',racks,null,'warehouse-rack');
      const header=node('header',rack);node('span',header,'RACK '+String(index+1).padStart(2,'0'));
      node('h3',header,location);node('small',header,items.length+' SKU');
      const slots=node('div',rack,null,'warehouse-slots');const limit=slotLimits.get(location)||6;
      items.slice(0,limit).forEach(product=>productButton(slots,product));
      if(items.length>limit){const more=node('button',rack,'แสดงอีก '+Math.min(6,items.length-limit)+' / เหลือ '+(items.length-limit)+' SKU','rack-more');more.type='button';more.addEventListener('click',()=>{slotLimits.set(location,limit+6);render();});}
      const foot=node('footer',rack);node('span',foot,items.filter(p=>p.low).length+' SKU สต็อกต่ำ');node('span',foot,items.filter(p=>p.bestSeller).length+' SKU ขายดี');
    });
    el('warehouse-more').hidden=groups.size<=groupLimit;
    const plan=el('warehouse-order-list');plan.replaceChildren();
    const suggested=filtered.filter(p=>p.suggested>0).sort((a,b)=>b.suggested-a.suggested||a.sku.localeCompare(b.sku));
    if(!suggested.length)node('p',plan,'ไม่มีรายการแนะนำสั่งเพิ่มในตัวกรองนี้','warehouse-plan-empty');
    suggested.slice(0,8).forEach(product=>{
      const button=node('button',plan,null,'warehouse-order-item');button.type='button';
      node('strong',button,product.name);node('small',button,product.sku+' · คงเหลือ '+format(product.stock));
      node('b',button,'แนะนำ +'+format(product.suggested));
      if(product.incoming)node('span',button,'มีของสั่งค้าง '+format(product.incoming)+' · ตรวจวันรับก่อนสั่ง');
      button.addEventListener('click',()=>openProduct(product,button));
    });
    if(suggested.length>8)node('p',plan,'อีก '+(suggested.length-8)+' SKU — เลือก “แนะนำให้สั่งเพิ่ม” เพื่อดูบนชั้นวาง','warehouse-plan-empty');
  }
  search.addEventListener('input',()=>{groupLimit=9;render();});
  el('warehouse-location').addEventListener('change',()=>{groupLimit=9;render();});
  document.querySelectorAll('[data-stock-filter]').forEach(button=>button.addEventListener('click',()=>{
    mode=button.dataset.stockFilter;groupLimit=9;
    document.querySelectorAll('[data-stock-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));render();
  }));
  el('warehouse-more').addEventListener('click',()=>{groupLimit+=9;render();});
  const dialog=el('warehouse-dialog');el('warehouse-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(opener&&opener.isConnected)opener.focus();});
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  const detailButton=el('warehouse-product-detail');
  if(detailButton)detailButton.addEventListener('click',()=>{dialog.close();if(selected&&typeof window.openProductDetail==='function')window.openProductDetail(selected.sku);});
  const hall=document.querySelector('.warehouse-hall');
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused=reduced.matches,inView=true;
  function motion(){hall.classList.toggle('is-paused',paused||!inView||document.hidden);el('warehouse-motion').textContent=paused?'เล่นภาพพนักงาน':'หยุดภาพพนักงาน';el('warehouse-motion').setAttribute('aria-pressed',String(paused));}
  el('warehouse-motion').addEventListener('click',()=>{paused=!paused;motion();});
  document.addEventListener('visibilitychange',motion);
  reduced.addEventListener('change',()=>{paused=reduced.matches;motion();});
  if('IntersectionObserver' in window)new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;motion();}).observe(hall);
  const toolsLink=document.querySelector('a[href="#warehouse-tools"]');
  if(toolsLink)toolsLink.addEventListener('click',()=>{const input=document.querySelector('input[data-search-for="inventory-table"]');if(input)input.dispatchEvent(new Event('input',{bubbles:true}));});
  render();motion();
})();
