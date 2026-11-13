"""Authenticated loopback transport. No GUI/capture calls run in HTTP threads."""
from collections import deque, OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time

KINDS={'snapshot','prepare','pause','playing','ended','buffering','unsupported','poll','disconnect','play_failed'}

class Bridge:
    def __init__(self,extension_id,clock=time.monotonic):
        if not re.fullmatch('[a-p]{32}',extension_id):raise ValueError('확장 ID는 a~p 영문 소문자 32자입니다.')
        self.origin='chrome-extension://'+extension_id;self.token=secrets.token_hex(32)
        self.clock=clock;self.lock=threading.RLock();self.events=deque(maxlen=512)
        self.sources=OrderedDict();self.replies=OrderedDict();self.last_sequences={}
        self.selected=None;self.armed=False;self.message='수동 제어';self.server=None;self.thread=None
    def ingest(self,data):
        if not isinstance(data,dict) or data.get('kind') not in KINDS:raise ValueError('invalid event')
        source=data.get('source');seq=data.get('seq')
        if not isinstance(source,dict) or not isinstance(seq,int) or isinstance(seq,bool) or seq<0:raise ValueError('invalid source/sequence')
        key=source.get('key')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,180}',key):raise ValueError('invalid source key')
        if not isinstance(source.get('title'),str) or len(source['title'])>500:raise ValueError('invalid title')
        if source.get('state') not in ('playing','paused','ended','unsupported','buffering'):raise ValueError('invalid state')
        if not isinstance(source.get('supported'),bool):raise ValueError('invalid support status')
        request=data.get('request_id')
        if request is not None and (not isinstance(request,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request)):raise ValueError('invalid request')
        wall=data.get('event_wall_ms')
        if not isinstance(wall,(int,float)) or not 0<=wall<1e15:raise ValueError('invalid timestamp')
        with self.lock:
            previous=self.last_sequences.get(key,-1)
            if seq<=previous:raise ValueError('stale sequence')
            self.last_sequences[key]=seq
            source={k:source.get(k) for k in ('key','title','state','supported','origin','video_label','gate')}
            for field in ('origin','video_label','gate'):
                if not isinstance(source.get(field),str) or len(source[field])>500:raise ValueError('invalid metadata')
            source['seen']=self.clock();self.sources[key]=source;self.sources.move_to_end(key)
            while len(self.sources)>64:
                old,_=self.sources.popitem(last=False);self.last_sequences.pop(old,None)
            if data['kind']!='poll':
                if len(self.events)>=512:raise ValueError('event queue full')
                self.events.append({'kind':data['kind'],'source':source,'request_id':request,
                                    'event_wall_ms':wall,'received_wall_ms':time.time()*1000,'received_mono':self.clock(),'media_time':data.get('media_time') if isinstance(data.get('media_time'),(int,float)) and 0<=data['media_time']<1e9 else None})
            if data['kind']=='prepare' and request:
                if key!=self.selected or not self.armed:self.resolve(request,'blocked','선택한 강의 탭의 자동 연동이 준비되지 않았습니다.')
                else:self.replies.setdefault(request,{'status':'pending','reason':'녹화 준비 중','source_key':key,'created':self.clock()})
            reply=self.replies.get(request,{'status':'blocked','reason':'준비 요청이 만료되었습니다.'}) if request else None
            if reply and (reply.get('source_key',key)!=key or key!=self.selected or not self.armed):reply={'status':'blocked','reason':'연동이 해제되었거나 다른 탭입니다.'}
            return {'selected_key':self.selected,'armed':self.armed,'message':self.message,'reply':reply}
    def resolve(self,request,status,reason=''):
        if not request:return
        with self.lock:
            previous=self.replies.get(request,{})
            self.replies[request]={**previous,'status':status,'reason':reason,'ack_wall_ms':time.time()*1000}
            while len(self.replies)>64:self.replies.popitem(last=False)
    def snapshot(self):
        with self.lock:return [dict(v) for v in self.sources.values()]
    def drain(self):
        with self.lock:result=list(self.events);self.events.clear();return result
    def configure(self,selected,armed,message):
        with self.lock:self.selected=selected;self.armed=armed;self.message=message
    def start(self):
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass  # never log tokens or raw HTTP payloads
            def setup(self):super().setup();self.connection.settimeout(3)
            def authorized(self,preflight=False):
                expected=f'127.0.0.1:{self.server.server_address[1]}'
                if self.headers.get('Host')!=expected:return False
                origin=self.headers.get('Origin')
                if origin not in (None,bridge.origin):return False
                if preflight and origin!=bridge.origin:return False
                if not preflight and self.headers.get('X-MyRecorder-Extension')!=bridge.origin.split('://')[1]:return False
                if self.path!='/v1/events':return False
                if preflight:return True
                try:return secrets.compare_digest(self.headers.get('Authorization','').encode('ascii'),('Bearer '+bridge.token).encode('ascii'))
                except UnicodeEncodeError:return False
            def answer(self,status,data):
                body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
                self.send_response(status)
                if self.headers.get('Origin')==bridge.origin:self.send_header('Access-Control-Allow-Origin',bridge.origin)
                self.send_header('Vary','Origin');self.send_header('Cache-Control','no-store')
                self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
                self.send_header('Connection','close');self.end_headers();self.wfile.write(body)
            def do_OPTIONS(self):
                if not self.authorized(True):return self.answer(403,{'error':'origin/host rejected'})
                if self.headers.get('Access-Control-Request-Method')!='POST':return self.answer(403,{'error':'method rejected'})
                self.send_response(204);self.send_header('Access-Control-Allow-Origin',bridge.origin)
                self.send_header('Access-Control-Allow-Methods','POST');self.send_header('Access-Control-Allow-Headers','authorization,content-type,x-myrecorder-extension')
                self.send_header('Content-Length','0');self.send_header('Connection','close');self.end_headers()
            def do_POST(self):
                if not self.authorized():return self.answer(403,{'error':'authentication/origin/host rejected'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.answer(415,{'error':'json required'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=16384 or self.headers.get('Transfer-Encoding'):return self.answer(413,{'error':'body rejected'})
                    data=json.loads(self.rfile.read(length))
                    self.answer(200,bridge.ingest(data))
                except (ValueError,TypeError,KeyError):self.answer(400,{'error':'invalid/stale event'})
            def do_GET(self):self.answer(405,{'error':'POST required'})
        class Server(ThreadingHTTPServer):
            daemon_threads=True
            request_queue_size=8
        self.server=Server(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='MyRecorderBridge',daemon=True);self.thread.start()
    @property
    def pairing(self):return {'port':self.server.server_address[1],'token':self.token}
    def close(self):
        self.configure(None,False,'연결 종료')
        if self.server:
            if self.thread and self.thread.is_alive():self.server.shutdown()
            self.server.server_close()
        if self.thread:self.thread.join(timeout=2)
