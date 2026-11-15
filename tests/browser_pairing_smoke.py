"""Actual popup save/readback/probe with controlled failure injection. No Windows capture."""
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
    raise AssertionError('pairing condition timed out')

extension=Path(__file__).resolve().parents[1]/'browser_extension'
with tempfile.TemporaryDirectory(prefix='pairing-flow-example-') as d:
    root=Path(d);(root/'index.html').write_text('<title>Pairing example video</title><video></video>')
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();bridge=None
    try:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(root/'profile'),channel='chromium',headless=True,
                ignore_default_args=['--disable-extensions'],args=['--no-sandbox',f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            try:
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                extension_id=worker.url.split('/')[2];bridge=Bridge(extension_id,signed_only=True);bridge.start();pairing=bridge.pairing
                lecture=context.new_page();lecture.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                popup_url=worker.url.replace('background.js','popup.html')
                def popup():
                    page=context.new_page();page.goto(popup_url)
                    wait(lambda:page.locator('#target option').count()>1)
                    return page
                # Reproduce loss of an unsaved textarea when an action popup is dismissed.
                page=popup();page.fill('#pairing',json.dumps(pairing));page.close()
                page=popup();wait(lambda:'CREDENTIALS_MISSING' in page.locator('#credential-status').inner_text())
                page.click('#save-pairing');wait(lambda:'INPUT_EMPTY' in page.locator('#status').inner_text())
                assert page.locator('#connect').is_disabled()
                # Import a JSON file, then explicitly persist and cold-decrypt it before testing the app.
                page.set_input_files('#pairing-file',{'name':'connection-example.json','mimeType':'application/json','buffer':json.dumps(pairing).encode()})
                wait(lambda:'아직 저장 전' in page.locator('#credential-status').inner_text())
                page.click('#save-pairing');wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                assert page.locator('#pairing').input_value()=='' and bridge.snapshot()==[] and bridge.drain()==[]
                page.close();page=popup();wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                # Wrong app token is distinguished from missing/browser-store credentials.
                bad={**pairing,'token':'a'*64}
                page.fill('#pairing',json.dumps(bad));page.click('#save-pairing')
                wait(lambda:'AUTH_REJECTED' in page.locator('#status').inner_text())
                assert '암호화 저장' in page.locator('#credential-status').inner_text()
                assert page.locator('#connect').is_disabled()
                page.fill('#pairing',json.dumps(pairing));page.click('#save-pairing')
                wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                # Explicit write failure: no generic first-pairing message, no raw secret in diagnostics.
                worker.evaluate('()=>{globalThis.realVaultSave=PairingVault.save;PairingVault.save=async()=>{throw new Error("synthetic write failure")};}')
                page.fill('#pairing',json.dumps(pairing));page.click('#save-pairing')
                wait(lambda:'STORE_WRITE_FAILED' in page.locator('#status').inner_text())
                assert pairing['token'] not in page.locator('#status').inner_text()
                worker.evaluate('()=>{PairingVault.save=globalThis.realVaultSave;}')
                page.fill('#pairing',json.dumps(pairing));page.click('#save-pairing')
                wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                # App outage keeps the already stored credentials; recovery needs no paste/reset.
                bridge.close();page.click('#save-pairing')
                wait(lambda:'APP_UNREACHABLE' in page.locator('#status').inner_text())
                bridge=Bridge(extension_id,signed_only=True,token=pairing['token'],port=pairing['port']);bridge.start()
                page.click('#save-pairing');wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                assert not bridge.armed and bridge.selected is None
                page.evaluate("()=>{window.realCall=rpc.call;rpc.call=()=>new Promise((_,reject)=>setTimeout(()=>reject(PairingInput.error('BACKGROUND_TIMEOUT','simulated timeout')),10000));}")
                page.click('#save-pairing');wait(lambda:'BACKGROUND_TIMEOUT' in page.locator('#status').inner_text())
                assert page.locator('#save-pairing').is_enabled()
                page.evaluate('()=>{rpc.call=window.realCall;}')
                page.click('#save-pairing');wait(lambda:'앱 응답 정상' in page.locator('#credential-status').inner_text())
                print('Actual Chromium: unsaved-popup dismissal, explicit JSON/file save, cold readback and signed app probe: PASS')
                print('Missing input/write failure/wrong token/app outage distinguished; credentials preserved and no capture: PASS')
            finally:context.close()
    finally:
        if bridge:bridge.close()
        server.shutdown();server.server_close();thread.join(timeout=2)
