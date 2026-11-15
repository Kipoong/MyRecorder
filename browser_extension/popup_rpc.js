// Dedicated UI channel; explicit replies/handshake, separate from video events.
(() => {
  const BUILD='0.6.4';
  function error(code,message){const e=new Error(message);e.code=code;return e;}
  function create() {
    let port,closed=false;const pending=new Map();
    function failAll(reason){for(const item of pending.values()){clearTimeout(item.timer);item.reject(reason);}pending.clear();}
    try {port=chrome.runtime.connect({name:'myrecorder-ui-v1'});}
    catch {closed=true;}
    if(port) {
      port.onMessage.addListener(message=>{
        const item=pending.get(message?.request_id);if(!item)return;
        clearTimeout(item.timer);pending.delete(message.request_id);
        if(message.type!==item.type || !message.result || typeof message.result.ok!=='boolean')item.reject(error('UI_BAD_REPLY','팝업 응답 형식이 맞지 않습니다. 확장을 새로고침하세요.'));
        else item.resolve(message.result);
      });
      port.onDisconnect.addListener(()=>{
        void chrome.runtime.lastError;closed=true;
        failAll(error('UI_CHANNEL_CLOSED','백그라운드 UI 채널이 닫혔습니다. 확장 관리 화면에서 새로고침한 뒤 팝업을 닫고 다시 여세요. 토큰 재발급은 필요하지 않습니다.'));
      });
    }
    function send(type,fields={}) {
      if(closed || !port)return Promise.reject(error('UI_CHANNEL_CLOSED','확장 백그라운드에 연결되지 않았습니다. 확장을 새로고침하고 팝업을 다시 여세요.'));
      return new Promise((resolve,reject)=>{
        const request_id=crypto.randomUUID();
        const timer=setTimeout(()=>{pending.delete(request_id);reject(error('BACKGROUND_TIMEOUT','백그라운드 UI 응답이 10초 안에 오지 않았습니다. 확장을 새로고침하세요.'));},10000);
        pending.set(request_id,{resolve,reject,timer,type});
        try {port.postMessage({...fields,type,request_id});}
        catch {clearTimeout(timer);pending.delete(request_id);reject(error('UI_CHANNEL_CLOSED','확장 연결이 해제되었습니다. 팝업을 다시 여세요.'));}
      });
    }
    const ready=send('ui_hello').then(result=>{
      if(!result.ok) {
        const info=result.sender_info;
        const diagnostic=info?` (ID일치:${!!info.id_matches}, URL있음:${!!info.url_present}, 확장Origin:${!!info.origin_matches}, 탭있음:${!!info.has_tab})`:'';
        throw error(result.code||'UI_HANDSHAKE_FAILED',(result.error||'백그라운드 확인 실패')+diagnostic);
      }
      if(result.worker_build!==BUILD || result.manifest_version!==BUILD)
        {
          const safe=value=>typeof value==='string'&&/^\d+\.\d+\.\d+$/.test(value)?value:'확인 불가';
          throw error('UI_VERSION_MISMATCH',`팝업 ${BUILD} / 백그라운드 ${safe(result.worker_build)} / 설치 ${safe(result.manifest_version)}. 확장을 새로고침하고 팝업을 다시 여세요.`);
        }
      return result;
    });
    ready.catch(()=>{});
    return {get closed(){return closed;},ready,call:async(type,fields={})=>{await ready;return send(type,fields);},close:()=>{closed=true;port?.disconnect();failAll(error('UI_CHANNEL_CLOSED','팝업 종료'));}};
  }
  globalThis.PopupRpc={create,build:BUILD};
})();
