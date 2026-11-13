"""Streaming packet audit after capture; detects timestamp errors, not perceptual lip sync."""
import math
import subprocess
from .media import binary, CREATE_NO_WINDOW


def packet_audit(path):
    command=[binary('ffprobe'),'-v','error','-show_packets','-show_entries',
             'packet=stream_index,pts_time,dts_time,duration_time','-of','compact=p=0:nk=0',str(path)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                             encoding='utf-8',errors='replace',creationflags=CREATE_NO_WINDOW)
    streams={};warnings=[]
    try:
        for line in process.stdout:
            fields=dict(part.split('=',1) for part in line.strip().split('|') if '=' in part)
            if 'stream_index' not in fields:continue
            index=fields['stream_index']
            state=streams.setdefault(index,{'packets':0,'first_pts':None,'last_end':None,'last_dts':None,'dts_regressions':0,'max_dts_gap':0.})
            def number(key):
                try:value=float(fields[key]);return value if math.isfinite(value) else None
                except (KeyError,ValueError):return None
            pts,dts,duration=number('pts_time'),number('dts_time'),number('duration_time')
            state['packets']+=1
            if pts is not None:
                state['first_pts']=pts if state['first_pts'] is None else min(pts,state['first_pts'])
                end=pts+max(0,duration or 0)
                state['last_end']=end if state['last_end'] is None else max(end,state['last_end'])
            if dts is not None:
                if state['last_dts'] is not None:
                    delta=dts-state['last_dts']
                    if delta < -0.00001:state['dts_regressions']+=1
                    state['max_dts_gap']=max(state['max_dts_gap'],delta)
                state['last_dts']=dts
        error=process.stderr.read();code=process.wait()
        if code:raise RuntimeError('PTS 조회 실패: '+error[-2000:])
        if not streams:raise RuntimeError('PTS를 확인할 패킷이 없습니다.')
        for index,state in streams.items():
            if state['dts_regressions']:warnings.append(f'스트림 {index}: DTS 역행 {state["dts_regressions"]}회')
            if state['first_pts'] is None:warnings.append(f'스트림 {index}: PTS 없음')
            if state['max_dts_gap']>.5:warnings.append(f'스트림 {index}: 타임스탬프 간격이 500ms를 넘습니다.')
        if len(streams)>1:
            starts=[s['first_pts'] for s in streams.values() if s['first_pts'] is not None]
            ends=[s['last_end'] for s in streams.values() if s['last_end'] is not None]
            if starts and max(starts)-min(starts)>.25:warnings.append('음성·영상 시작 PTS 차이가 250ms를 넘습니다.')
            if ends and max(ends)-min(ends)>.25:warnings.append('음성·영상 끝 PTS 차이가 250ms를 넘습니다.')
        return {'streams':streams,'warnings':warnings}
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.stdout.close();process.stderr.close()
