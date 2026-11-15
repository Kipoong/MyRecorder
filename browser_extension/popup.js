document.querySelector('#id').textContent=chrome.runtime.id;
const status=document.querySelector('#status');
document.querySelector('#connect').addEventListener('click',async () => {
  try {
    const text=document.querySelector('#pairing').value.trim();
    const pairing=text?JSON.parse(text):null;
    if (pairing && (!Number.isInteger(pairing.port)||pairing.port<1||pairing.port>65535||!/^[a-f0-9]{64}$/.test(pairing.token))) throw new Error('앱 연결 정보를 확인하세요.');
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const url=new URL(tab.url);
    if (!['http:','https:'].includes(url.protocol)) throw new Error('HTTP/HTTPS 강의 페이지에서 사용하세요.');
    const pattern=`${url.protocol}//${url.hostname}/*`;
    if (!await chrome.permissions.request({origins:[pattern]})) throw new Error('선택한 강의 사이트 접근 권한이 필요합니다.');
    const result=await chrome.runtime.sendMessage(pairing?{type:'pairing_save',pairing}:{type:'pairing_status'});
    if (!result?.ok || !result.paired) throw new Error(result?.error || '처음 한 번 앱 연결 정보를 입력하세요.');
    document.querySelector('#pairing').value='';
    const suffix=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(url.origin));
    const id=[...new Uint8Array(suffix)].slice(0,8).map(v=>v.toString(16).padStart(2,'0')).join('');
    const remembered=await chrome.runtime.sendMessage({type:'site_remember',pattern,id});
    if (!remembered?.ok) throw new Error(remembered?.error || '사이트 연결 저장 실패');
    await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['gate.js']});
    await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',files:['content.js']});
    status.textContent='연결 저장 완료. 다음에는 자동 재연결됩니다. 녹화하려면 앱에서 video를 선택하고 자동 감지를 켜세요.';
  } catch(e) {status.textContent=e.message;}
});
document.querySelector('#disconnect').addEventListener('click',async () => {
  const result=await chrome.runtime.sendMessage({type:'pairing_forget'});
  if (!result?.ok) {status.textContent=result?.error || '삭제 실패';return;}
  await chrome.scripting.unregisterContentScripts();
  status.textContent='브라우저 인증 정보와 자동 연결을 삭제했습니다. 완전히 폐기하려면 앱의 연결 초기화도 누르세요. 열린 페이지는 새로고침하세요.';
});

chrome.runtime.sendMessage({type:'pairing_status'}).then(result=>{if(result?.paired) status.textContent='저장한 연결 사용 중 — 토큰 입력 없이 자동 재연결됩니다. 새 사이트만 현재 강의 탭 연결을 누르세요.';}).catch(()=>{});
