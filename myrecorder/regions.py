"""Pure logical-coordinate editing. Capture geometry is immutable outside idle."""
import math

MIN_SIZE = 32


def edit_region(original, dx, dy, mode, bounds, minimum=MIN_SIZE):
    x,y,w,h=original
    bx,by,bw,bh=bounds
    if any(not math.isfinite(v) for v in (*original,dx,dy,*bounds)):
        raise ValueError('유효하지 않은 영역 좌표입니다.')
    if min(w,h,bw,bh,minimum)<=0 or x<bx or y<by or x+w>bx+bw or y+h>by+bh:
        raise ValueError('선택 영역과 모니터 크기를 확인하세요.')
    dx,dy=round(dx),round(dy)
    if mode=='move':
        return max(bx,min(x+dx,bx+bw-w)),max(by,min(y+dy,by+bh-h)),w,h
    if mode not in {'n','s','e','w','ne','nw','se','sw'}:
        raise ValueError('알 수 없는 영역 조절 방식입니다.')
    left,top,right,bottom=x,y,x+w,y+h
    mw,mh=min(minimum,bw),min(minimum,bh)
    if 'w' in mode: left=max(bx,min(x+dx,right-mw))
    if 'e' in mode: right=min(bx+bw,max(x+w+dx,left+mw))
    if 'n' in mode: top=max(by,min(y+dy,bottom-mh))
    if 's' in mode: bottom=min(by+bh,max(y+h+dy,top+mh))
    return left,top,right-left,bottom-top
