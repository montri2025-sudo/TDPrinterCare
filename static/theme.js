/* Apply before first paint; preferences stay on this device. */
(function(){
'use strict';
const key='tdsp-theme';let theme='dark';
try{const saved=localStorage.getItem(key);if(saved==='light'||saved==='dark')theme=saved;}catch(e){}
function apply(value){theme=value;document.documentElement.dataset.theme=value;document.documentElement.style.colorScheme=value;const button=document.getElementById('theme-toggle');if(button){button.textContent=value==='dark'?'☀ ธีมสว่าง':'☾ ธีมมืด';button.setAttribute('aria-label',value==='dark'?'เปลี่ยนเป็นธีมสว่าง':'เปลี่ยนเป็นธีมมืด');button.setAttribute('aria-pressed',String(value==='light'));}}
apply(theme);
document.addEventListener('DOMContentLoaded',()=>{apply(theme);const button=document.getElementById('theme-toggle');if(button)button.addEventListener('click',()=>{apply(theme==='dark'?'light':'dark');try{localStorage.setItem(key,theme);}catch(e){}});});
window.addEventListener('storage',event=>{if(event.key===key&&(event.newValue==='light'||event.newValue==='dark'))apply(event.newValue);});
})();
