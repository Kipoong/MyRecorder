(() => {
  if (window.__myRecorderContentInstalled) return;
  window.__myRecorderContentInstalled=true;
  const channel=crypto.randomUUID();
  const videos=new Map();
  const active=new Map();
  const lastReady=new Map();
  const protectedVideos=new WeakSet();
  let selected=null, armed=false, status='연결 대기';
  function state(video) {
    if (!video || protectedVideos.has(video) || video.mediaKeys) return 'unsupported';
    return video.ended?'ended':video.paused?'paused':'playing';
  }
  function configure(id,video) {
    window.dispatchEvent(new CustomEvent('myrecorder-config',{detail:{id,channel,armed:armed&&selected===id&&state(video)!=='unsupported'}}));
  }
  async function send(id,kind,request_id,event_wall_ms=Date.now()) {
    const video=videos.get(id);
    const result=await chrome.runtime.sendMessage({type:'lecture_event',event:{video_id:id,kind,request_id,event_wall_ms,
      title:document.title,label:video?`video ${[...videos.keys()].indexOf(id)+1}`:'HTML5 video 없음',
      supported:state(video)!=='unsupported',state:state(video),gate:kind==='playing'?(request_id?'ready-ack':'observer'):'play-promise',media_time:video?.currentTime || 0}});
    if (!result?.ok) throw new Error(result?.error || '앱 연결 끊김');
    selected=result.selected_key===result.source_key?id:(selected===id?null:selected);
    armed=result.armed;status=result.message;
    for (const [key,v] of videos) configure(key,v);
    return result;
  }
  function error(message) {
    status=message;armed=false;
    for (const [id,video] of videos) configure(id,video);
    document.documentElement.dataset.myrecorderStatus=message; // no token/URL here
  }
  function scan() {
    for (const [id,video] of videos) if (!video.isConnected) {
      send(id,'disconnect').catch(()=>{});videos.delete(id);
    }
    for (const video of document.querySelectorAll('video')) {
      if ([...videos.values()].includes(video) || videos.size>=16) continue;
      const id=crypto.randomUUID();videos.set(id,video);video.dataset.myrecorderVideo=id;
      for (const kind of ['pause','playing','ended']) video.addEventListener(kind,() => {
        const request_id=kind==='playing'?lastReady.get(id):undefined;
        if (kind==='playing') lastReady.delete(id);
        send(id,kind,request_id).catch(e=>error(e.message));
      });
      for (const kind of ['waiting','stalled']) video.addEventListener(kind,() => send(id,'buffering').catch(e=>error(e.message)));
      video.addEventListener('encrypted',() => {protectedVideos.add(video);send(id,'unsupported').catch(e=>error(e.message));});
    }
  }
  window.addEventListener('myrecorder-request',async event => {
    const d=event.detail;
    if (!d || d.channel!==channel || !videos.has(d.id) || selected!==d.id || !armed) return;
    const cancel={cancelled:false,request_id:d.request_id};active.set(d.id,cancel);
    try {
      let response=await send(d.id,'prepare',d.request_id,d.event_wall_ms);
      const deadline=Date.now()+36000;
      while (response.reply?.status==='pending' && Date.now()<deadline && !cancel.cancelled) {
        await new Promise(resolve=>setTimeout(resolve,100));
        response=await send(d.id,'poll',d.request_id);
      }
      const reply=cancel.cancelled?{status:'blocked',reason:'재생 취소'}:response.reply;
      if (reply?.status==='ready') lastReady.set(d.id,d.request_id);
      window.dispatchEvent(new CustomEvent('myrecorder-answer',{detail:{channel,request_id:d.request_id,...reply}}));
      if (reply?.status!=='ready') error(reply?.reason || '녹화 준비 실패');
    } catch(e) {
      window.dispatchEvent(new CustomEvent('myrecorder-answer',{detail:{channel,request_id:d.request_id,status:'blocked',reason:e.message}}));
      error(e.message);
    } finally {if (active.get(d.id)===cancel) active.delete(d.id);}
  });
  window.addEventListener('myrecorder-play-failed',event => {
    const d=event.detail;
    if (d?.channel===channel && videos.has(d.id)) send(d.id,'play_failed',d.request_id).catch(e=>error(e.message));
  });
  window.addEventListener('myrecorder-cancel',event => {
    const d=event.detail;
    if (d?.channel!==channel) return;
    const request=active.get(d.id);
    if (request) {request.cancelled=true;send(d.id,'pause').catch(e=>error(e.message));}
  });
  setInterval(async () => {
    scan();
    try {
      if (!videos.size) await send('no-video','unsupported');
      for (const id of videos.keys()) await send(id,'snapshot');
      document.documentElement.dataset.myrecorderStatus=status;
    } catch(e) {error(e.message);}
  },1000);
  scan();
})();
