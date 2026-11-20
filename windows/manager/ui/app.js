let state = null;
let busy = false;
const $ = id => document.getElementById(id);
const reasonText = {verified:'出口核验通过。已有连接每 10 秒复核，异常时阻断。',exit_mismatch:'检测到出口不符合部署配置中的 IP / 国家 / 节点，已拒绝连接。',verification_failed:'出口核验失败，守卫正在阻断，等待链路恢复。',verification_degraded:'出口核验暂不可用；固定上游转发继续，等待下一次核验。',not_verified:'守卫正在核验固定住宅出口。',stopped:'守卫已停止。'};
function text(id, value){ $(id).textContent = value; }
function badge(id, label, kind){text(id,label);$(id).className='pill '+kind;}
function toast(message){text('toast',message);$('toast').classList.add('visible');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),6500);}
async function action(name,...args){
 if(busy)return;
 busy=true;
 document.querySelectorAll('button').forEach(button=>button.disabled=true);
 try{
  const result=await window.pywebview.api[name](...args);
  if(result&&!result.ok)toast(result.error);
  else if(name==='check_now')toast('正在检查实际连接，结果会自动更新。');
 }catch(error){toast(String(error));}
 finally{
  busy=false;
  document.querySelectorAll('button').forEach(button=>button.disabled=false);
  await refresh();
 }
}
function renderServer(server){
 const {configured,connected,gateway,node,phase,message}=server;
 text('server-address',configured?gateway.host+':'+gateway.port:'尚未添加');
 text('server-detail',configured?[gateway.user,node].filter(Boolean).join(' · '):'');
 const pending=phase==='password'?'等待密码':phase==='connecting'?'正在连接':'';
 badge('server-badge',pending||(connected?'已连接':'未连接'),connected&&!pending?'good':'neutral');
 text('server-message',pending==='等待密码'?'请在系统窗口输入当次密码。':pending||message||
      (configured?'点击“连接服务器”恢复连接。':'添加平台 SSH 入口后，用系统密码窗口连接。'));
 text('connect-server',connected?'检查连接':configured?'连接服务器':'添加服务器');
 text('change-server',node?'更换节点':'编辑服务器');
 $('connect-server').disabled=busy;
 $('change-server').hidden=!configured;
 $('change-server').disabled=busy;
 $('disconnect-server').disabled=busy||!connected;
}
function showServerDialog(){
 const server=state.server;
 const {host='',user='',port=22}=server.gateway;
 const {inner_user,shared_home,identity}=server.account;
 text('server-dialog-title',server.node?'更换节点':server.configured?'编辑服务器':'添加服务器');
 text('save-server',server.node?'连接新节点':'保存并连接');
 $('server-account').hidden=Boolean(server.node);
 $('server-switch-note').hidden=!server.node;
 $('server-form-error').hidden=true;
 for(const [id,value] of Object.entries({
  'server-host':host,'server-user':user,'server-port':port,
  'server-inner-user':inner_user,'server-home':shared_home,'server-key':identity,
 }))$(id).value=value;
 $('server-dialog').showModal();
}
function render(s){state=s;text('expected-ip',s.expected_ip);text('expected-region',s.expected_country+' / '+s.expected_colo);const g=s.guard,r=s.remote,t=s.tunnel,c=s.codex;
 renderServer(s.server);
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
 $('restart-owned').disabled=busy||s.server.configured||!t.owned;
 $('ssh-toggle').hidden=s.server.configured;
 $('codex-toggle').hidden=s.server.configured;
 if(s.server.configured){
  text('ssh-foot',s.server.connected?'由“我的服务器”保持连接':'请在“我的服务器”连接');
  text('codex-foot',s.server.connected?'由“我的服务器”保持连接':'请在“我的服务器”连接');
 }
}
async function refresh(){if(!window.pywebview?.api)return;try{render(await window.pywebview.api.snapshot());}catch(e){toast('状态读取失败：'+e);}}
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!==button.dataset.page));text('page-title',button.dataset.page==='overview'?'连接总览':'运行记录');});
$('connect-server').onclick=()=>{
 if(!state)return;
 if(state.server.configured)action('connect_server');
 else showServerDialog();
};
$('change-server').onclick=showServerDialog;
$('close-server').onclick=()=>$('server-dialog').close();
$('save-server').onclick=()=>{
 const [host,user,port]=['server-host','server-user','server-port'].map(id=>$(id).value.trim());
 const account=state.server.node?null:{
  inner_user:$('server-inner-user').value.trim(),
  shared_home:$('server-home').value.trim(),
  identity:$('server-key').value.trim()
 };
 if(!host||!user||!port||(account&&Object.values(account).some(value=>!value))){
  text('server-form-error','请填写全部服务器字段。');
  $('server-form-error').hidden=false;
  return;
 }
 $('server-dialog').close();
 action('connect_server',host,user,port,account);
};
$('disconnect-server').onclick=()=>$('disconnect-dialog').showModal();
$('cancel-disconnect').onclick=()=>$('disconnect-dialog').close();
$('confirm-disconnect').onclick=()=>{
 $('disconnect-dialog').close();
 action('disconnect_server');
};
$('guard-toggle').onclick=()=>state&&action('set_guard',!state.settings.guard_enabled);
$('ssh-toggle').onclick=()=>state&&action('set_reconnect',!state.settings.ssh_reconnect);
$('codex-toggle').onclick=()=>state&&action('set_codex_reconnect',!state.settings.codex_reconnect);
$('refresh').onclick=()=>action('check_now');$('open-vscode').onclick=()=>action('open_vscode');$('open-logs').onclick=()=>action('open_logs');$('restart-owned').onclick=()=>action('restart_owned_tunnel');
$('startup').onchange=e=>action('set_startup',e.target.checked);
$('adspower-guide').onclick=()=>$('guide').showModal();$('close-guide').onclick=()=>$('guide').close();
$('copy-proxy').onclick=async()=>{try{await navigator.clipboard.writeText('http://127.0.0.1:17899');toast('代理地址已复制');}catch{toast('代理地址：http://127.0.0.1:17899');}};
window.addEventListener('pywebviewready',()=>{refresh();setInterval(refresh,2000);});
