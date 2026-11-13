"""Explicit physical-coordinate desktop selection; independent of Qt list order."""
from dataclasses import asdict
import json
from .display import (DisplayError, native_monitors, screen_snapshot, match_monitor,
                      dpi_awareness, map_region)


def bounding(rectangles):
    if not rectangles:raise DisplayError('화면이 없습니다.','DESKTOP_EMPTY')
    left=min(r[0] for r in rectangles);top=min(r[1] for r in rectangles)
    right=max(r[0]+r[2] for r in rectangles);bottom=max(r[1]+r[3] for r in rectangles)
    return left,top,right-left,bottom-top


def intersects(a,b):return max(a[0],b[0])<min(a[0]+a[2],b[0]+b[2]) and max(a[1],b[1])<min(a[1]+a[3],b[1]+b[3])


def validate_rect(region,bounds,monitors):
    result=map_region(region,bounds,bounds)
    if not any(intersects(result,m.rect) for m in monitors):
        raise DisplayError('영역이 모니터 사이 빈 공간에만 있습니다.','REGION_IN_DESKTOP_GAP')
    return result


def layout(screens,diagnostics=None,operation='desktop_layout'):
    report={'operation':operation,'coordinate_space':'physical_virtual_desktop'}
    try:
        snapshots=[screen_snapshot(s) for s in screens]
        report['qt_screens']=snapshots
        monitors=native_monitors();report['windows_monitors']=[asdict(m) for m in monitors]
        if len(screens)!=len(monitors):raise DisplayError('Qt/Windows 연결 화면 수가 다릅니다.','SCREEN_COUNT_CONFLICT')
        entries=[];used=[];evidence=[]
        for screen,snapshot in zip(screens,snapshots):
            native,match=match_monitor(snapshot,snapshots,monitors)
            if match['native_index'] in used:raise DisplayError('서로 다른 화면이 동일 모니터에 대응합니다.','DESKTOP_MATCH_AMBIGUOUS')
            used.append(match['native_index']);entries.append((screen,native));evidence.append(match)
        if any(abs(s['dpr']-1)>.01 for s in snapshots) and dpi_awareness()!=2:
            raise DisplayError('혼합/고배율 데스크톱에는 모니터별 DPI 인식이 필요합니다.','PER_MONITOR_DPI_REQUIRED')
        bounds=bounding([m.rect for m in monitors])
        signature=json.dumps(sorted([{'qt':screen_snapshot(s),'native':asdict(m)} for s,m in entries],key=lambda e:e['native']['name']),sort_keys=True)
        report.update(physical_virtual_desktop=bounds,matching=evidence)
        if diagnostics:diagnostics('desktop_layout_ok',**report)
        return entries,bounds,signature
    except Exception as exc:
        report.update(detail=str(exc),failed_condition=getattr(exc,'code','NATIVE_QUERY_FAILED'),validation=getattr(exc,'report',{}))
        if diagnostics:diagnostics('desktop_layout_failed',**report)
        raise DisplayError('가상 데스크톱 검증 실패: '+str(exc),report['failed_condition'],report) from exc
