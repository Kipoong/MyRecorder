// Persistent encrypted pairing is accessible only to trusted extension contexts.
importScripts('vault.js');
let siteQueue=Promise.resolve();
async function restoreSites() {
  const {paired_sites=[]}=await chrome.storage.local.get('paired_sites');
  if (!await PairingVault.load()) return;
  const registered=await chrome.scripting.getRegisteredContentScripts();
  for (const site of paired_sites) {
    if (!await chrome.permissions.contains({origins:[site.pattern]})) continue;
    const scripts=[{id:`gate-${site.id}`,matches:[site.pattern],js:['gate.js'],world:'MAIN',runAt:'document_start',persistAcrossSessions:true},
      {id:`observer-${site.id}`,matches:[site.pattern],js:['content.js'],world:'ISOLATED',runAt:'document_start',persistAcrossSessions:true}];
    const missing=scripts.filter(script=>!registered.some(old=>old.id===script.id));
    if (missing.length) await chrome.scripting.registerContentScripts(missing);
    // Restored tabs can load before dynamic script registration; inject only into approved sites.
    const tabs=await chrome.tabs.query({url:[site.pattern]});
    for (const tab of tabs) if (tab.id) {
      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['gate.js']}).catch(()=>{});
      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',files:['content.js']}).catch(()=>{});
    }
  }
}
function restoreQueued(){siteQueue=siteQueue.catch(()=>{}).then(restoreSites);return siteQueue;}
restoreQueued().catch(()=>{});
chrome.runtime.onStartup.addListener(()=>restoreQueued().catch(()=>{}));
chrome.runtime.onInstalled.addListener(()=>restoreQueued().catch(()=>{}));
let queue = Promise.resolve();
let seq = 0;
const instance = crypto.randomUUID();
async function post(payload) {
  const pairing = await PairingVault.load();
  if (!pairing) throw new Error('확장 팝업에서 로컬 연결 정보를 입력하세요.');
  const body=JSON.stringify({...payload,seq:++seq});
  const nonce=[...crypto.getRandomValues(new Uint8Array(32))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const stamp=String(Date.now()),encode=value=>new TextEncoder().encode(value);
  const key=await crypto.subtle.importKey('raw',encode(pairing.token),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);
  const signature=await crypto.subtle.sign('HMAC',key,encode(`POST\n/v1/events\n${stamp}\n${nonce}\n${body}`));
  const hex=bytes=>[...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
  const response = await fetch(`http://127.0.0.1:${pairing.port}/v1/events`, {
    method:'POST',cache:'no-store',signal:AbortSignal.timeout(4000),
    headers:{'Content-Type':'application/json','Authorization':`MyRecorder-HMAC ${hex(signature)}`,
      'X-MyRecorder-Extension':chrome.runtime.id,'X-MyRecorder-Nonce':nonce,'X-MyRecorder-Time':stamp},body
  });
  if (!response.ok) throw new Error(`로컬 연결 거부 (${response.status}). 앱 연결 초기화 여부를 확인하세요.`);
  const text=await response.text(),proof=response.headers.get('X-MyRecorder-Proof');
  if (!/^[a-f0-9]{64}$/.test(proof||'')) throw new Error('MyRecorder 응답 인증 실패');
  const bytes=new Uint8Array(proof.match(/../g).map(v=>parseInt(v,16)));
  if (!await crypto.subtle.verify('HMAC',key,bytes,encode(`response\n${nonce}\n${text}`))) throw new Error('MyRecorder 응답 인증 실패');
  return JSON.parse(text);
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id===chrome.runtime.id && sender.url===chrome.runtime.getURL('popup.html') && ['pairing_save','pairing_status','pairing_forget','site_remember'].includes(message?.type)) {
    (async()=>{
      if (message.type==='pairing_save') await PairingVault.save(message.pairing);
      if (message.type==='pairing_forget') {await PairingVault.forget();await chrome.storage.local.remove('paired_sites');}
      if (message.type==='site_remember') {
        if (!/^https?:\/\/[^/ *]+\/\*$/.test(message.pattern)||!/^[a-f0-9]{16}$/.test(message.id)) throw new Error('invalid site');
        const {paired_sites=[]}=await chrome.storage.local.get('paired_sites');
        const sites=paired_sites.filter(site=>site.pattern!==message.pattern);
        if (sites.length>=32) throw new Error('too many sites');
        sites.push({pattern:message.pattern,id:message.id});await chrome.storage.local.set({paired_sites:sites});await restoreQueued();
      }
      return {ok:true,paired:!!await PairingVault.load()};
    })().then(respond).catch(()=>respond({ok:false,error:'저장한 연결 복원/변경 실패. 연결 정보를 삭제하고 다시 페어링하세요.'}));
    return true;
  }
  if (message?.type !== 'lecture_event' || sender.id !== chrome.runtime.id || !sender.tab || sender.frameId !== 0) return;
  const event = message.event;
  if (!event || typeof event.video_id !== 'string' || !/^[A-Za-z0-9_-]{1,60}$/.test(event.video_id)) return;
  const source = {
    key: `${instance}:${sender.tab.id}:${sender.documentId || 'document'}:${event.video_id}`,
    title: String(sender.tab.title || event.title || '제목 없음').slice(0,500),
    origin: new URL(sender.url).origin, video_label: String(event.label || 'HTML5 video').slice(0,100),
    state: event.state, supported: event.supported === true, gate: String(event.gate || 'observer').slice(0,100)
  };
  const payload = {kind:event.kind, source, request_id:event.request_id,
                   event_wall_ms:event.event_wall_ms,media_time:event.media_time};
  const task = queue.then(() => post(payload));
  queue = task.catch(() => {});
  task.then(result => respond({ok:true, ...result, source_key:source.key}))
      .catch(error => respond({ok:false,error:error.message}));
  return true;
});
