// Pairing secrets stay in trusted extension session storage, never in the page.
let queue = Promise.resolve();
let seq = 0;
const instance = crypto.randomUUID();
async function post(payload) {
  const {pairing} = await chrome.storage.session.get('pairing');
  if (!pairing) throw new Error('확장 팝업에서 로컬 연결 정보를 입력하세요.');
  const response = await fetch(`http://127.0.0.1:${pairing.port}/v1/events`, {
    method: 'POST', cache: 'no-store', signal: AbortSignal.timeout(4000),
    headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${pairing.token}`,
              'X-MyRecorder-Extension': chrome.runtime.id},
    body: JSON.stringify({...payload, seq: ++seq})
  });
  if (!response.ok) throw new Error(`로컬 연결 거부 (${response.status}). 앱의 확장 ID/연결 정보를 확인하세요.`);
  return await response.json();
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
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
