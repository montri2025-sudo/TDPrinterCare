(function(){
'use strict';
const viewport=document.getElementById('restock-table-viewport'),dock=document.getElementById('restock-scroll-dock');if(!viewport||!dock)return;
const slider=document.getElementById('restock-scroll-range'),left=document.getElementById('restock-scroll-left'),right=document.getElementById('restock-scroll-right');
function sync(){const max=Math.max(0,viewport.scrollWidth-viewport.clientWidth);dock.hidden=max<2;slider.max=String(max);slider.value=String(Math.round(viewport.scrollLeft));slider.setAttribute('aria-valuetext',max?'เลื่อนไปทางขวา '+Math.round(viewport.scrollLeft/max*100)+' เปอร์เซ็นต์':'แสดงครบทุกคอลัมน์');left.disabled=viewport.scrollLeft<1;right.disabled=viewport.scrollLeft>=max-1;}
slider.addEventListener('input',()=>{viewport.scrollLeft=Number(slider.value);sync();});left.addEventListener('click',()=>{viewport.scrollLeft-=Math.max(160,viewport.clientWidth*.7);sync();});right.addEventListener('click',()=>{viewport.scrollLeft+=Math.max(160,viewport.clientWidth*.7);sync();});viewport.addEventListener('scroll',sync,{passive:true});window.addEventListener('resize',sync);
if('ResizeObserver' in window){const observer=new ResizeObserver(sync);observer.observe(viewport);observer.observe(document.getElementById('restock-orders-table'));}sync();
})();
