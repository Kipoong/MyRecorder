// MAIN world: only the explicitly selected video is intercepted. No secrets here.
(() => {
  if (window.__myRecorderGateInstalled) return;
  window.__myRecorderGateInstalled = true;
  const originalPlay = HTMLMediaElement.prototype.play;
  const originalPause = HTMLMediaElement.prototype.pause;
  const targets = new WeakMap();
  const pending = new WeakMap();
  const now = () => Date.now();
  window.addEventListener('myrecorder-config', event => {
    const d = event.detail;
    if (!d || typeof d.id !== 'string' || typeof d.channel !== 'string') return;
    const video = [...document.querySelectorAll('video')].find(v => v.dataset.myrecorderVideo === d.id);
    if (video) targets.set(video, {id:d.id, channel:d.channel, armed:d.armed === true});
  });
  HTMLMediaElement.prototype.play = function(...args) {
    const config = targets.get(this);
    if (!config?.armed || !(this instanceof HTMLVideoElement) || this.mediaKeys) return originalPlay.apply(this,args);
    if (pending.has(this)) return pending.get(this);
    const video = this, request = crypto.randomUUID();
    const promise = new Promise((resolve,reject) => {
      let timer;
      const cleanup = () => {clearTimeout(timer);window.removeEventListener('myrecorder-answer',answer);};
      const answer = event => {
        const d = event.detail;
        if (d?.request_id !== request || d.channel !== config.channel) return;
        cleanup();
        if (d.status !== 'ready') {reject(new DOMException(d.reason || '녹화 준비 실패','AbortError'));return;}
        const failed=error=>{window.dispatchEvent(new CustomEvent('myrecorder-play-failed',{detail:{id:config.id,channel:config.channel,request_id:request}}));reject(error);};
        try {Promise.resolve(originalPlay.apply(video,args)).then(resolve,failed);} catch(error) {failed(error);}
      };
      window.addEventListener('myrecorder-answer',answer);
      timer=setTimeout(() => {cleanup();reject(new DOMException('녹화 준비 시간 초과. 확장에서 연동을 해제하면 수동 재생할 수 있습니다.','AbortError'));},40000);
      window.dispatchEvent(new CustomEvent('myrecorder-request',{detail:{id:config.id,channel:config.channel,
        request_id:request,event_wall_ms:now(),media_time:video.currentTime}}));
    });
    pending.set(video,promise);
    promise.finally(() => pending.delete(video)).catch(() => {});
    return promise;
  };
  // A second click while preparing should cancel the pending playback.
  HTMLMediaElement.prototype.pause = function(...args) {
    const config=targets.get(this);
    if (config?.armed && pending.has(this)) window.dispatchEvent(new CustomEvent('myrecorder-cancel',{detail:{id:config.id,channel:config.channel}}));
    return originalPause.apply(this,args);
  };
})();
