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
function connectionError(code,message){const e=new Error(message);e.code=code;return e;}
async function post(payload) {
  const pairing = await PairingVault.load();
  if (!pairing) throw connectionError('CREDENTIALS_MISSING','확장에 저장된 인증 정보가 없습니다. ① 앱 연결 저장·확인을 누르세요.');
  const body=JSON.stringify({...payload,seq:++seq});
  const nonce=[...crypto.getRandomValues(new Uint8Array(32))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const stamp=String(Date.now()),encode=value=>new TextEncoder().encode(value);
  const key=await crypto.subtle.importKey('raw',encode(pairing.token),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);
  const signature=await crypto.subtle.sign('HMAC',key,encode(`POST\n/v1/events\n${stamp}\n${nonce}\n${body}`));
  const hex=bytes=>[...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
  let response;
  try {response = await fetch(`http://127.0.0.1:${pairing.port}/v1/events`, {
    method:'POST',cache:'no-store',signal:AbortSignal.timeout(4000),
    headers:{'Content-Type':'application/json','Authorization':`MyRecorder-HMAC ${hex(signature)}`,
      'X-MyRecorder-Extension':chrome.runtime.id,'X-MyRecorder-Nonce':nonce,'X-MyRecorder-Time':stamp},body
  });
  } catch {throw connectionError('APP_UNREACHABLE','앱에 연결하지 못했습니다. MyRecorder 실행 상태와 연결 포트를 확인하세요.');}
  if (response.status===403) throw connectionError('AUTH_REJECTED','앱이 인증을 거부했습니다. 앱의 확장 ID와 현재 연결 JSON이 일치하는지 확인하세요.');
  if (response.status===400 && payload.kind==='ping') throw connectionError('APP_UPDATE_REQUIRED','MyRecorder 앱도 V0.6.3으로 업데이트한 뒤 실행하세요.');
  if (!response.ok) throw connectionError('APP_HTTP_ERROR',`앱 응답 오류 (${response.status})`);
  const text=await response.text(),proof=response.headers.get('X-MyRecorder-Proof');
  if (!/^[a-f0-9]{64}$/.test(proof||'')) throw connectionError('APP_PROOF_INVALID','앱 응답 서명을 확인하지 못했습니다. 연결 포트를 확인하세요.');
  const bytes=new Uint8Array(proof.match(/../g).map(v=>parseInt(v,16)));
  if (!await crypto.subtle.verify('HMAC',key,bytes,encode(`response\n${nonce}\n${text}`))) throw connectionError('APP_PROOF_INVALID','앱 응답 서명을 확인하지 못했습니다. 연결 포트를 확인하세요.');
  return JSON.parse(text);
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id===chrome.runtime.id && sender.url===chrome.runtime.getURL('popup.html') && ['pairing_save','pairing_status','pairing_verify','pairing_forget','site_remember'].includes(message?.type)) {
    (async()=>{
      if (message.type==='pairing_save') {
        try {await PairingVault.save(message.pairing);if (!await PairingVault.verify()) throw new Error('missing readback');}
        catch {throw connectionError('STORE_WRITE_FAILED','브라우저 암호화 저장/다시 읽기 확인에 실패했습니다. 저장소 권한이나 프로필을 확인하세요.');}
      }
      if (message.type==='pairing_verify') {
        const pairing=await PairingVault.load();
        if (!pairing) throw connectionError('CREDENTIALS_MISSING','저장된 인증 정보가 없습니다. ① 앱 연결 저장·확인을 누르세요.');
        const reply=await post({kind:'ping'});
        if (reply.connection!=='ready') throw connectionError('APP_PROTOCOL','앱 연결 확인 응답이 올바르지 않습니다.');
        return {ok:true,paired:true,verified:true,port:pairing.port};
      }
      if (message.type==='pairing_forget') {await PairingVault.forget();await chrome.storage.local.remove('paired_sites');}
      if (message.type==='site_remember') {
        if (!/^https?:\/\/[^/ *]+\/\*$/.test(message.pattern)||!/^[a-f0-9]{16}$/.test(message.id)) throw new Error('invalid site');
        const {paired_sites=[]}=await chrome.storage.local.get('paired_sites');
        const sites=paired_sites.filter(site=>site.pattern!==message.pattern);
        if (sites.length>=32) throw new Error('too many sites');
        sites.push({pattern:message.pattern,id:message.id});await chrome.storage.local.set({paired_sites:sites});await restoreQueued();
      }
      const stored=await PairingVault.load();
      return {ok:true,paired:!!stored,port:stored?.port};
    })().then(respond).catch(error=>respond({ok:false,code:error.code||'STORE_READ_FAILED',error:error.code?error.message:'저장한 인증 정보 읽기에 실패했습니다. 브라우저 프로필을 확인하세요.'}));
    return true;
  }
  if (message?.type !== 'lecture_event' || sender.id !== chrome.runtime.id || !sender.tab || sender.frameId !== 0) return;
  const event = message.event;
  if (!event || typeof event.video_id !== 'string' || !/^[A-Za-z0-9_-]{1,60}$/.test(event.video_id)) return;
  let pageOrigin;
  try {const url=new URL(sender.url);if (!['http:','https:'].includes(url.protocol)) throw new Error('unsupported');pageOrigin=url.origin;}
  catch {respond({ok:false,error:'강의 페이지 주소를 확인할 수 없습니다. 페이지를 새로고침하세요.'});return false;}
  const source = {
    key: `${instance}:${sender.tab.id}:${sender.documentId || 'document'}:${event.video_id}`,
    title: String(sender.tab.title || event.title || '제목 없음').slice(0,500),
    origin: pageOrigin, video_label: String(event.label || 'HTML5 video').slice(0,100),
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
