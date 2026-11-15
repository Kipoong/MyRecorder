"""Real popup UI channel and authorization; version mismatch is injected, not a Windows test."""
import functools,json,tempfile,threading,time
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from myrecorder.browser_bridge import Bridge
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def wait(predicate):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.04)
    raise AssertionError('UI channel condition timed out')

extension=Path(__file__).resolve().parents[1]/'browser_extension'
with tempfile.TemporaryDirectory(prefix='ui-channel-example-') as d:
    root=Path(d);(root/'index.html').write_text('<title>UI channel example</title><video></video>')
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();bridge=None
    try:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(root/'profile'),channel='chromium',headless=True,
                ignore_default_args=['--disable-extensions'],args=['--no-sandbox',f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            try:
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                extension_id=worker.url.split('/')[2];bridge=Bridge(extension_id,signed_only=True);bridge.start()
                web=context.new_page();web.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                popup=context.new_page();popup.goto(worker.url.replace('background.js','popup.html?context=diagnostic#view'))
                wait(lambda:'백그라운드 0.6.4 응답 확인' in popup.locator('#worker-status').inner_text())
                popup.fill('#pairing',json.dumps(bridge.pairing));popup.click('#save-pairing')
                wait(lambda:'앱 응답 정상' in popup.locator('#credential-status').inner_text())
                assert bridge.snapshot()==[] and bridge.drain()==[] and not bridge.armed
                popup.evaluate('()=>rpc.close()');popup.click('#save-pairing')
                wait(lambda:'앱 응답 정상' in popup.locator('#credential-status').inner_text() and popup.locator('#save-pairing').is_enabled())
                # Compatibility messages from the same packaged UI with a query also receive a reply.
                result=popup.evaluate("()=>chrome.runtime.sendMessage({type:'pairing_status'})")
                assert result['ok'] and result['paired']
                # A real content-script origin must not gain vault authority through the new port.
                denied=worker.evaluate('''async url=>{
                    const tab=(await chrome.tabs.query({})).find(t=>t.url===url);
                    const result=await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',func:()=>new Promise(resolve=>{
                      const port=chrome.runtime.connect({name:'myrecorder-ui-v1'});
                      port.onMessage.addListener(message=>{resolve(message.result);port.disconnect();});
                      port.postMessage({type:'pairing_forget',request_id:'untrusted-test'});
                    })});return result[0].result;
                }''',web.url)
                assert denied['code']=='UI_SENDER_REJECTED'
                assert worker.evaluate('async()=>!!await PairingVault.load()')
                # Mixed worker version must block secret-bearing commands before they are sent.
                mismatch=popup.evaluate('''async()=>{
                    const original=chrome.runtime.connect,types=[];
                    chrome.runtime.connect=()=>{
                      let listener;return {onMessage:{addListener:fn=>listener=fn},onDisconnect:{addListener:()=>{}},disconnect:()=>{},
                        postMessage:message=>{types.push(message.type);setTimeout(()=>listener({request_id:message.request_id,type:message.type,result:{ok:true,worker_build:'0.6.3',manifest_version:'0.6.4'}}),0);}};
                    };
                    try {const client=PopupRpc.create();try{await client.call('pairing_save',{pairing:{test:'not sent'}});return {code:'unexpected',types};}catch(error){return {code:error.code,types};}}
                    finally {chrome.runtime.connect=original;}
                }''')
                assert mismatch=={'code':'UI_VERSION_MISMATCH','types':['ui_hello']}
                assert bridge.token not in popup.locator('#worker-status').inner_text()
                print('Actual Chromium: query/fragment popup handshake and encrypted save/app check: PASS')
                print('Content-script vault access denied; injected worker mismatch blocks secret commands: PASS')
            finally:context.close()
    finally:
        if bridge:bridge.close()
        server.shutdown();server.server_close();thread.join(timeout=2)
