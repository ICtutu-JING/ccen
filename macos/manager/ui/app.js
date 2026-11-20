let state = null;
let busy = false;
const $ = id => document.getElementById(id);
const reasonText = {verified:'固定出口核验通过，每 10 秒复核。',exit_mismatch:'出口不符合指定 IP / 国家 / 节点，已阻断。',verification_failed:'出口核验失败，正在阻断。',verification_degraded:'核验暂不可用；固定上游继续转发，等待下次核验。',not_verified:'正在核验固定住宅出口。',stopped:'守卫已停止。'};
function text(id,value){$(id).textContent=value;}
function badge(id,label,kind){text(id,label);$(id).className='pill '+kind;}
function toast(message){text('toast',message);$('toast').classList.add('visible');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),9000);}
async function action(name,...args){
 if(busy)return;
 busy=true;
 document.querySelectorAll('button').forEach(x=>x.disabled=true);
 try{const r=await window.pywebview.api[name](...args);if(r&&!r.ok)toast(r.error);else if(name==='check_now')toast('正在重新检查网络。');}
 catch(e){toast(String(e));}
 finally{busy=false;document.querySelectorAll('button').forEach(x=>x.disabled=false);await refresh();}
}
function render(s){
 state=s;const g=s.guard,c=s.connection;
 text('expected-ip',s.expected_ip);text('expected-region',s.expected_country+' / '+s.expected_colo);
 text('server-address',c.configured?c.gateway.host+':'+c.gateway.port:'尚未配置');
 text('server-detail',c.configured?c.gateway.user+' · '+c.node:'请先配置服务器');
 badge('server-badge',c.phase==='awaiting_password'?'等待密码':c.phase==='connecting'?'连接中':c.connected?'已连接':'未连接',c.connected?'good':'neutral');
 text('server-message',c.message);
 text('connect-server',c.phase==='awaiting_password'?'等待密码…':c.phase==='connecting'?'等待连接…':c.connected?'检查连接':'连接服务器');
 $('disconnect-server').disabled=busy||!c.connected;
 $('change-server').disabled=busy||!c.configured;
 badge('guard-badge',g.verified?'核验通过':g.forwarding?'核验告警':g.running?'正在阻断':'已停止',g.verified?'good':g.running?'warn':'neutral');
 text('guard-ip',g.ip);text('guard-region',g.region==='—'?'等待核验':g.region+' / '+g.colo);
 text('guard-message',reasonText[g.reason]||g.reason);
 text('guard-toggle',s.settings.guard_enabled?'停止守卫':'启动守卫');$('guard-toggle').classList.toggle('stop',s.settings.guard_enabled);
 text('guard-foot',g.running?'当前转发 '+g.active+' 条连接':'守卫停止后，已接入的 Claude 与浏览器无法联网');
 $('guard-dot').className='dot '+(g.verified?'good':'');
 const ok=c.connected&&c.claude.ok&&c.codex.ok;
 badge('remote-badge',ok?'链路核验通过':c.connected?'链路异常':'等待服务器',ok?'good':'warn');
 text('remote-claude',c.claude.ok?c.claude.ip+' · '+c.claude.country+' / '+c.claude.colo:c.connected?'未通过核验':'等待连接');
 text('remote-codex',c.codex.ok?'授权服务可达':c.connected?'代理未连通':'等待连接');
 text('remote-checked',c.checked_at||'—');
 text('remote-message',ok?'两条代理可用。账号登录和首次应用连接在各自桌面界面完成。':c.connected?'查看守卫及 Clash 状态，点击“检查链路”重新核验。':'点击上方“连接服务器”，无需输入终端指令。');
 $('remote-dot').className='dot '+(ok?'good':'');
 for(const id of ['open-codex','open-claude'])$(id).disabled=busy||!c.connected;
 $('startup').checked=s.settings.startup;$('startup').disabled=busy;
 text('updated',s.checked_at);if(s.events.length)text('latest-event',s.events[0].message);
 $('event-list').replaceChildren(...s.events.map(e=>{const row=document.createElement('div');row.className='event';const stamp=document.createElement('time'),msg=document.createElement('p');stamp.textContent=e.time;msg.textContent=e.message;row.append(stamp,msg);return row;}));
}
async function refresh(){if(!window.pywebview?.api)return;try{render(await window.pywebview.api.snapshot());}catch(e){toast('状态读取失败：'+e);}}
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!==button.dataset.page));text('page-title',button.dataset.page==='overview'?'连接总览':'运行记录');});
$('guard-toggle').onclick=()=>state&&action('set_guard',!state.settings.guard_enabled);
$('connect-server').onclick=()=>action('connect_server');
$('change-server').onclick=()=>{const e=state.connection.gateway;$('server-host').value=e.host;$('server-user').value=e.user;$('server-port').value=e.port;$('server-dialog').showModal();};
$('close-server').onclick=()=>$('server-dialog').close();
$('save-server').onclick=()=>{const host=$('server-host').value.trim(),user=$('server-user').value.trim(),port=$('server-port').value;if(!host||!user||!port){toast('请填写服务器地址、用户名和端口。');return;}$('server-dialog').close();action('connect_server',host,user,port);};
$('disconnect-server').onclick=()=>$('disconnect-dialog').showModal();
$('cancel-disconnect').onclick=()=>$('disconnect-dialog').close();
$('confirm-disconnect').onclick=()=>{$('disconnect-dialog').close();action('disconnect_server');};
$('open-codex').onclick=()=>action('open_client','codex');$('open-claude').onclick=()=>action('open_client','claude');
$('refresh').onclick=()=>action('check_now');$('open-logs').onclick=()=>action('open_logs');
$('startup').onchange=e=>action('set_startup',e.target.checked);
$('adspower-guide').onclick=()=>$('guide').showModal();$('close-guide').onclick=()=>$('guide').close();
window.addEventListener('pywebviewready',()=>{refresh();setInterval(refresh,2000);});
