"""Physical desktop diagram picker and per-monitor logical overlay projection."""
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, Signal, QObject
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QDialogButtonBox, QHBoxLayout, QSpinBox
from .display import map_region, rect_tuple
from .desktop import validate_rect
from .overlay import RegionOverlay
from .window_capture import ExclusionStatus

class Diagram(QWidget):
    picked=Signal(object)
    def __init__(self,monitors,bounds):
        super().__init__();self.monitors=monitors;self.bounds=bounds;self.selection=bounds;self.anchor=None
        self.setMinimumSize(640,240)
    def transform(self):
        x,y,w,h=self.bounds
        scale=min((self.width()-20)/w,(self.height()-20)/h)
        return x,y,scale
    def physical(self,point):
        x,y,scale=self.transform();bx,by,bw,bh=self.bounds
        return (max(bx,min(round(x+(point.x()-10)/scale),bx+bw)),max(by,min(round(y+(point.y()-10)/scale),by+bh)))
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#202329'));x,y,scale=self.transform()
        def box(r):return QRectF(10+(r[0]-x)*scale,10+(r[1]-y)*scale,r[2]*scale,r[3]*scale)
        for m in self.monitors:
            q=box(m.rect);p.fillRect(q,QColor('#3c4d60'));p.setPen(Qt.white)
            p.drawRect(q);p.drawText(q,Qt.AlignCenter,f'{m.name}\n{m.rect[2]}×{m.rect[3]}\n({m.rect[0]}, {m.rect[1]})')
        p.setPen(QPen(QColor('#25b65a'),3));p.drawRect(box(self.selection))
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.anchor=self.physical(event.position())
    def mouseMoveEvent(self,event):
        if self.anchor is not None:
            x,y=self.physical(event.position());ax,ay=self.anchor
            self.selection=(min(ax,x),min(ay,y),max(1,abs(x-ax)),max(1,abs(y-ay)))
            self.picked.emit(self.selection);self.update()
    def mouseReleaseEvent(self,event):self.mouseMoveEvent(event);self.anchor=None

class DesktopDialog(QDialog):
    def __init__(self,entries,bounds,selected=None,parent=None):
        super().__init__(parent);self.setWindowTitle('두 화면 / 가상 데스크톱 영역 — 물리 픽셀')
        self.monitors=[m for s,m in entries];self.bounds=bounds;self.selected=selected or bounds
        grid=QVBoxLayout(self)
        grid.addWidget(QLabel('축소 배치도에서 드래그하거나 물리 좌표를 입력하세요. 화면 영상 미리보기는 아닙니다.\n음수 원점을 지원합니다. 화면 사이 빈 공간도 사각형에 포함될 수 있습니다.'))
        self.diagram=Diagram(self.monitors,bounds);grid.addWidget(self.diagram)
        row=QHBoxLayout();self.fields=[]
        for label,value in zip(('X','Y','너비','높이'),self.selected):
            row.addWidget(QLabel(label));field=QSpinBox();field.setRange(-100000,100000);field.setValue(value)
            row.addWidget(field);self.fields.append(field);field.valueChanged.connect(self.changed)
        grid.addLayout(row);self.diagram.picked.connect(self.set_fields)
        self.hint=QLabel();grid.addWidget(self.hint)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);grid.addWidget(self.buttons)
        self.changed();self.resize(900,460)
    def set_fields(self,values):
        for f,v in zip(self.fields,values):f.blockSignals(True);f.setValue(v);f.blockSignals(False)
        self.changed()
    def changed(self):
        self.selected=tuple(f.value() for f in self.fields);valid=True
        try:validate_rect(self.selected,self.bounds,self.monitors);message=f'물리 영역: {self.selected}'
        except Exception as exc:message=str(exc);valid=False
        self.diagram.selection=self.selected;self.diagram.update();self.hint.setText(message)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

class DesktopOverlay(QObject):
    regionChanged=Signal(object)
    def __init__(self):
        super().__init__();self.children_frames={};self.selected=None;self._anchors={}
        self.phase='idle';self.capture_active=False;self.physical=None
        self.exclusion=ExclusionStatus(False,'미확인');self.editable=False;self._active_frames=[]
    def hide(self):
        for child in self.children_frames.values():child._cancel_drag();child.hide()
    def close(self):
        for child in self.children_frames.values():child.close()
    def isVisible(self):return any(c.isVisible() for c in self.children_frames.values())
    def configure(self,physical,entries,phase,visible,editable,suspended,capture_active):
        self.selected=tuple(physical);self.physical=tuple(physical);self.phase=phase
        self.capture_active=capture_active;self.editable=editable
        active=[];roi=QRect(*physical)
        for screen,m in entries:
            key=m.name;intersection=roi.intersected(QRect(*m.rect))
            if intersection.isEmpty():continue
            if key not in self.children_frames:
                child=RegionOverlay();self.children_frames[key]=child
                child.moveRequested.connect(lambda point,original,dx,dy,k=key:self.move(k,dx,dy))
                child.regionChanged.connect(lambda rect,k=key:self.resize_region(k,rect))
            child=self.children_frames[key];logical=screen.geometry()
            selected=QRect(*map_region(rect_tuple(intersection),m.rect,rect_tuple(logical)))
            child._desktop_mapping=(m.rect,rect_tuple(logical))
            # Only external edges resize the overall physical region.
            edges=set()
            if intersection.left()==roi.left():edges.add('w')
            if intersection.right()==roi.right():edges.add('e')
            if intersection.top()==roi.top():edges.add('n')
            if intersection.bottom()==roi.bottom():edges.add('s')
            child.allowed_handles={mode for mode in ('n','s','e','w','ne','nw','se','sw') if all(c in edges for c in mode)}
            child.configure(selected,logical,rect_tuple(intersection),phase,visible,editable,suspended,capture_active)
            active.append(child)
        for child in self.children_frames.values():
            if child not in active:child._cancel_drag();child.hide()
        self._active_frames=active
        self.refresh_exclusion()
    def refresh_exclusion(self):
        applied=bool(self._active_frames) and all(c.exclusion.applied for c in self._active_frames)
        if self.capture_active and not applied:self.hide()
        self.exclusion=ExclusionStatus(applied,'모든 화면 테두리 제외 확인' if applied else '화면 테두리 제외 미확인 — 캡처 중 숨김')
    def initial(self,key):
        child=self.children_frames[key];drag=child._drag
        if not drag:return None
        marker=drag
        if self._anchors.get(key,(None,None))[0] is not marker:self._anchors[key]=(marker,self.selected)
        return self._anchors[key][1]
    def move(self,key,dx,dy):
        original=self.initial(key)
        if original is None or not self.editable:return
        physical,logical=self.children_frames[key]._desktop_mapping
        x,y,w,h=original
        self.regionChanged.emit((x+round(dx*physical[2]/logical[2]),y+round(dy*physical[3]/logical[3]),w,h))
    def resize_region(self,key,rect):
        original=self.initial(key)
        if original is None or not self.editable:return
        child=self.children_frames[key];physical,logical=child._desktop_mapping
        mapped=map_region(rect_tuple(rect),logical,physical)
        mode=child._drag[2];x,y,w,h=original;right=x+w;bottom=y+h
        if 'w' in mode:x=mapped[0]
        if 'e' in mode:right=mapped[0]+mapped[2]
        if 'n' in mode:y=mapped[1]
        if 's' in mode:bottom=mapped[1]+mapped[3]
        self.regionChanged.emit((x,y,right-x,bottom-y))
