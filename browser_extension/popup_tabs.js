// URL metadata is optional in Chrome's Tab API. Never parse it unchecked.
(() => {
  function fail(code,message) {const error=new Error(message);error.code=code;throw error;}
  function target(tab) {
    if (!tab || !Number.isInteger(tab.id) || tab.id<0) fail('NO_TAB','연결할 강의 탭을 선택하세요.');
    if (typeof tab.url!=='string' || !tab.url.trim()) fail('MISSING_URL','탭 주소 조회 권한이 없습니다. 확장 V0.6.2를 새로고침하고 탭 정보 권한을 확인하세요.');
    let url;
    try {url=new URL(tab.url);} catch {fail('INVALID_URL','탭 주소를 확인하지 못했습니다. 강의 페이지를 완전히 연 뒤 탭 목록을 새로고침하세요.');}
    if (!['http:','https:'].includes(url.protocol) || !url.hostname) fail('UNSUPPORTED_URL','테스트 영상 또는 강의의 HTTP/HTTPS 탭을 선택하세요. 새 탭·확장 관리·확장 자체 화면은 연결 대상이 아닙니다.');
    if (url.username || url.password) fail('URL_CREDENTIALS','주소에 인증 정보가 포함된 탭은 지원하지 않습니다. 일반 강의 주소로 접속하세요.');
    const documentUrl=new URL(url.href);documentUrl.hash='';
    return {id:tab.id,title:String(tab.title||'제목 없음'),url,documentUrl:documentUrl.href,
            pattern:`${url.protocol}//${url.hostname}/*`};
  }
  globalThis.PopupTabs={target};
})();
