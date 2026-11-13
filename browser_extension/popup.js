document.querySelector('#id').textContent=chrome.runtime.id;
const status=document.querySelector('#status');
document.querySelector('#connect').addEventListener('click',async () => {
  try {
    const pairing=JSON.parse(document.querySelector('#pairing').value);
    if (!Number.isInteger(pairing.port)||pairing.port<1||pairing.port>65535||!/^[a-f0-9]{64}$/.test(pairing.token)) throw new Error('앱 연결 정보를 확인하세요.');
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const url=new URL(tab.url);
    if (!['http:','https:'].includes(url.protocol)) throw new Error('HTTP/HTTPS 강의 페이지에서 사용하세요.');
    const pattern=`${url.protocol}//${url.hostname}/*`;
    if (!await chrome.permissions.request({origins:[pattern]})) throw new Error('선택한 강의 사이트 접근 권한이 필요합니다.');
    await chrome.storage.session.set({pairing});
    const suffix=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(url.origin));
    const id=[...new Uint8Array(suffix)].slice(0,8).map(v=>v.toString(16).padStart(2,'0')).join('');
    await chrome.scripting.unregisterContentScripts({ids:[`gate-${id}`,`observer-${id}`]}).catch(()=>{});
    await chrome.scripting.registerContentScripts([
      {id:`gate-${id}`,matches:[pattern],js:['gate.js'],runAt:'document_start',world:'MAIN',persistAcrossSessions:false},
      {id:`observer-${id}`,matches:[pattern],js:['content.js'],runAt:'document_start',world:'ISOLATED',persistAcrossSessions:false}
    ]);
    await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['gate.js']});
    await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',files:['content.js']});
    status.textContent='연결 요청됨. 앱에서 정확한 video 탭을 선택하고 자동 감지를 켜세요. 처음 재생 전에 준비 완료를 확인하세요.';
  } catch(e) {status.textContent=e.message;}
});
document.querySelector('#disconnect').addEventListener('click',async () => {
  await chrome.storage.session.remove('pairing');
  await chrome.scripting.unregisterContentScripts();
  status.textContent='해제했습니다. 앱은 연결 끊김을 표시합니다. 열린 페이지를 새로고침하면 play 래퍼도 제거됩니다.';
});
