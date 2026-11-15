"""Real Chromium popup setup path, including missing tab metadata. No capture/Windows claims."""
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
        time.sleep(.05)
    raise AssertionError('popup/bridge condition timed out')

extension=Path(__file__).resolve().parents[1]/'browser_extension'
with tempfile.TemporaryDirectory(prefix='popup-flow-example-') as d:
    root=Path(d);(root/'index.html').write_text('<title>Example HTML5 target</title><video></video>')
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    bridge=None
    try:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(root/'profile'),channel='chromium',headless=True,
                ignore_default_args=['--disable-extensions'],args=['--no-sandbox',f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            try:
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                extension_id=worker.url.split('/')[2];bridge=Bridge(extension_id,signed_only=True);bridge.start()
                lecture=context.new_page();lecture.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                popup=context.new_page();popup.goto(worker.url.replace('background.js','popup.html'))
                wait(lambda:popup.locator('#target option').count()>1)
                assert popup.locator('#target').input_value()=='' # own popup tab is not a lecture
                target_id=worker.evaluate('async()=>{const tabs=await chrome.tabs.query({});return tabs.find(t=>t.title==="Example HTML5 target").id}')
                popup.select_option('#target',str(target_id))
                popup.fill('#pairing',json.dumps(bridge.pairing));popup.click('#save-pairing')
                wait(lambda:'앱 응답 정상' in popup.locator('#credential-status').inner_text())
                assert bridge.snapshot()==[] and bridge.drain()==[]
                popup.click('#connect')
                wait(lambda:'연결 저장 완료' in popup.locator('#status').inner_text())
                wait(lambda:len(bridge.snapshot())>0)
                assert popup.locator('#pairing').input_value()==''
                assert bridge.snapshot()[0]['title']=='Example HTML5 target'
                assert not bridge.armed and bridge.selected is None
                assert worker.evaluate("()=>chrome.permissions.contains({permissions:['tabs']})")
                assert len(worker.evaluate('()=>chrome.scripting.getRegisteredContentScripts()'))==2
                # Same UI can reconnect with no newly pasted token.
                popup.reload();wait(lambda:popup.locator('#target option').count()>1)
                popup.select_option('#target',str(target_id));popup.click('#connect')
                wait(lambda:'연결 저장 완료' in popup.locator('#status').inner_text())
                # Inject the actual reported metadata condition at the browser API boundary.
                popup.evaluate('chrome.tabs.query=async()=>[{id:123,active:true}]')
                popup.click('#refresh-tabs')
                wait(lambda:'탭 주소 조회 권한' in popup.locator('#status').inner_text())
                assert popup.locator('#connect').is_disabled()
                assert 'Invalid URL' not in popup.locator('#status').inner_text()
                # Navigation after selection is rejected before connecting a different document.
                popup.reload();wait(lambda:popup.locator('#target option').count()>1)
                popup.select_option('#target',str(target_id));lecture.goto(lecture.url+'?changed')
                popup.click('#connect');wait(lambda:'주소가 바뀌' in popup.locator('#status').inner_text())
                popup.click('#refresh-tabs');wait(lambda:popup.locator('#target option').count()>1)
                popup.select_option('#target',str(target_id))
                # Closed target is reported safely; it does not silently connect to another tab.
                lecture.close();popup.click('#connect')
                wait(lambda:popup.locator('#connect').is_enabled())
                assert '연결 저장 완료' not in popup.locator('#status').inner_text()
                assert 'Invalid URL' not in popup.locator('#status').inner_text()
                print('Actual Chromium popup: explicit target, permission, save, script injection and signed connection: PASS')
                print('Stored-token reconnect, missing URL metadata, navigation and closed target: PASS; capture remains disarmed.')
            finally:context.close()
    finally:
        if bridge:bridge.close()
        server.shutdown();server.server_close();thread.join(timeout=2)
