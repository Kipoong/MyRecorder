"""Capture policy: media playback and silence never imply a recorder pause."""
from dataclasses import dataclass

MODES={'lecture':'강의 녹화','general':'일반 영상 녹화'}

@dataclass(frozen=True)
class RecordingPolicy:
    mode: str = 'lecture'
    def __post_init__(self):
        if self.mode not in MODES:raise ValueError('지원하지 않는 녹화 유형입니다.')
    @property
    def automatic_detection_supported(self):return False
    @property
    def instructions(self):
        if self.mode=='lecture':
            return '수동 강의 모드: 강의를 멈춘 뒤 MyRecorder 일시정지를 누르세요. 재개하면 같은 MP4로 이어집니다. 재생 자동 감지는 미지원입니다.'
        return '일반 모드: 원본 정지 화면·무음도 계속 녹화합니다. MyRecorder 일시정지를 직접 누른 구간만 제외합니다.'
    def permits(self,command,state):
        return state in {'start':('idle',),'pause':('recording',),'resume':('paused',),
                         'stop':('recording','paused','save_failed')}.get(command,())
    def playback_action(self,event):
        # Extension point for a future explicit player adapter. No visual/silence heuristic.
        return 'continue'
