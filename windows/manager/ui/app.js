let state = null;
let busy = false;
const $ = id => document.getElementById(id);
const reasonText = {verified:'出口核验通过。已有连接每 10 秒复核，异常时阻断。',exit_mismatch:'检测到出口不符合部署配置中的 IP / 国家 / 节点，已拒绝连接。',verification_failed:'出口核验失败，守卫正在阻断，等待链路恢复。',verification_degraded:'出口核验暂不可用；固定上游转发继续，等待下一次核验。',not_verified:'守卫正在核验固定住宅出口。',stopped:'守卫已停止。'};
function text(id, value){ $(id).textContent = value; }
function badge(id, label, kind){text(id,label);$(id).className='pill '+kind;}
function toast(message){text('toast',message);$('toast').classList.add('visible');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),6500);}
async function action(name,...args){if(busy)return;busy=true;document.querySelectorAll('button').forEach(x=>x.disabled=true);try{const r=await window.pywebview.api[name](...args);if(r&&!r.ok)toast(r.error);else if(name==='check_now')toast('正在检查实际连接，结果会自动更新。');await refresh();}catch(e){toast(String(e));}finally{busy=false;document.querySelectorAll('button').forEach(x=>x.disabled=false);}}
function render(s){state=s;text('expected-ip',s.expected_ip);text('expected-region',s.expected_country+' / '+s.expected_colo);const g=s.guard,r=s.remote,t=s.tunnel,c=s.codex;
 badge('codex-badge',c.remote.verified?'代理可用':c.owned?'等待上游':'等待连接',c.remote.verified?'good':'warn');
 text('codex-health',c.remote.verified?'已连通 ChatGPT':'等待连接');
 $('codex-count').replaceChildren(document.createTextNode(String(c.reconnects)+' '),Object.assign(document.createElement('small'),{textContent:'次'}));
 text('codex-message',!c.local_ok?'本机普通代理尚未启动':c.error||c.remote.reason);
 text('codex-toggle',s.settings.codex_reconnect?'暂停自动恢复':'启用自动恢复');$('codex-toggle').classList.toggle('stop',s.settings.codex_reconnect);
 text('codex-foot',c.owned?'本应用正在后台维持 Codex 隧道':c.external?'沿用现有 Codex 隧道':s.settings.codex_reconnect?'自动恢复已启用':'自动恢复未启用');
 $('codex-dot').className='dot '+(c.remote.verified?'good':'');
 text('codex-proxy-health',c.remote.verified?'已连通 ChatGPT':'等待连接');$('codex-proxy-health').className=c.remote.verified?'':'bad';
 badge('guard-badge',g.verified?'核验通过':g.forwarding?'核验告警':g.running?'正在阻断':'尚未启动',g.verified?'good':g.running?'warn':'neutral');
 text('guard-ip',g.ip);text('guard-region',g.region==='—'?'等待核验':`${g.region} / ${g.colo}`);
 text('guard-message',reasonText[g.reason]||g.reason);text('guard-toggle',s.settings.guard_enabled?'停止守卫':'启动守卫');$('guard-toggle').classList.toggle('stop',s.settings.guard_enabled);
 text('guard-foot',g.running?`当前转发 ${g.active} 条连接 · AdsPower 需设置为 17899`:'浏览器接入需要在 AdsPower 中设置一次');$('guard-dot').className='dot '+(g.verified?'good':g.running?'bad':'');
 badge('ssh-badge',r.verified?'链路已核验':r.reachable?'等待住宅链':'SSH 未就绪',r.verified?'good':r.reachable?'warn':'neutral');
 text('remote-ip',r.ip||'—');$('reconnect-count').replaceChildren(document.createTextNode(String(t.reconnects)+' '),Object.assign(document.createElement('small'),{textContent:'次'}));
 text('ssh-message',t.error||(r.verified?`远端出口 ${r.region} / ${r.colo}，守卫已放行。`:r.reason));
 text('ssh-toggle',s.settings.ssh_reconnect?'暂停自动恢复':'启用自动恢复');$('ssh-toggle').classList.toggle('stop',s.settings.ssh_reconnect);
 text('ssh-foot',t.owned?'本应用正在维持专用代理隧道':t.external?'沿用现有专用隧道 · '+(s.settings.ssh_reconnect?'断开后自动接续':'自动恢复未启用'):s.settings.ssh_reconnect?'自动恢复已启用':'自动恢复未启用');$('ssh-dot').className='dot '+(r.verified?'good':'');
 for(const [id,ok,on,off] of [['local-health',s.local_ok,'可连接','未连接'],['remote-health',r.reachable,'可连接','未连接'],['gate-health',r.verified,'固定出口核验通过','等待核验']]){text(id,ok?on:off);$(id).className=ok?'':'bad';}
 $('startup').checked=s.settings.startup;text('updated',s.checked_at);
 if(s.events.length)text('latest-event',s.events[0].message);
 $('event-list').replaceChildren(...s.events.map(e=>{const row=document.createElement('div');row.className='event';const stamp=document.createElement('time'),msg=document.createElement('p');stamp.textContent=e.time;msg.textContent=e.message;row.append(stamp,msg);return row;}));
 $('restart-owned').disabled=!t.owned;
}
async function refresh(){if(!window.pywebview?.api)return;try{render(await window.pywebview.api.snapshot());}catch(e){toast('状态读取失败：'+e);}}
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!==button.dataset.page));text('page-title',button.dataset.page==='overview'?'连接总览':'运行记录');});
$('guard-toggle').onclick=()=>state&&action('set_guard',!state.settings.guard_enabled);
$('ssh-toggle').onclick=()=>state&&action('set_reconnect',!state.settings.ssh_reconnect);
$('codex-toggle').onclick=()=>state&&action('set_codex_reconnect',!state.settings.codex_reconnect);
$('refresh').onclick=()=>action('check_now');$('open-vscode').onclick=()=>action('open_vscode');$('open-logs').onclick=()=>action('open_logs');$('restart-owned').onclick=()=>action('restart_owned_tunnel');
$('startup').onchange=e=>action('set_startup',e.target.checked);
$('adspower-guide').onclick=()=>$('guide').showModal();$('close-guide').onclick=()=>$('guide').close();
$('copy-proxy').onclick=async()=>{try{await navigator.clipboard.writeText('http://127.0.0.1:17899');toast('代理地址已复制');}catch{toast('代理地址：http://127.0.0.1:17899');}};
window.addEventListener('pywebviewready',()=>{refresh();setInterval(refresh,2000);});
