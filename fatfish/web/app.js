const params = new URLSearchParams(location.hash.slice(1));
if (params.has('token')) { sessionStorage.setItem('fatfish-token', params.get('token')); history.replaceState(null, '', location.pathname); }
const token = sessionStorage.getItem('fatfish-token') || '';
let saved = {}, busy = false, exited = false, qqDismissed = false, qqOnline = false, loginAccount = '';
let friends = [];
const titles = {home:'我的大肥鱼', connect:'连接设置', persona:'人格与记忆', library:'我的资料库', manage:'数据与扩展', logs:'运行记录'};
function notice(message, error=false) { const el=document.querySelector('#notice'); el.textContent=message; el.className=error?'error':'success'; el.hidden=false; if(el.getBoundingClientRect().bottom<0)el.scrollIntoView({behavior:'smooth',block:'start'}); }
async function api(path, body) {
  const response = await fetch('/api/'+path, {method:body===undefined?'GET':'POST', headers:{'X-Fatfish-Token':token, 'Content-Type':'application/json'}, ...(body!==undefined?{body:JSON.stringify(body)}:{})});
  const data=await response.json(); if(!response.ok) throw new Error(data.error || '操作未完成'); return data;
}
function page(name) { document.querySelectorAll('.page').forEach(e=>e.classList.toggle('active',e.id===name)); document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.page===name)); document.querySelector('#page-name').textContent=titles[name]; if(name==='logs') refreshLogs(); if(name==='library') refreshLibrary(); }
document.querySelectorAll('[data-page],[data-go]').forEach(e=>e.addEventListener('click',()=>page(e.dataset.page||e.dataset.go)));
function fill() {
  for(const form of document.forms) if(form.id!=='fish-identity-form') for(const field of form.elements) if(field.name && field.type!=='password') {
    if(field.type==='checkbox') field.checked=!!saved[field.name]; else field.value=Array.isArray(saved[field.name])?saved[field.name].join(', '):(saved[field.name]??'');
  }
  document.querySelector('#key-state').textContent=saved.has_api_key?'已有密钥。输入新密钥可替换，留空保留。':'密钥尚未配置';
  document.querySelector('[name=group_scope]').value=saved.group_scope||((saved.groups?.length||saved.users?.length)?'selected':'all');
  syncGroupScope();
  document.querySelector('[name=private_scope]').value=saved.private_scope||(saved.users?.length?'selected':'off');
  syncPrivateScope();
  syncReplyFrequency();
}
function syncReplyFrequency() {
  const value=Number(document.querySelector('[name=group_reply_frequency]').value);
  document.querySelector('#reply-frequency-value').value=(value*100).toFixed(0)+'%';
  document.querySelector('#reply-frequency-hint').textContent=value===0?'0%：不主动开启新话题；仍会回应呼叫和有价值的旧话题追问。':value===1?'100%：没有呼叫或未结束话题时，每次都尝试开启新话题；仍会判断是否值得说话，不逐条回复。':`${(value*100).toFixed(0)}%：只在没人叫它、也没有未结束话题时，按此概率尝试接一个新话题。`;
}
document.querySelector('[name=group_reply_frequency]').addEventListener('input',syncReplyFrequency);
function syncGroupScope() {
  const all=document.querySelector('[name=group_scope]').value==='all';
  document.querySelector('#group-list-field').hidden=all;
  document.querySelector('[name=groups]').disabled=all;
  document.querySelector('#group-scope-hint').textContent=all?'接入这个 QQ 已加入的所有群聊，无需填写群号。':'只接入下方填写的群聊；多个群号用逗号分隔。';
}
document.querySelector('[name=group_scope]').addEventListener('change',syncGroupScope);
function syncPrivateScope() {
  const mode=document.querySelector('[name=private_scope]').value;
  document.querySelector('#private-people-field').hidden=mode!=='selected';
  document.querySelector('[name=users]').disabled=mode!=='selected';
  document.querySelector('#private-scope-hint').textContent=mode==='all'?'回复所有能向这个小号发来私聊消息的人。':mode==='off'?'不接收或回复私聊消息。':'只回复选中的联系人；也可以手动填写 QQ 号。选择后请保存连接设置。';
  renderFriends();
}
function renderFriends() {
  const selected=new Set(document.querySelector('[name=users]').value.split(/[,，\s]+/).filter(Boolean));
  const list=document.querySelector('#private-friends');
  list.replaceChildren();
  for(const friend of friends) {
    const label=document.createElement('label');label.className='friend-choice';
    const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(friend.qq);
    const text=document.createElement('span');text.textContent=friend.name+'（'+friend.qq+'）';
    check.addEventListener('change',()=>{const input=document.querySelector('[name=users]');const current=new Set(input.value.split(/[,，\s]+/).filter(Boolean));if(check.checked)current.add(friend.qq);else current.delete(friend.qq);input.value=[...current].join(', ');});
    label.append(check,text);list.append(label);
  }
}
document.querySelector('[name=private_scope]').addEventListener('change',syncPrivateScope);
document.querySelector('[name=users]').addEventListener('input',renderFriends);
document.querySelector('#load-private-friends').addEventListener('click',async()=>{
  const button=document.querySelector('#load-private-friends');button.disabled=true;button.textContent='正在读取好友…';
  try{const data=await api('qq-friends');friends=data.friends;renderFriends();document.querySelector('#private-friends-note').textContent=friends.length?'勾选要接入私聊的好友，然后保存连接设置。':'好友列表为空，可以在下方手动填写 QQ 号。';}
  catch(e){notice(e.message,true);document.querySelector('#private-friends-note').textContent=e.message;}
  finally{button.disabled=false;button.textContent='从 QQ 好友中选择';}
});
async function refresh() {
  const s=await api('status');
  document.querySelector('#header-state').textContent=s.ready?'核心就绪':s.running?'核心启动中':s.last_exit?'核心启动失败':'核心未启动';
  document.querySelector('#header-state').classList.toggle('online',s.ready);
  document.querySelector('#core-state').textContent=s.ready?'已就绪':s.running?'启动中':s.last_exit?'启动失败':'已停止';
  document.querySelector('#core-detail').textContent=s.last_exit && !s.running?'上次启动退出，请查看运行记录':'大肥鱼的蓝色小窝';
  document.querySelector('#hero-mood').textContent=s.ready?'已经准备好聊天啦。':s.running?'大肥鱼正在醒来…':'先在这里发会儿呆。';
  document.querySelector('#api-state').textContent=s.api_configured?'已配置':'待配置';
  const privateScope=s.private_scope||(s.users?'selected':'off');
  document.querySelector('#group-state').textContent=(s.group_scope==='all'?'所有群聊':s.groups+' 个指定群')+' / '+(privateScope==='all'?'所有私聊':privateScope==='off'?'私聊已关闭':s.users+' 位联系人');
  document.querySelector('#instance-path').textContent=s.instance;
  document.querySelector('#memory-state').textContent=s.memory_enabled?'自动记忆已启用，实际检索状态可在完整管理台查看。':'自动记忆未启用；人格、手工背景和聊天历史仍保存在本机。';
  if(s.qq_tool) renderQQ(s.qq_tool);
}
function renderQQ(q) {
  loginAccount=q.account||'';
  const labels={missing:'QQ 组件待准备',preparing:'QQ 组件准备中',downloading:'正在下载 QQ 组件',extracting:'正在安装 QQ 组件',starting:'QQ 启动中',waiting_qr:'等待扫码登录',confirming:'等待手机确认',online:'QQ 已登录',mismatch:'QQ 账号不一致',error:'QQ 需要处理',stopped:'QQ 已停止'};
  document.querySelector('#qq-state').textContent=labels[q.phase]||'正在检查 QQ';
  document.querySelector('#qq-detail').textContent=q.message;
  document.querySelector('#qq-dialog-detail').textContent=q.message;
  document.querySelector('#qq-dot').classList.toggle('online',q.phase==='online');
  document.querySelector('#qq-account').textContent=q.account?'当前登录 QQ：'+q.account:'';
  const img=document.querySelector('#qq-qr');
  if(q.qr && q.qr.startsWith('data:image/svg+xml;base64,')) {if(img.src!==q.qr)img.src=q.qr;img.hidden=false;} else {img.hidden=true;img.removeAttribute('src');}
  document.querySelector('#qq-placeholder').hidden=!img.hidden;
  document.querySelector('#qq-placeholder').textContent=q.phase==='online'?'✓ 已登录':q.phase==='error'?'准备未完成':q.phase==='stopped'?'组件已停止':'二维码准备中';
  const progress=document.querySelector('#qq-progress');progress.hidden=!['downloading','extracting'].includes(q.phase);progress.value=q.progress||0;
  const dialog=document.querySelector('#qq-dialog');
  if(q.phase==='online') {if(!qqOnline){qqDismissed=false;if(dialog.open)dialog.close();}qqOnline=true;}
  else {if(qqOnline){qqOnline=false;qqDismissed=false;}if(q.qr&&!qqDismissed&&!dialog.open)dialog.showModal();}
}
function showQQ(){qqDismissed=false;document.querySelector('#qq-dialog').showModal();}
document.querySelector('#show-qq').addEventListener('click',showQQ);
document.querySelector('#connect-show-qq').addEventListener('click',showQQ);
document.querySelector('#close-qq').addEventListener('click',()=>{qqDismissed=true;document.querySelector('#qq-dialog').close();});
document.querySelector('#qq-dialog').addEventListener('cancel',()=>{qqDismissed=true;});
document.querySelector('#use-login-account').addEventListener('click',()=>{if(!loginAccount)return notice('QQ 尚未登录，请先扫码。',true);document.querySelector('[name=qq_account]').value=loginAccount;notice('已填入当前登录的小号，请保存连接设置。');});
function displayLog(line) { return line.replace('[麦麦推理引擎]','[大肥鱼推理引擎]').replace('[麦麦聊天循环]','[大肥鱼聊天循环]'); }
async function refreshLogs() { try { const data=await api('logs'); const el=document.querySelector('#log-content'); const atBottom=el.scrollHeight-el.scrollTop-el.clientHeight<60; el.textContent=data.lines.map(displayLog).join('\n')||'核心尚未启动。'; if(atBottom) el.scrollTop=el.scrollHeight; } catch(e) {notice(e.message,true);} }
for(const form of document.forms) if(form.id!=='fish-identity-form') form.addEventListener('submit',async event=>{
  event.preventDefault(); const body={};
  for(const field of form.elements) if(field.name && !field.disabled) body[field.name]=field.type==='checkbox'?field.checked:field.value;
  for(const name of ['groups','users']) if(name in body) body[name]=body[name].split(/[,，\s]+/).filter(Boolean);
  if('qq_port' in body) body.qq_port=Number(body.qq_port);
  const frequencyOnly=form.id==='participation-form';
  if(frequencyOnly) body.group_reply_frequency=Number(body.group_reply_frequency);
  const submit=form.querySelector('button[type=submit],button.primary');
  if(submit) submit.disabled=true;
  try { saved=await api(frequencyOnly?'participation':'settings',body); if(frequencyOnly) syncReplyFrequency(); else fill(); form.querySelectorAll('input[type=password]').forEach(e=>e.value=''); notice(frequencyOnly?'新话题概率已保存，正在运行的鱼会自动使用新设置。':'设置已保存，下次启动使用新配置。'); await refresh(); } catch(e) {notice(e.message,true);}
  finally {if(submit) submit.disabled=false;}
});
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',async()=>{
  if(busy) return; busy=true; button.disabled=true;
  const action=button.dataset.action;
  const originalLabel=button.textContent; button.textContent=action==='stop'?'正在保存并关停…':action==='package'?'正在生成纯净包…':'正在处理…';
  const popup=action==='advanced'?window.open('about:blank','fatfish-advanced'):null;
  try {
    const result=await api(action,action==='advanced'?undefined:{});
    if(action==='qq-start') {qqDismissed=false;showQQ();}
    if(action==='advanced') {
      const el=document.querySelector('#advanced-token'); el.textContent='MaiBot 登录令牌：'+result.token+'（仅在本机使用）'; el.hidden=false;
      if(popup) popup.location=result.url; else notice('管理台地址：'+result.url+'。登录令牌可在“数据与扩展”页查看。');
      page('manage');
    } else notice((result.message||'操作完成')+(result.reply?'：'+result.reply:'')+(result.path?'。位置：'+result.path:''));
    if(action==='quit') {exited=true;document.querySelector('#header-state').textContent='管理台已退出';} else await refresh();
  } catch(e) {if(popup)popup.close(); notice(e.message,true);}
  finally {busy=false;button.disabled=false;button.textContent=originalLabel;}
}));
document.querySelector('#show-connection').addEventListener('click',async()=>{try {const d=await api('connection');document.querySelector('#ws-address').textContent=d.address;document.querySelector('#ws-token').value=d.token;document.querySelector('#connection-guide').hidden=false;}catch(e){notice(e.message,true);}});
document.querySelector('#copy-token').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(document.querySelector('#ws-token').value);notice('接口令牌已复制。');}catch{notice('无法自动复制，请从输入框手动复制令牌。',true);}});
document.querySelector('#refresh-logs').addEventListener('click',refreshLogs);
document.querySelector('#show-credits').addEventListener('click',()=>document.querySelector('#credits-dialog').showModal());
document.querySelector('#close-credits').addEventListener('click',()=>document.querySelector('#credits-dialog').close());
document.querySelector('#download-release').addEventListener('click',async()=>{try{const r=await fetch('/api/download-release',{headers:{'X-Fatfish-Token':token}});if(!r.ok){const d=await r.json();throw new Error(d.error);}const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download='千鱼-0.3.14-纯净版.zip';a.click();setTimeout(()=>URL.revokeObjectURL(u),3000);}catch(e){notice(e.message,true);}});
(async()=>{try{saved=await api('settings');fill();await refresh();}catch(e){notice(e.message,true);}})();
setInterval(()=>{if(exited)return;refresh().catch(()=>{document.querySelector('#header-state').textContent='管理台连接断开';});if(document.querySelector('#logs').classList.contains('active'))refreshLogs();},4000);

async function openLibraryFolder(key) {
  try { const result=await api('open-library-folder',{key});notice(result.message+'：'+result.path); }
  catch(e){notice(e.message,true);}
}
async function refreshLibrary() {
  try {
    const data=await api('library');
    document.querySelector('#library-summary').textContent='可读取 '+data.index.count+' 份文件资料。'+data.index.method;
    const warnings=document.querySelector('#library-warnings');warnings.replaceChildren();
    for(const text of data.index.warnings){const p=document.createElement('p');p.textContent=text;warnings.append(p);}
    const container=document.querySelector('#library-folders');container.replaceChildren();
    for(const item of data.folders){
      const card=document.createElement('article');card.className='card';
      const title=document.createElement('h2');title.textContent=item.title;
      const desc=document.createElement('p');desc.textContent=item.description;
      const path=document.createElement('code');path.textContent=item.path;
      const button=document.createElement('button');button.textContent='打开文件夹';button.addEventListener('click',()=>openLibraryFolder(item.key));
      card.append(title,desc,path,button);container.append(card);
    }
    const list=document.querySelector('#library-files');list.replaceChildren();
    for(const file of data.index.documents){const li=document.createElement('li');li.textContent=file.name+' · '+file.characters+' 字符'+(file.pinned?' · 每轮附带开头':'');list.append(li);}
    if(!data.index.count){const li=document.createElement('li');li.textContent='还没有文件资料。放入 Markdown 或 TXT 后刷新。';list.append(li);}
    document.querySelector('#share-path').textContent=data.share;
  }catch(e){notice(e.message,true);}
}
document.querySelector('#refresh-library').addEventListener('click',refreshLibrary);
document.querySelector('#open-share').addEventListener('click',()=>openLibraryFolder('share'));

async function loadFishIdentities() {
  const data=await api('fish-identities'); const container=document.querySelector('#fish-identities'); container.replaceChildren();
  const labels={fish:'鱼',human:'真人',unknown:'待判断'};
  for(const row of data.people) {
    const item=document.createElement('p'); item.textContent=`${row.name||'未命名'} · ${row.user_id} · ${labels[row.status]||'待判断'}：${row.reason||'暂无依据'}`;
    container.append(item);
  }
  if(!data.people.length) container.textContent='还没有识别记录。';
}
document.querySelector('#fish-identity-form').addEventListener('submit',async event=>{
  event.preventDefault(); const form=event.currentTarget; const button=form.querySelector('button.primary'); button.disabled=true;
  try { await api('fish-identities',{user_id:form.elements.user_id.value.trim(),status:form.elements.status.value}); await loadFishIdentities(); notice('人物身份已纠正，下一条消息生效。'); }
  catch(error) {notice(error.message,true);} finally {button.disabled=false;}
});
document.querySelector('#reload-fish-identities').addEventListener('click',()=>loadFishIdentities().catch(error=>notice(error.message,true)));
document.querySelector('[data-page="persona"]').addEventListener('click',()=>loadFishIdentities().catch(error=>notice(error.message,true)));
