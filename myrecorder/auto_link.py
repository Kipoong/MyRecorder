"""Independent lecture synchronizer. No media/screen/audio heuristics or capture APIs."""
import time

class AutoLink:
    def __init__(self,bridge,log,clock=time.monotonic):
        self.bridge=bridge;self.log=log;self.clock=clock
        self.enabled=False;self.selected=None;self.manual_hold=False;self.auto_paused=False
        self.pending={};self.tail=1.;self.lead=.5;self.end_stops=False;self.deadline=None
        self.desired=None;self.last_seen=None;self.recording_since=None;self.previous_state=None
        self.session_started=False;self.waiting_action=None;self.message='자동 연동 OFF'
    def emit(self,event,**fields):self.log(event,mono=self.clock(),wall_ms=time.time()*1000,**fields)
    def arm(self,key,mode):
        source=next((s for s in self.bridge.snapshot() if s['key']==key),None)
        if mode!='lecture' or not source or not source['supported'] or self.clock()-source['seen']>4:raise ValueError('지원되는 강의 탭을 먼저 선택하세요.')
        self.bridge.drain()
        self.enabled=True;self.selected=key;self.manual_hold=False;self.auto_paused=False
        self.desired='warmup';self.deadline=None;self.session_started=False;self.waiting_action=None
        self.last_seen=self.clock();self.recording_since=None;self.previous_state=None
        self.message='선행 영상·오디오 준비 중';self.bridge.configure(key,True,self.message)
        self.emit('auto_armed',source=key,lead=self.lead,tail=self.tail,already_playing=source['state']=='playing')
        if source['state']=='playing':self.desired='play';self.message='이미 재생 중 — 시작 누락 가능. 다음 재생부터 게이트 적용'
    def disable(self,reason='자동 연동 OFF'):
        self.enabled=False;self.desired=None;self.deadline=None;self.waiting_action=None;self.message=reason
        for request in self.pending:self.bridge.resolve(request,'blocked',reason)
        self.pending.clear();self.bridge.configure(self.selected,False,reason);self.emit('auto_disabled',reason=reason)
    def manual(self,command):
        if command=='pause':
            self.manual_hold=True;self.desired='pause';self.deadline=None
            for request in self.pending:self.bridge.resolve(request,'blocked','MyRecorder 수동 일시정지 상태입니다.')
            self.pending.clear();self.message='수동 일시정지 우선 — 자동 재개 안 함'
        elif command in ('resume','start'):
            self.manual_hold=False;self.auto_paused=False;self.desired='play';self.deadline=None
        elif command=='stop':self.disable('사용자 녹화 종료 — 다음 강의는 자동 연동을 다시 켜세요.')
        self.emit('manual_command',command=command)
    def process(self,event):
        if not self.enabled or event['source']['key']!=self.selected:return
        self.last_seen=self.clock();kind=event['kind']
        if kind!='snapshot':self.emit('browser_event',kind=kind,request_id=event.get('request_id'),
            event_wall_ms=event['event_wall_ms'],received_wall_ms=event['received_wall_ms'],
            transport_wall_ms=event['received_wall_ms']-event['event_wall_ms'],media_time=event.get('media_time'),gate=event['source'].get('gate'))
        if kind=='play_failed':
            self.disable('브라우저가 재생을 거부했습니다 — 녹화는 유지, 플레이어를 직접 확인하세요.');return
        if kind in ('unsupported','disconnect') or not event['source']['supported']:
            self.disable('감지 불가/연결 끊김 — 현재 녹화는 유지, 수동 제어하세요.');return
        if kind=='prepare':
            request=event.get('request_id')
            if not request:return
            if self.manual_hold:self.bridge.resolve(request,'blocked','수동 일시정지 우선');return
            if request not in self.pending and len(self.pending)>=16:
                self.bridge.resolve(request,'blocked','동시 재생 준비 요청이 너무 많습니다.');return
            self.pending[request]=self.clock();self.desired='play';self.deadline=None
        elif kind=='playing':
            if not self.manual_hold:
                self.desired='play';self.deadline=None
                self.message='재생 중 — ready 확인' if event['source'].get('gate')=='ready-ack' else '관찰 방식 재생 중 — 시작 누락 가능'
        elif kind=='pause':
            if not self.manual_hold:self.desired='pause';self.deadline=self.clock()+self.tail
        elif kind=='ended':
            if not self.manual_hold:self.desired='stop' if self.end_stops else 'pause';self.deadline=self.clock()+self.tail
        # waiting/stalled/buffering do not pause. snapshots do not restart a session.
    def tick(self,state,busy,mode):
        now=self.clock()
        events=self.bridge.drain()
        if not self.enabled:return None
        if mode!='lecture':self.disable('일반 영상 모드 — 자동 연동 적용 안 함');return None
        for event in events:self.process(event)
        if not self.enabled:return None
        if self.last_seen is not None and now-self.last_seen>8:
            self.disable('브라우저 연결 끊김 — 녹화는 유지, 수동 제어하세요.');return None
        if state=='save_failed':self.disable('저장 실패 — 수동 복구/재시도하세요.');return None
        if self.previous_state!=state:
            self.emit('recorder_state',state=state)
            self.previous_state=state
            if state=='recording':self.recording_since=now;self.session_started=True;self.waiting_action=None
            if state=='paused':self.auto_paused=not self.manual_hold;self.waiting_action=None
            if state=='idle' and self.session_started:
                self.disable('저장 완료 — 자동 연동을 다시 켜면 새 세션');return None
        for request,since in list(self.pending.items()):
            if now-since>35:
                self.bridge.resolve(request,'blocked','녹화 준비 35초 시간 초과');self.pending.pop(request)
        if not self.pending and self.desired=='play' and self.waiting_action and now-self.waiting_action[1]>40:
            self.disable('녹화 준비 시간 초과 — 수동 확인 필요');return None
        if busy:return None
        if self.manual_hold:return None
        if state=='recording' and self.recording_since is not None and now-self.recording_since>=self.lead:
            for request,since in list(self.pending.items()):
                self.bridge.resolve(request,'ready','영상·오디오 녹화 시작 확인')
                self.emit('ready_ack',request_id=request,ready_delay_ms=(now-since)*1000)
                self.pending.pop(request)
        action=None
        if self.desired in ('warmup','play'):
            if state=='idle':action='start'
            elif state=='paused' and self.auto_paused:action='resume'
            elif self.desired=='warmup' and state=='recording' and self.recording_since is not None and now-self.recording_since>=self.lead:
                self.desired='pause';action='pause';self.message='준비 완료 — 강의 재생 버튼을 누르세요.'
        elif self.desired in ('pause','stop') and (self.deadline is None or now>=self.deadline):
            if self.desired=='stop' and state in ('recording','paused'):action='stop'
            elif state=='recording':action='pause'
        if action:
            self.waiting_action=(action,now);self.emit('auto_dispatch',action=action)
        self.bridge.configure(self.selected,self.enabled,self.message)
        return action
    def failed(self,reason):self.disable('자동 전환 실패: '+reason+' — 수동 제어하세요.')
