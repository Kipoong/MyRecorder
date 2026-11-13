"""Generate a local unprotected HTML5 test player under configured Temp."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import uuid
from .settings import SettingsStore,storage_directory
from .media import binary,run

HTML='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>MyRecorder HTML5 연동 시험</title>
<style>body{font:18px sans-serif;background:#20232a;color:white}button{padding:14px;margin:8px}video{width:640px}#clock{font-size:36px}</style>
<h2>MyRecorder HTML5 연동 시험 (보호 없는 합성 영상)</h2>
<video id="video" src="sample.mp4" playsinline></video>
<div id="clock">0.000초</div><div id="flash">시작 신호</div>
<button id="play">강의 재생 (JS play)</button><button id="pause">강의 일시정지</button>
<button id="bypass">기본 video 컨트롤 표시 (관찰 시험)</button><button id="end">종료 근처로 이동</button>
<p>확장에서 이 탭을 연결하고 앱에서 자동 감지/준비를 완료한 뒤 재생하세요.\n재생 실패는 아래에 표시됩니다. 이 페이지에는 DRM이나 실제 강의가 없습니다.</p><pre id="log"></pre>
<script>
const video=document.querySelector('#video'),output=document.querySelector('#log');
function log(message){output.textContent=Date.now()+' | '+video.currentTime.toFixed(3)+' | '+message+'\\n'+output.textContent.slice(0,3000)}
document.querySelector('#play').onclick=()=>video.play().catch(e=>log('재생 실패: '+e.message));
document.querySelector('#pause').onclick=()=>video.pause();
document.querySelector('#bypass').onclick=()=>{video.controls=true;log('기본 컨트롤을 조작하고 앱의 ready/관찰 상태를 확인하세요.')} ;
document.querySelector('#end').onclick=()=>{video.currentTime=Math.max(0,video.duration-1)};
for(const name of ['play','playing','pause','waiting','ended'])video.addEventListener(name,()=>log(name));
function draw(){document.querySelector('#clock').textContent=video.currentTime.toFixed(3)+'초';
 document.querySelector('#flash').style.background=video.currentTime<.2?'red':'transparent';requestAnimationFrame(draw)}draw();
</script></html>'''

def main():
    folder=storage_directory(SettingsStore().load().temp)/('player-demo-'+uuid.uuid4().hex);folder.mkdir()
    run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=30:duration=60',
         '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=60','-c:v','libx264','-preset','ultrafast',
         '-c:a','aac','-pix_fmt','yuv420p','-movflags','+faststart',str(folder/'sample.mp4')])
    (folder/'index.html').write_text(HTML,encoding='utf-8')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(folder)))
    print(f'Chrome/Edge에서 열기: http://127.0.0.1:{server.server_port}/index.html',flush=True)
    print(f'합성 시험 파일: {folder}\n종료: Ctrl+C. 파일은 Temp에 보존됩니다.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
