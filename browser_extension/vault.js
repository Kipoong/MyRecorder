// Ciphertext in storage.local; non-extractable AES-GCM key in this extension's IndexedDB.
// This is browser-profile storage, not a claim of Windows DPAPI for IndexedDB.
(() => {
  let cached;
  function valid(pairing) {
    if (!pairing || !Number.isInteger(pairing.port) || pairing.port<1 || pairing.port>65535 || !/^[a-f0-9]{64}$/.test(pairing.token)) throw new Error('연결 정보를 확인하세요.');
    return {port:pairing.port,token:pairing.token};
  }
  async function database() {
    return await new Promise((resolve,reject)=>{
      const request=indexedDB.open('myrecorder-pairing',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('keys');
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('브라우저 키 저장소를 열지 못했습니다.'));
    });
  }
  async function key(create=false) {
    const db=await database();
    try {
      let existing=await new Promise((resolve,reject)=>{
        const request=db.transaction('keys').objectStore('keys').get('aes');
        request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('키 조회 실패'));
      });
      if (!existing && create) {
        existing=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
        await new Promise((resolve,reject)=>{
          const transaction=db.transaction('keys','readwrite');transaction.objectStore('keys').put(existing,'aes');
          transaction.oncomplete=resolve;transaction.onerror=()=>reject(new Error('키 저장 실패'));
        });
      }
      return existing;
    } finally {db.close();}
  }
  const aad=()=>new TextEncoder().encode(`MyRecorder:${chrome.runtime.id}:v1`);
  async function save(pairing) {
    pairing=valid(pairing);
    const secret=await key(true),iv=crypto.getRandomValues(new Uint8Array(12));
    const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad()},secret,new TextEncoder().encode(JSON.stringify(pairing)));
    await chrome.storage.local.set({pairing_cipher:{version:1,iv:[...iv],data:[...new Uint8Array(encrypted)]}});
    await chrome.storage.session.remove('pairing');cached=pairing;
  }
  async function load() {
    if (cached) return cached;
    const {pairing_cipher}=await chrome.storage.local.get('pairing_cipher');
    if (pairing_cipher) {
      try {
        if (pairing_cipher.version!==1 || pairing_cipher.data.length>4096) throw new Error('bad data');
        const secret=await key();if (!secret) throw new Error('missing key');
        const clear=await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(pairing_cipher.iv),additionalData:aad()},secret,new Uint8Array(pairing_cipher.data));
        cached=valid(JSON.parse(new TextDecoder().decode(clear)));return cached;
      } catch {throw new Error('저장한 연결 복원 실패. 확장에서 연결 정보를 삭제하고 다시 페어링하세요.');}
    }
    // Upgrade an existing V0.6 session without leaving plaintext persistent storage.
    const {pairing}=await chrome.storage.session.get('pairing');
    if (pairing) {await save(pairing);return cached;}
    return null;
  }
  async function forget() {
    cached=undefined;await chrome.storage.local.remove('pairing_cipher');await chrome.storage.session.remove('pairing');
    const db=await database();
    try {await new Promise((resolve,reject)=>{
      const tx=db.transaction('keys','readwrite');tx.objectStore('keys').delete('aes');
      tx.oncomplete=resolve;tx.onerror=()=>reject(new Error('키 삭제 실패'));
    });} finally {db.close();}
  }
  // Serialize reads/writes so a delayed decrypt cannot resurrect credentials after forget.
  let operations=Promise.resolve();
  function serial(action) {const next=operations.catch(()=>{}).then(action);operations=next.catch(()=>{});return next;}
  globalThis.PairingVault={save:value=>serial(()=>save(value)),load:()=>serial(load),forget:()=>serial(forget),key:create=>serial(()=>key(create))};
})();
