document.querySelector('#id').textContent=chrome.runtime.id;
const status=document.querySelector('#status'),select=document.querySelector('#target');
const connect=document.querySelector('#connect'),refresh=document.querySelector('#refresh-tabs'),forget=document.querySelector('#disconnect');
let tabs=new Map(),busy=false,touched=false;
function controls(value) {
  busy=value;connect.disabled=value||!select.value;select.disabled=value;refresh.disabled=value;forget.disabled=value;
}
function selectedLabel() {
  try {const value=PopupTabs.target(tabs.get(Number(select.value)));document.querySelector('#target-info').textContent=`연결 대상: ${value.title} | ${value.url.origin}`;}
  catch {document.querySelector('#target-info').textContent='연결할 HTTP/HTTPS 강의 탭을 선택하세요.';}
  if (!busy)connect.disabled=!select.value;
}
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
  touched=true;
  try {
    const text=document.querySelector('#pairing').value.trim();let pairing=null;
    try {pairing=text?JSON.parse(text):null;} catch {throw new Error('앱 연결 정보는 JSON 전체를 복사해 입력하세요.');}
    if (pairing && (!Number.isInteger(pairing.port)||pairing.port<1||pairing.port>65535||!/^[a-f0-9]{64}$/.test(pairing.token))) throw new Error('앱 연결 정보를 확인하세요.');
    const chosen=PopupTabs.target(tabs.get(Number(select.value)));
    controls(true);status.textContent='선택한 강의 사이트 연결을 준비하는 중…';
    // Request permission directly from the click gesture, before other awaited API calls.
    if (!await chrome.permissions.request({origins:[chosen.pattern]})) throw new Error('선택한 강의 사이트 접근 권한이 필요합니다.');
    let current;
    try {current=PopupTabs.target(await chrome.tabs.get(chosen.id));}
    catch {throw new Error('선택한 탭이 닫혔거나 주소를 읽지 못했습니다. 탭 목록을 새로고침하고 다시 선택하세요.');}
    if (current.documentUrl!==chosen.documentUrl) throw new Error('선택한 탭의 주소가 바뀌었습니다. 탭 목록을 새로고침하고 다시 선택하세요.');
    const result=await chrome.runtime.sendMessage(pairing?{type:'pairing_save',pairing}:{type:'pairing_status'});
    if (!result?.ok || !result.paired) throw new Error(result?.error || '처음 한 번 앱 연결 정보를 입력하세요.');
    document.querySelector('#pairing').value='';
    const suffix=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(current.url.origin));
    const id=[...new Uint8Array(suffix)].slice(0,8).map(v=>v.toString(16).padStart(2,'0')).join('');
    const remembered=await chrome.runtime.sendMessage({type:'site_remember',pattern:current.pattern,id});
    if (!remembered?.ok) throw new Error(remembered?.error || '사이트 연결 저장 실패');
    try {
      await chrome.scripting.executeScript({target:{tabId:chosen.id},world:'MAIN',files:['gate.js']});
      await chrome.scripting.executeScript({target:{tabId:chosen.id},world:'ISOLATED',files:['content.js']});
    } catch {throw new Error('선택한 페이지에 감지 기능을 연결하지 못했습니다. 페이지 새로고침과 해당 사이트 접근 권한을 확인하세요.');}
    status.textContent='연결 저장 완료. 앱에서 해당 video를 선택하고 자동 감지를 켜세요. 이후에는 자동 재연결됩니다.';
  } catch(error) {status.textContent=error.message||'연결하지 못했습니다. 탭과 확장 권한을 확인하세요.';}
  finally {controls(false);}
});
forget.addEventListener('click',async () => {
  touched=true;controls(true);
  try {
    const result=await chrome.runtime.sendMessage({type:'pairing_forget'});
    if (!result?.ok) throw new Error(result?.error || '삭제 실패');
    await chrome.scripting.unregisterContentScripts();
    document.querySelector('#pairing').value='';
    status.textContent='브라우저 인증 정보를 삭제했습니다. 앱의 연결 초기화도 누르고 새로 페어링하세요. 강의 페이지는 새로고침하세요.';
  } catch(error) {status.textContent=error.message||'삭제하지 못했습니다.';}
  finally {controls(false);}
});
(async()=>{
  try {
    await loadTabs();
    const result=await chrome.runtime.sendMessage({type:'pairing_status'});
    if (!touched && result?.paired && select.value) status.textContent='저장한 연결을 사용할 수 있습니다. 위 대상 탭을 확인하세요. 토큰 재입력은 필요 없습니다.';
  } catch {if (!touched) status.textContent='탭 목록을 읽지 못했습니다. 확장 V0.6.2의 탭 정보 권한을 확인하고 목록을 새로고침하세요.';}
})();
