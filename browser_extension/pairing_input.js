(() => {
  function error(code,message) {const e=new Error(message);e.code=code;return e;}
  function parse(text) {
    if (typeof text!=='string'||!text.trim()) throw error('INPUT_EMPTY','연결 정보 입력칸이 비어 있습니다. 앱의 JSON 전체를 붙여넣으세요.');
    if (text.length>8192) throw error('INPUT_TOO_LARGE','연결 정보가 너무 큽니다. 앱의 연결 JSON만 입력하세요.');
    let value;try{value=JSON.parse(text.trim());}catch{throw error('INPUT_JSON','JSON을 읽지 못했습니다. 파일 이름이나 경로가 아닌 JSON 본문을 입력하세요.');}
    if (!value||typeof value!=='object'||Array.isArray(value)||!Number.isInteger(value.port)||value.port<1||value.port>65535||typeof value.token!=='string'||!/^[a-f0-9]{64}$/.test(value.token))
      throw error('INPUT_SCHEMA','port 숫자와 64자리 token이 있는 앱 연결 JSON이 필요합니다.');
    return {port:value.port,token:value.token};
  }
  globalThis.PairingInput={parse,error};
})();
