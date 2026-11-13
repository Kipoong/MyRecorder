"""Persistent hollow region overlay; UI-only, no capture/audio pipeline changes."""
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QWidget
from .regions import edit_region
from .window_capture import ExclusionStatus, exclude_overlay

COLORS={'idle':'#25b65a','recording':'#ed3f3f','paused':'#f39b25'}
LABELS={'idle':'대기','recording':'녹화 중','paused':'일시정지 / 저장'}


class RegionOverlay(QWidget):
    regionChanged=Signal(object)

    def __init__(self, protect=exclude_overlay):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool|Qt.WindowDoesNotAcceptFocus|Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.selected=QRect()
        self.bounds=QRect()
        self.physical=None
        self.phase='idle'
        self.capture_active=False
        self.requested_visible=True
        self.editable=True
        self.suspended=False
        self.exclusion=ExclusionStatus(False,'미확인')
        self._protect=protect
        self._protecting=False
        self._ready=True
        self._closing=False
        self._transparent_input=False
        self._drag=None
        self._bands=[]
        self._handles={}
        self._label=QRect()

    def configure(self, selected, bounds, physical, phase='idle', visible=True, editable=True, suspended=False, capture_active=False):
        if phase not in COLORS: raise ValueError('알 수 없는 오버레이 상태')
        self.selected=QRect(selected);self.bounds=QRect(bounds);self.physical=physical
        self.capture_active=bool(capture_active or phase=='recording')
        self.phase=phase;self.requested_visible=visible;self.suspended=suspended
        self.editable=bool(editable and phase=='idle' and not self.capture_active)
        transparent=not self.editable
        if transparent!=self._transparent_input:
            self._cancel_drag()
            self.hide()  # flag changes can recreate HWND; do this before capture starts
            self.setWindowFlag(Qt.WindowTransparentForInput,transparent)
            self._transparent_input=transparent
        if selected.isEmpty() or not bounds.contains(selected):
            self.exclusion=ExclusionStatus(False,'선택 영역이 모니터 밖입니다. 다시 선택하세요.')
            self.editable=False;self._cancel_drag()
            self.hide();return
        self._layout()
        if suspended or not visible or selected.isEmpty():
            self._cancel_drag()
            self.hide();return
        self._apply_exclusion()
        if self.capture_active and not self.exclusion.applied:
            self.hide()  # fail closed: missing protection must not burn UI into video
            return
        self.show()
        self.update()

    def _apply_exclusion(self, hwnd=None):
        if self._protecting:return
        self._protecting=True
        try:self.exclusion=self._protect(int(self.winId()) if hwnd is None else hwnd)
        except Exception as exc:self.exclusion=ExclusionStatus(False,f'오버레이 제외 확인 오류: {type(exc).__name__}')
        finally:self._protecting=False

    def event(self,event):
        result=super().event(event)
        if event.type()==QEvent.WinIdChange and getattr(self,'_ready',False) and not self._protecting and not self._closing:
            hwnd=int(self.effectiveWinId() or 0)
            if hwnd:self._apply_exclusion(hwnd)
            else:self.exclusion=ExclusionStatus(False,'오버레이 창 재생성 중')
            if self.capture_active and not self.exclusion.applied:self.hide()
        return result

    def _layout(self):
        if self.selected.isEmpty() or self.bounds.isEmpty():return
        r,b=self.selected,self.bounds
        thickness=3;handle=9
        # Prefer outside the capture. At screen edges, inset bands require affinity.
        lx=r.left()-thickness if r.left()-b.left()>=thickness else r.left()
        rx=r.right()+1 if b.right()-r.right()>=thickness else r.right()-thickness+1
        ty=r.top()-thickness if r.top()-b.top()>=thickness else r.top()
        by=r.bottom()+1 if b.bottom()-r.bottom()>=thickness else r.bottom()-thickness+1
        self._bands=[QRect(lx,r.top(),thickness,r.height()),QRect(rx,r.top(),thickness,r.height()),
                     QRect(r.left(),ty,r.width(),thickness),QRect(r.left(),by,r.width(),thickness)]
        width=min(300,b.width());height=min(24,b.height())
        if r.top()-b.top()>=height+3:y=r.top()-height-3
        elif b.bottom()-r.bottom()>=height+3:y=r.bottom()+4
        else:y=r.top()+3
        x=max(b.left(),min(r.left(),b.right()-width+1))
        self._label=QRect(x,max(b.top(),min(y,b.bottom()-height+1)),width,height)
        centers={'nw':r.topLeft(),'n':QPoint(r.center().x(),r.top()),'ne':r.topRight(),
                 'e':QPoint(r.right(),r.center().y()),'se':r.bottomRight(),
                 's':QPoint(r.center().x(),r.bottom()),'sw':r.bottomLeft(),'w':QPoint(r.left(),r.center().y())}
        self._handles={key:QRect(point.x()-handle//2,point.y()-handle//2,handle,handle).intersected(b)
                       for key,point in centers.items()} if self.editable else {}
        geometry=r.adjusted(-handle,-height-4,handle,handle).united(self._label).intersected(b)
        self.setGeometry(geometry)
        mask=QRegion()
        for rect in [*self._bands,*self._handles.values(),self._label]:
            mask=mask.united(QRegion(rect.intersected(b).translated(-geometry.topLeft())))
        self.setMask(mask)  # the unpainted middle belongs to the lecture app

    def paintEvent(self,event):
        p=QPainter(self);color=QColor(COLORS[self.phase]);origin=self.geometry().topLeft()
        for rect in self._bands:p.fillRect(rect.translated(-origin),color)
        for rect in self._handles.values():p.fillRect(rect.translated(-origin),color)
        label=self._label.translated(-origin);p.fillRect(label,color)
        p.setPen(Qt.black)
        size=f'{self.physical[2]}×{self.physical[3]} px' if self.physical else f'{self.selected.width()}×{self.selected.height()} DIP'
        hint=' | 드래그 이동' if self.editable else ''
        p.drawText(label.adjusted(5,0,-4,0),Qt.AlignVCenter|Qt.AlignLeft,f'{LABELS[self.phase]} | {size}{hint}')

    def _hit(self,point):
        for key,rect in self._handles.items():
            if rect.contains(point):return key
        if self._label.contains(point) or any(rect.contains(point) for rect in self._bands):return 'move'
        return None

    def mousePressEvent(self,event):
        if not self.editable or event.button()!=Qt.LeftButton:return
        point=event.globalPosition().toPoint();mode=self._hit(point)
        if mode:
            self._drag=(point,QRect(self.selected),mode)
            self.grabMouse();event.accept()

    def mouseMoveEvent(self,event):
        point=event.globalPosition().toPoint()
        if self._drag and self.editable:
            anchor,original,mode=self._drag;delta=point-anchor
            def values(rect):return rect.x(),rect.y(),rect.width(),rect.height()
            result=edit_region(values(original),delta.x(),delta.y(),mode,values(self.bounds))
            self.regionChanged.emit(QRect(*result))
        elif self.editable:
            mode=self._hit(point)
            cursors={'nw':Qt.SizeFDiagCursor,'se':Qt.SizeFDiagCursor,'ne':Qt.SizeBDiagCursor,'sw':Qt.SizeBDiagCursor,
                     'n':Qt.SizeVerCursor,'s':Qt.SizeVerCursor,'e':Qt.SizeHorCursor,'w':Qt.SizeHorCursor,'move':Qt.SizeAllCursor}
            self.setCursor(cursors.get(mode,Qt.ArrowCursor))

    def mouseReleaseEvent(self,event):
        self._cancel_drag()
        event.accept()

    def _cancel_drag(self):
        if self._drag:self.releaseMouse()
        self._drag=None

    def closeEvent(self,event):
        self._closing=True
        self._cancel_drag();event.accept()
