"""Capture policy: media playback and silence never imply a recorder pause."""
from dataclasses import dataclass

MODES={'lecture':'강의 녹화','general':'일반 영상 녹화'}

@dataclass(frozen=True)
class RecordingPolicy:
    mode: str = 'lecture'
    def __post_init__(self):
        if self.mode not in MODES:raise ValueError('지원하지 않는 녹화 유형입니다.')
    @property
    def automatic_detection_supported(self):
        # Adapter capability only; the bridge must be connected and explicitly armed.
        return self.mode=='lecture'
    @property
    def instructions(self):
        if self.mode=='lecture':
            return '강의 모드: 기본은 수동 조작입니다. 확장 연결 후 자동 감지를 켜면 선택한 HTML5 video만 연동합니다. 미지원 플레이어는 수동으로 조작하세요.'
        return '일반 모드: 원본 정지 화면·무음도 계속 녹화합니다. MyRecorder 일시정지를 직접 누른 구간만 제외합니다.'
    def permits(self,command,state):
        return state in {'start':('idle',),'pause':('recording',),'resume':('paused',),
                         'stop':('recording','paused','save_failed')}.get(command,())
    def playback_action(self,event):
        # Explicit authenticated events are handled by AutoLink. No visual/silence heuristic here.
        return 'continue'
