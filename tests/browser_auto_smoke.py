"""Real unpacked extension + HTML5 browser + HTTP, with simulated recorder policy.
Optional dev test: PLAYWRIGHT_BROWSERS_PATH=... PYTHONPATH=. python tests/browser_auto_smoke.py
No Windows capture or audio device success is implied.
"""
import functools
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import subprocess,tempfile,threading,time
from playwright.sync_api import sync_playwright
from myrecorder.browser_bridge import Bridge
from myrecorder.auto_link import AutoLink

root=Path(__file__).resolve().parents[1];extension=root/'browser_extension'
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def wait(predicate,timeout=12):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('browser/bridge condition timed out')

with tempfile.TemporaryDirectory(prefix='browser-auto-example-') as d:
    folder=Path(d)
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15:duration=20',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=20',
                    '-c:v','libvpx','-deadline','realtime','-c:a','libvorbis',str(folder/'sample.webm')],check=True)
    (folder/'index.html').write_text('''<!doctype html><title>Example HTML5 lecture</title>
    <video id="video" src="sample.webm" controls></video><script>window.cachedPlay=HTMLMediaElement.prototype.play;</script>
    <button id="play" onclick="video.play().catch(e=>document.body.dataset.error=e.message)">Play</button>
    <button id="pause" onclick="video.pause()">Pause</button>''')
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(folder)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/index.html'
    try:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(folder/'profile'),channel='chromium',headless=True,
                ignore_default_args=['--disable-extensions'],args=['--no-sandbox',f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            extension_id=worker.url.split('/')[2];bridge=Bridge(extension_id);bridge.start()
            done=threading.Event();logs=[];errors=[]
            try:
                worker.evaluate('(pairing)=>chrome.storage.session.set({pairing})',bridge.pairing)
                page=context.new_page();page.goto(url);page.wait_for_selector('video')
                def inject(page):
                    worker.evaluate('''async ({url})=>{
                      const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url===url);
                      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['gate.js']});
                      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',files:['content.js']});
                    }''',{'url':page.url})
                inject(page)
                wait(lambda:len(bridge.snapshot())==1)
                key=bridge.snapshot()[0]['key']
                auto=AutoLink(bridge,lambda event,**fields:logs.append((event,fields)))
                auto.lead=.1;auto.tail=.1;auto.arm(key,'lecture')
                state={'value':'idle','starts':0,'pauses':0}
                def drive():
                    try:
                        while not done.wait(.02):
                            action=auto.tick(state['value'],False,'lecture')
                            if action in ('start','resume'):
                                time.sleep(.15);state['value']='recording';state['starts']+=1
                            elif action=='pause':state['value']='paused';state['pauses']+=1
                            elif action=='stop':state['value']='idle'
                    except Exception as error:errors.append(str(error))
                controller=threading.Thread(target=drive,daemon=True);controller.start()
                wait(lambda:state['value']=='paused')
                page.wait_for_timeout(1200) # deliver selected/armed status to content script
                for index in range(5):
                    page.click('#play')
                    assert page.eval_on_selector('video','v=>v.paused && v.currentTime < 20')
                    page.wait_for_function('!document.querySelector("video").paused && document.querySelector("video").currentTime > 0')
                    assert state['value']=='recording'
                    page.eval_on_selector('video','v=>v.dispatchEvent(new Event("waiting"))')
                    page.wait_for_timeout(150);assert state['value']=='recording'
                    before=state['pauses'];page.click('#pause');wait(lambda:state['pauses']>before)
                assert len([1 for event,fields in logs if event=='ready_ack'])==5
                assert len([1 for event,fields in logs if event=='browser_event' and fields.get('kind')=='playing' and fields.get('gate')=='ready-ack'])==5
                # A different tab can play while the selected lecture remains paused.
                other=context.new_page();other.goto(url+'?other');inject(other)
                wait(lambda:len(bridge.snapshot())>=2)
                other.click('#play');other.wait_for_function('!document.querySelector("video").paused')
                other.wait_for_timeout(300);assert state['value']=='paused'
                page.bring_to_front();page.evaluate('window.cachedPlay.call(document.querySelector("video"))');page.wait_for_function('!document.querySelector("video").paused')
                wait(lambda:state['value']=='recording')
                wait(lambda:any(event=='browser_event' and fields.get('kind')=='playing' and fields.get('gate')=='observer' for event,fields in logs))
                page.close();wait(lambda:not auto.enabled,timeout=12)
                assert state['value']=='recording' # disconnect never silently stops capture
                assert not errors,errors
                print('Real Chromium unpacked extension + HTML5 gate + authenticated loopback: PASS')
                print('5 ready ACK cycles, buffering/other-tab isolation, bypass observer warning, disconnect fallback: PASS')
                print('Recorder transitions simulated; Windows capture/MP4/A-V sync not exercised by this browser test.')
            finally:
                done.set()
                if 'controller' in locals():controller.join(timeout=2)
                bridge.close();context.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
