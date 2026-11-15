document.querySelector('#id').textContent=chrome.runtime.id;
const status=document.querySelector('#status'),select=document.querySelector('#target');
const connect=document.querySelector('#connect'),refresh=document.querySelector('#refresh-tabs'),forget=document.querySelector('#disconnect');
const save=document.querySelector('#save-pairing'),input=document.querySelector('#pairing'),credentialStatus=document.querySelector('#credential-status'),fileInput=document.querySelector('#pairing-file');
let tabs=new Map(),busy=false,touched=false,paired=false,verified=false,dirty=false,generation=0;
function controls(value=busy) {
  busy=value;connect.disabled=value||!select.value||!paired||!verified||dirty;
  select.disabled=value;refresh.disabled=value;forget.disabled=value;save.disabled=value;fileInput.disabled=value;input.disabled=value;
}
function selectedLabel() {
  try {const value=PopupTabs.target(tabs.get(Number(select.value)));document.querySelector('#target-info').textContent=`연결 대상: ${value.title} | ${value.url.origin}`;}
  catch {document.querySelector('#target-info').textContent='연결할 HTTP/HTTPS 강의 탭을 선택하세요.';}
  controls();
}
function showError(error,fallback='CONNECTION_FAILED') {
  status.textContent=`[${error.code||fallback}] ${error.message||'연결 단계를 확인하세요.'}`;
}
let rpc;
function connectUi() {
  const client=PopupRpc.create();rpc=client;
  document.querySelector('#worker-status').textContent='백그라운드 UI 채널 연결 확인 중…';
  client.ready.then(info=>{if(rpc===client)document.querySelector('#worker-status').textContent=`백그라운드 ${info.worker_build} 응답 확인 · UI 채널 정상`;}).catch(error=>{if(rpc===client)document.querySelector('#worker-status').textContent=`[${error.code}] ${error.message}`;});
}
connectUi();
async function request(type,fields={}) {
  if(rpc.closed)connectUi();
  const result=await rpc.call(type,fields);
  if(!result.ok)throw PairingInput.error(result.code||'UI_BAD_REPLY',result.error||'확장 응답이 올바르지 않습니다.');
  return result;
}
input.addEventListener('input',()=>{
  touched=true;generation++;dirty=!!input.value.trim();verified=false;
  try {const value=PairingInput.parse(input.value);credentialStatus.textContent=`입력 형식 정상 · 포트 ${value.port} · 토큰 64자리 (내용 숨김) · 아직 저장 전`;
    status.textContent='① 앱 연결 저장·확인을 눌러야 저장됩니다. 붙여넣기만 하고 팝업을 닫으면 입력이 사라집니다.';}
  catch(error) {credentialStatus.textContent=dirty?'입력 형식 확인 필요 — 기존 저장 정보는 변경하지 않았습니다.':'입력칸 비어 있음';showError(error);}
  controls();
});
fileInput.addEventListener('change',async()=>{
  const file=fileInput.files?.[0];if(!file)return;
  try {
    if(file.size>8192)throw PairingInput.error('INPUT_TOO_LARGE','앱 연결 정보 JSON 파일만 선택하세요.');
    const text=await file.text();PairingInput.parse(text);input.value=text;input.dispatchEvent(new Event('input'));
  } catch(error) {showError(error,'FILE_READ_FAILED');}
  finally {fileInput.value='';}
});
save.addEventListener('click',async()=>{
  touched=true;generation++;controls(true);verified=false;
  try {
    if(input.value.trim()) {
      const pairing=PairingInput.parse(input.value);
      status.textContent='1/3 암호화 저장과 다시 읽기를 확인하는 중…';
      const result=await request('pairing_save',{pairing});
      if(!result.paired)throw PairingInput.error('STORE_NOT_CONFIRMED','저장 후 인증 정보가 확인되지 않았습니다.');
      paired=true;dirty=false;input.value='';credentialStatus.textContent=`암호화 저장·다시 읽기 확인 완료 · 포트 ${result.port}`;
    } else {
      const result=await request('pairing_status');paired=result.paired;
      if(!paired)throw PairingInput.error('INPUT_EMPTY','입력칸과 저장소가 모두 비어 있습니다. 앱의 JSON 본문을 붙여넣거나 JSON 파일을 선택하세요.');
      credentialStatus.textContent=`저장된 연결 사용 · 포트 ${result.port}`;
    }
    status.textContent='2/3 앱의 서명된 응답을 확인하는 중…';
    await request('pairing_verify');verified=true;
    credentialStatus.textContent+=' · 앱 응답 정상';
    status.textContent='3/3 앱 연결 확인 완료. 아래에서 강의 탭을 선택하고 ② 강의 탭 연결을 누르세요.';
  } catch(error) {showError(error);if(paired)credentialStatus.textContent+=' · 앱 확인 미완료 (인증 정보는 보존됨)';}
  finally {controls(false);}
});
async function loadTabs() {
  const previous=select.value;
  const [all,active]=await Promise.all([chrome.tabs.query({windowType:'normal'}),chrome.tabs.query({active:true,lastFocusedWindow:true})]);
  tabs=new Map();let missing=0;
  select.replaceChildren(new Option('강의 / 테스트 영상 탭을 선택하세요.',''));
  for (const tab of all) {
    try {
      const value=PopupTabs.target(tab);tabs.set(value.id,tab);
      select.add(new Option(`${value.title} | ${value.url.origin}`,String(value.id)));
    } catch(error) {if (error.code==='MISSING_URL')missing++;}
  }
  // Never silently pick an unrelated HTTP tab when the active tab is an internal page.
  if (tabs.has(Number(previous)) && previous) select.value=previous;
  else if (active[0] && tabs.has(active[0].id)) select.value=String(active[0].id);
  selectedLabel();
  if (!tabs.size) status.textContent=missing?'탭 주소 조회 권한이 없습니다. 확장을 새로고침하고 탭 정보 권한을 확인하세요.':'HTTP/HTTPS 테스트 영상이나 강의 페이지를 먼저 연 뒤 탭 목록 새로고침을 누르세요.';
  else if (!select.value) status.textContent='확장 자체 화면이나 내부 페이지에서는 자동 선택하지 않습니다. 위 목록에서 강의 탭을 직접 선택하세요.';
  else status.textContent='대상 탭을 확인하고 선택한 강의 탭 연결을 누르세요.';
}
select.addEventListener('change',()=>{touched=true;selectedLabel();if(select.value)status.textContent='대상 탭을 선택했습니다. 연결 버튼을 누르세요.';});
refresh.addEventListener('click',async()=>{touched=true;try{await loadTabs();}catch{status.textContent='탭 목록을 읽지 못했습니다. 확장 권한과 브라우저 창을 확인하세요.';}});
connect.addEventListener('click',async () => {
  touched=true;generation++;
  try {
    if(!paired||!verified||dirty)throw PairingInput.error('SAVE_FIRST','① 앱 연결 저장·확인을 먼저 완료하세요.');
    const chosen=PopupTabs.target(tabs.get(Number(select.value)));
    controls(true);status.textContent='선택한 강의 사이트 연결을 준비하는 중…';
    if (!await chrome.permissions.request({origins:[chosen.pattern]})) throw PairingInput.error('SITE_PERMISSION','선택한 강의 사이트 접근 권한이 필요합니다.');
    let current;
    try {current=PopupTabs.target(await chrome.tabs.get(chosen.id));}
    catch {throw PairingInput.error('TAB_CLOSED','선택한 탭이 닫혔거나 주소를 읽지 못했습니다. 탭 목록을 새로고침하세요.');}
    if (current.documentUrl!==chosen.documentUrl) throw PairingInput.error('TAB_CHANGED','선택한 탭의 주소가 바뀌었습니다. 목록을 새로고침하고 다시 선택하세요.');
    await request('pairing_verify');
    const suffix=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(current.url.origin));
    const id=[...new Uint8Array(suffix)].slice(0,8).map(v=>v.toString(16).padStart(2,'0')).join('');
    await request('site_remember',{pattern:current.pattern,id});
    try {
      await chrome.scripting.executeScript({target:{tabId:chosen.id},world:'MAIN',files:['gate.js']});
      await chrome.scripting.executeScript({target:{tabId:chosen.id},world:'ISOLATED',files:['content.js']});
    } catch {throw PairingInput.error('SCRIPT_INJECTION','페이지를 새로고침하고 사이트 접근 권한을 확인하세요.');}
    status.textContent='연결 저장 완료. 앱에서 해당 video를 선택하고 자동 감지를 켜세요. 이후에는 자동 재연결됩니다.';
  } catch(error) {showError(error);}
  finally {controls(false);}
});
forget.addEventListener('click',async () => {
  touched=true;generation++;controls(true);
  try {
    const result=await chrome.runtime.sendMessage({type:'pairing_forget'});
    if (!result?.ok) throw new Error(result?.error || '삭제 실패');
    await chrome.scripting.unregisterContentScripts();
    input.value='';paired=false;verified=false;dirty=false;credentialStatus.textContent='저장된 연결 없음 [CREDENTIALS_MISSING]';
    status.textContent='브라우저 인증 정보를 삭제했습니다. 앱의 연결 초기화도 누르고 새로 페어링하세요. 강의 페이지는 새로고침하세요.';
  } catch(error) {status.textContent=error.message||'삭제하지 못했습니다.';}
  finally {controls(false);}
});
(async()=>{
  const ticket=generation;
  try {
    await loadTabs();const result=await request('pairing_status');
    if(ticket!==generation)return;
    paired=result.paired;
    if(!paired) {credentialStatus.textContent='저장된 연결 없음 [CREDENTIALS_MISSING]';status.textContent='앱 JSON을 붙여넣고 ① 앱 연결 저장·확인을 누르세요.';controls();return;}
    credentialStatus.textContent=`저장된 연결 있음 · 포트 ${result.port}`;
    await request('pairing_verify');if(ticket!==generation)return;
    verified=true;credentialStatus.textContent+=' · 앱 응답 정상';
    if(!touched)status.textContent='저장된 연결의 앱 응답을 확인했습니다. 강의 탭을 선택하고 ②를 누르세요.';
  } catch(error) {if(ticket===generation)showError(error);}
  finally {controls();}
})();
