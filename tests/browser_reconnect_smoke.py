"""Actual Chromium profile restart + encrypted extension vault + loopback reconnect.
No DPAPI/Windows capture is exercised. Playwright and a test Chromium are optional dev tools.
"""
import functools,tempfile,threading,time
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
        time.sleep(.05)
    raise AssertionError('reconnect timed out')

extension=Path(__file__).resolve().parents[1]/'browser_extension'
with tempfile.TemporaryDirectory(prefix='browser-reconnect-example-') as d:
    root=Path(d);(root/'index.html').write_text('<title>Reconnect example</title><video></video>')
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/index.html';bridge=None
    try:
        with sync_playwright() as p:
            def launch():return p.chromium.launch_persistent_context(str(root/'profile'),channel='chromium',headless=True,
                ignore_default_args=['--disable-extensions'],args=['--no-sandbox',f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            context=launch()
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            extension_id=worker.url.split('/')[2];bridge=Bridge(extension_id,signed_only=True);bridge.start()
            pairing=bridge.pairing
            worker.evaluate('(pairing)=>PairingVault.save(pairing)',pairing)
            # Same registrations used by the popup, deliberately persistent across restart.
            worker.evaluate('''async()=>{
                await chrome.storage.local.set({paired_sites:[{id:'1234567890abcdef',pattern:'http://127.0.0.1/*'}]});
                await chrome.scripting.registerContentScripts([
                  {id:'gate-1234567890abcdef',matches:['http://127.0.0.1/*'],js:['gate.js'],world:'MAIN',runAt:'document_start',persistAcrossSessions:true},
                  {id:'observer-1234567890abcdef',matches:['http://127.0.0.1/*'],js:['content.js'],world:'ISOLATED',runAt:'document_start',persistAcrossSessions:true}
                ]);
            }''')
            page=context.new_page();page.goto(url);wait(lambda:len(bridge.snapshot())>0)
            assert not bridge.armed and bridge.selected is None
            raw=worker.evaluate('()=>chrome.storage.local.get(null)')
            assert pairing['token'] not in str(raw) and 'pairing_cipher' in raw
            assert worker.evaluate('async()=>!(await PairingVault.key()).extractable')
            assert worker.evaluate('async()=>{try{await crypto.subtle.exportKey("raw",await PairingVault.key());return false}catch{return true}}')
            bridge.close();bridge=Bridge(extension_id,token=pairing['token'],port=pairing['port'],signed_only=True);bridge.start()
            wait(lambda:len(bridge.snapshot())>0)
            assert bridge.pairing==pairing and not bridge.armed and bridge.selected is None
            context.close()
            # No popup, no pasted token, no session storage migration on this run.
            context=launch();page=context.new_page();page.goto(url)
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            try:wait(lambda:len(bridge.snapshot())>=2)
            except AssertionError:
                print('Restart debug: registrations=',len(worker.evaluate('()=>chrome.scripting.getRegisteredContentScripts()')))
                print('Restart debug: vault=',worker.evaluate('async()=>{try{return !!await PairingVault.load()}catch(e){return e.message}}'))
                print('Restart debug: page state=',page.evaluate('document.documentElement.dataset.myrecorderStatus || "no observer"'))
                raise
            assert not bridge.armed and bridge.selected is None
            assert worker.evaluate('async()=>!(await chrome.storage.session.get("pairing")).pairing')
            assert worker.evaluate('async()=>!!await PairingVault.load()')
            assert len(worker.evaluate('()=>chrome.scripting.getRegisteredContentScripts()'))==2
            # Forget removes both cipher and key; copied ciphertext cannot resurrect the pairing.
            worker.evaluate('()=>PairingVault.forget()')
            assert worker.evaluate('async()=>!(await PairingVault.load())')
            assert worker.evaluate('async()=>!(await PairingVault.key())')
            context.close()
            print('Actual Chromium: encrypted vault + non-extractable key, app restart, browser restart: PASS')
            print('Persistent site injection, no token paste/session secret, disarmed reconnect and forget: PASS')
    finally:
        if bridge:bridge.close()
        server.shutdown();server.server_close();thread.join(timeout=2)
