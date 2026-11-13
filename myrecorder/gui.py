from __future__ import annotations
import os
from pathlib import Path
import sys
import time
import traceback
import uuid
from PySide6.QtCore import Qt, QRect, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QPushButton, QLabel,
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QMessageBox, QGridLayout, QDialog, QDialogButtonBox, QScrollArea)
from .recorder import Options, Recorder
from .media import binary
from .modes import RecordingPolicy, MODES
from .preferences import PreferencesStore
from .desktop import layout as desktop_layout, validate_rect
from .desktop_ui import DesktopDialog, DesktopOverlay
from .audio import Diagnostics, device_choices
from .titles import TitleError, foreground_window, list_windows, window_title, ocr_title
from .display import DisplayError, physical_region, capture_png, screen_snapshot
from .coordinate_log import new_coordinate_log
from .maintenance import saved_sessions, cleanup_sessions
from .overlay import RegionOverlay
from .settings import SettingsStore, StoragePaths, StorageError, prepare_storage, LABELS


class Job(QThread):
    done = Signal(object, str)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        try:
            self.done.emit(self.fn(), '')
        except Exception:
            self.done.emit(None, traceback.format_exc())


class RegionPicker(QWidget):
    selected = Signal(object)
    cancelled = Signal()
    def __init__(self, screen, purpose='녹화 영역'):

        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.origin = None
        self.accepted = False
        self.purpose = purpose
        self.rect = QRect()
        self.setCursor(Qt.CrossCursor)
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rectified_screen(), QColor(0, 0, 0, 95))
        painter.setPen(QPen(QColor('#ff5050'), 2))
        painter.drawRect(self.rect)
        painter.setPen(Qt.white)
        painter.drawText(20, 35, f'{self.purpose}: 마우스로 드래그. Esc: 취소 / 한 모니터 안에서 선택')
    def rectified_screen(self):
        return QRect(0, 0, self.width(), self.height())
    def mousePressEvent(self, event):
        self.origin = event.position().toPoint()
    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect = QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rectified_screen())
            self.update()
    def mouseReleaseEvent(self, event):
        if self.origin is None:return
        self.rect=QRect(self.origin,event.position().toPoint()).normalized().intersected(self.rectified_screen())
        if self.rect.width() >= 32 and self.rect.height() >= 32:
            self.accepted = True
            self.selected.emit(self.rect.translated(self.geometry().topLeft()))
            self.close()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        if not self.accepted: self.cancelled.emit()
        event.accept()


class StorageDialog(QDialog):
    def __init__(self, store, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle('설정 — 저장 경로')
        self.store = store
        self.paths = paths
        self.fields = {}
        grid = QGridLayout(self)
        intro = QLabel('녹화·변환·임시 파일을 분리합니다. OneDrive 및 개발 폴더는 사용할 수 없습니다.\n접근 가능한 폴더를 직접 선택하세요. 자동 대체 저장은 하지 않습니다.')
        intro.setWordWrap(True)
        grid.addWidget(intro, 0, 0, 1, 3)
        for row, (key, label) in enumerate(LABELS.items(), 1):
            field = QLineEdit(getattr(paths, key))
            self.fields[key] = field
            button = QPushButton('찾아보기')
            button.clicked.connect(lambda checked=False, f=field: self.choose(f))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(button, row, 2)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, 4, 0, 1, 3)
        self.resize(800, 240)

    def choose(self, field):
        # Empty initial directory lets Windows choose its browsing location; nothing is saved there automatically.
        selected = QFileDialog.getExistingDirectory(self, '저장 폴더 선택', '')
        if selected:
            field.setText(selected)

    def save(self):
        candidate = StoragePaths(**{k: field.text().strip() for k, field in self.fields.items()})
        try:
            directories = prepare_storage(candidate, self.store.root)
            candidate = StoragePaths(**{k: str(v) for k, v in directories.items()})
            self.store.save(candidate)
        except StorageError as exc:
            QMessageBox.warning(self, '저장 경로를 확인하세요', str(exc))
            return
        self.paths = candidate
        self.accept()


class Window(QMainWindow):
    def __init__(self, store=None, check_startup=True):
        super().__init__()
        self.setWindowTitle('MyRecorder V0.5.0 — Windows 11')
        self.settings = store or SettingsStore()
        self.paths = self.settings.load()
        self.preferences=PreferencesStore(self.settings.root)
        self.policy=self.preferences.load()
        self.desktop_mode=False
        self.desktop_entries=[]
        self.desktop_signature=None
        self.recorder = None
        self.state = 'idle'
        self.job = None
        self.last = None
        self.region_screen = QApplication.primaryScreen()
        self.region = self.region_screen.geometry()
        self.last_external_window = None
        self.ocr_region = None
        self.ocr_screen = None
        self.ocr_executable = None
        self.capture_pending = False
        self.picker_pending = False
        self.title_source = 'default'
        self._last_idle_validation = 0.0
        self.region_valid = False
        self.engine_error = None
        try:
            binary('ffmpeg');binary('ffprobe')
        except RuntimeError as exc:self.engine_error=str(exc)
        self.coordinate_log = None
        self.coordinate_log_folder = None
        self.coordinate_log_error = None
        self._last_coordinate_preview = 0.0

        self._recording_transition = False
        self._last_overlay_policy = None
        self.border = RegionOverlay()
        self.border.regionChanged.connect(self.overlay_region_changed)
        self.border.moveRequested.connect(self.overlay_move_requested)
        self.desktop_border=DesktopOverlay()
        self.desktop_border.regionChanged.connect(self.edit_desktop_region)
        self.picker = None
        root = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        grid = QGridLayout(root)
        self.default_title = time.strftime('강의_%Y%m%d_%H%M%S')
        self.recording_type=QComboBox()
        for key,label in MODES.items():self.recording_type.addItem(label,key)
        self.recording_type.setCurrentIndex(self.recording_type.findData(self.policy.mode))
        self.recording_type.currentIndexChanged.connect(self.change_recording_type)
        self.mode_hint=QLabel(self.policy.instructions);self.mode_hint.setWordWrap(True)
        self.title = QLineEdit(self.default_title)
        self.title.textEdited.connect(lambda text: setattr(self, 'title_source', 'manual'))
        self.title_button = QPushButton('제목 자동 인식')
        self.title_button.clicked.connect(self.recognize_title)
        self.title_mode = QComboBox()
        self.title_mode.addItem('창 제목', 'window')
        self.title_mode.addItem('영역 OCR (수동)', 'ocr')
        self.lecture_window = QComboBox()
        self.lecture_window.addItem('직전 활성 창 (녹화 앱 제외)', None)
        self.window_refresh = QPushButton('강의 창 목록 새로고침')
        self.window_refresh.clicked.connect(self.refresh_title_windows)
        self.ocr_pick = QPushButton('OCR 제목 영역 선택')
        self.ocr_pick.clicked.connect(self.select_ocr_region)
        self.ocr_language = QComboBox()
        for label, value in [('한국어+영어','kor+eng'),('영어','eng'),('한국어','kor')]:
            self.ocr_language.addItem(label,value)
        self.ocr_engine = QPushButton('OCR 엔진 선택 (선택 사항)')
        self.ocr_engine.clicked.connect(self.choose_ocr_engine)
        self.title_hint = QLabel('녹화 전 버튼으로만 인식합니다. 결과를 수정할 수 있고 실패하면 기존 제목을 유지합니다.')
        self.title_hint.setWordWrap(True)
        self.cleanup_button = QPushButton('완료 세션 임시 파일 정리')
        self.cleanup_button.clicked.connect(self.clean_completed_sessions)

        self.folder = QLineEdit(self.paths.recordings)
        self.folder.setReadOnly(True)
        self.folder.setToolTip('저장 경로 설정에서 변경할 수 있습니다.')
        self.browse = QPushButton('저장 경로 설정')
        self.browse.clicked.connect(self.choose_folder)
        self.screen = QComboBox()
        for i, screen in enumerate(QApplication.screens()):
            self.screen.addItem(f'화면 {i+1}: {screen.name()} ({screen.geometry().width()}×{screen.geometry().height()})',screen)
        self.full = QPushButton('선택 모니터 전체')
        self.pick = QPushButton('영역 드래그 선택')
        self.full.clicked.connect(self.fullscreen)
        self.pick.clicked.connect(self.select_region)
        self.display_diagnose = QPushButton('화면 좌표 진단')
        self.display_diagnose.clicked.connect(self.diagnose_display)
        self.desktop_pick=QPushButton('두 화면에 걸친 영역')
        self.desktop_pick.clicked.connect(self.select_desktop_region)
        self.desktop_full=QPushButton('전체 가상 데스크톱')
        self.desktop_full.clicked.connect(self.full_desktop)
        self.region_label = QLabel()
        self.region_label.setWordWrap(True)
        self.border_toggle=QCheckBox('녹화 영역 테두리 표시')
        self.border_toggle.setChecked(True)
        self.border_toggle.toggled.connect(self.sync_overlay)
        self.border_hint=QLabel()
        self.border_hint.setWordWrap(True)
        self.region_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.system = QCheckBox('시스템 소리')
        self.system.setChecked(True)
        self.output_device = QComboBox()
        self.output_device.addItem('Windows 기본 WASAPI 출력 장치 (자동)', None)
        self.refresh_devices_button = QPushButton('오디오 장치 새로고침')
        self.refresh_devices_button.clicked.connect(self.refresh_audio_devices)
        self.audio_hint = QLabel('기본 출력은 자동 탐지됩니다. 직접 선택하려면 장치 목록을 새로고침하세요.')
        self.audio_hint.setWordWrap(True)
        self.mic = QCheckBox('마이크 (기본 입력 장치)')
        self.cursor = QCheckBox('마우스 커서 포함')
        self.cursor.setChecked(True)
        self.fps = QComboBox()
        self.fps.addItems(['15', '30', '60'])
        self.fps.setCurrentText('30')
        self.quality = QComboBox()
        self.quality.addItems(['고화질', '표준', '작은 용량'])
        self.quality.setCurrentIndex(1)
        self.start_button = QPushButton('녹화 시작')
        self.pause_button = QPushButton('일시정지')
        self.stop_button = QPushButton('종료 / MP4 저장')
        self.open_button = QPushButton('저장 폴더 열기')
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        self.open_button.clicked.connect(self.open_folder)
        self.clock = QLabel('00:00:00')
        self.clock.setStyleSheet('font-size: 28px; font-weight: bold;')
        self.status = QLabel('대기 — 제목과 녹화 영역을 확인하세요.')
        self.status.setWordWrap(True)
        rows = [(QLabel('녹화 유형'),self.recording_type), (self.mode_hint,), (QLabel('강의 제목'), self.title, self.title_button),
                (self.title_mode, self.lecture_window, self.window_refresh),
                (self.ocr_pick, self.ocr_language, self.ocr_engine), (self.title_hint,), (QLabel('저장 경로'), self.folder, self.browse),
                (self.screen, self.full, self.pick), (self.desktop_pick,self.desktop_full), (self.region_label, self.display_diagnose),
                (self.border_toggle,QLabel('대기 중: 테두리 이동 / 모서리 크기 조절'),self.border_hint),
                (self.system, self.mic, self.cursor),
                (QLabel('시스템 출력 장치'), self.output_device, self.refresh_devices_button), (self.audio_hint,), (QLabel('FPS'), self.fps, self.quality),
                (self.start_button, self.pause_button, self.stop_button), (self.clock, self.open_button, self.cleanup_button), (self.status,)]
        for r, widgets in enumerate(rows):
            for c, widget in enumerate(widgets):
                grid.addWidget(widget, r, c, 1, 3 if len(widgets)==1 else 1)
        self.controls = [self.recording_type,self.desktop_pick,self.desktop_full,self.title, self.folder, self.browse, self.screen, self.full, self.pick, self.system, self.mic, self.cursor, self.fps, self.quality, self.output_device, self.refresh_devices_button,
                         self.display_diagnose, self.title_button, self.title_mode, self.lecture_window, self.window_refresh,
                         self.ocr_pick, self.ocr_language, self.ocr_engine, self.cleanup_button]
        for key, fn in [('Ctrl+Shift+R', self.start), ('Ctrl+Shift+P', self.pause), ('Ctrl+Shift+S', self.stop)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(fn)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        self.fullscreen()
        self.refresh()
        self.resize(1000, 690)
        if check_startup:
            QTimer.singleShot(0, self.startup_checks)

    def startup_checks(self):
        if self.check_storage() and os.name == 'nt':
            self.refresh_audio_devices()

    def refresh_audio_devices(self):
        if self.state != 'idle' or self.job or not self.check_storage():
            return
        selected = self.output_device.currentData()
        def work():
            log = Diagnostics(Path(self.paths.temp)/('audio-devices-'+uuid.uuid4().hex+'.jsonl'))
            try:
                return device_choices(log), str(log.path)
            except Exception as exc:
                log.write('discovery_failed', error=str(exc))
                raise RuntimeError(f'{exc}\n장치 진단 로그: {log.path}') from exc
        def finished(result):
            choices, log_path = result
            self.output_device.clear()
            self.output_device.addItem('Windows 기본 WASAPI 출력 장치 (자동)', None)
            for device in choices:
                detail = f"{device.get('channels', '?')}ch / {device.get('rate', '?')}Hz → Loopback ID {device.get('loopback_index', '?')}"
                label = f"{device['name']} [출력 ID {device['index']}] — {detail}"
                if device['default']: label += ' (기본값)'
                if not device['available']: label += ' (Loopback 사용 불가)'
                self.output_device.addItem(label, device)
                if selected and selected.get('index') == device['index'] and selected.get('name') == device['name']:
                    self.output_device.setCurrentIndex(self.output_device.count()-1)
            default = next((d['name'] for d in choices if d['default']), '탐지하지 못함')
            self.audio_hint.setText(f'현재 WASAPI 기본 출력: {default}\n장치 진단 로그: {log_path}')
            self.status.setText('장치 조회 완료. 실제 소리를 내는 출력 장치를 선택하세요. 무음 영상은 시스템 소리·마이크를 모두 해제하세요.')
        self.status.setText('Windows WASAPI 출력·Loopback 장치 조회 중…')
        self.submit(work, finished)

    def refresh_title_windows(self):
        if self.state != 'idle' or self.job or self.capture_pending or self.picker_pending: return
        selected = self.lecture_window.currentData()
        def finished(windows):
            self.lecture_window.clear()
            self.lecture_window.addItem('직전 활성 창 (녹화 앱 제외)',None)
            for item in windows:
                self.lecture_window.addItem(item.title,item.hwnd)
                if selected == item.hwnd: self.lecture_window.setCurrentIndex(self.lecture_window.count()-1)
            self.title_hint.setText('강의 창을 선택하고 제목 자동 인식을 누르세요. 숨은 브라우저 탭은 읽지 않습니다.')
        self.submit(list_windows,finished,on_error=self.title_failed)

    def title_failed(self, error):
        if not self.title.text().strip(): self.title.setText(self.default_title)
        self.title_hint.setText('제목 인식 실패 — 기존 제목을 유지했습니다. 직접 입력하거나 다시 선택하세요.')
        QMessageBox.warning(self,'제목 인식',str(error)[-1800:])

    def apply_title(self, title, source):
        self.title.setText(title)
        self.title_source = source
        self.title_hint.setText('제목 인식 완료. 녹화 시작 전 강의 제목을 확인하고 필요하면 수정하세요.')

    def recognize_title(self):
        if self.state != 'idle' or self.job or self.capture_pending or self.picker_pending: return
        if self.title_mode.currentData() == 'window':
            hwnd = self.lecture_window.currentData()
            if hwnd is None and self.last_external_window is not None:
                hwnd = self.last_external_window.hwnd
            if hwnd is None:
                self.title_failed('활성 강의 창을 확인하지 못했습니다. 강의 창 목록에서 직접 선택하세요.')
                return
            self.submit(lambda:window_title(hwnd),lambda title:self.apply_title(title,'window'),on_error=self.title_failed)
            return
        if self.ocr_region is None or self.ocr_screen not in QApplication.screens():
            self.title_failed('먼저 OCR 제목 영역을 선택하세요.')
            return
        self.capture_pending = True
        self.refresh()
        visible = self.isVisible()
        self.hide()  # keep the recorder UI out of the selected title image
        def capture():
            error = None
            try:
                png = capture_png(self.ocr_screen,self.ocr_region)
            except Exception as exc:
                error = str(exc)
            finally:
                if visible: self.show()
                self.capture_pending = False
                self.refresh()
            if error is not None:
                self.title_failed(error)
                return
            language = self.ocr_language.currentData()
            executable = self.ocr_executable
            self.title_hint.setText('OCR 처리 중… 이미지·인식 결과는 디스크에 저장하지 않습니다.')
            self.submit(lambda:ocr_title(png,language,executable),
                        lambda title:self.apply_title(title,'ocr'),on_error=self.title_failed)
        QTimer.singleShot(180,capture)

    def select_ocr_region(self):
        if self.state != 'idle' or self.job or self.capture_pending or self.picker_pending: return
        screen = self.current_screen()
        def selected(rect):
            self.ocr_region,self.ocr_screen=rect,screen
            self.title_hint.setText(f'OCR 영역 선택됨: {rect.width()}×{rect.height()} 논리 픽셀. 영역 OCR 모드에서 제목 자동 인식을 누르세요.')
        self.open_picker(screen,'OCR 제목 영역',selected)

    def choose_ocr_engine(self):
        path,_ = QFileDialog.getOpenFileName(self,'Tesseract 실행 파일 선택','','실행 파일 (*.exe);;모든 파일 (*)')
        if path:
            self.ocr_executable=path
            self.title_hint.setText('OCR 엔진이 선택되었습니다. 한국어 인식에는 kor 언어 데이터가 필요합니다.')

    def clean_completed_sessions(self):
        if self.state != 'idle' or self.job or self.capture_pending or self.picker_pending or not self.check_storage(): return
        def preview(candidates):
            if not candidates:
                QMessageBox.information(self,'임시 파일 정리','완료 MP4를 검증할 수 있는 V0.4 세션이 없습니다. 실패/이전 버전 세션은 보존합니다.')
                return
            total=sum(c.bytes for c in candidates)
            text=f'{len(candidates)}개 완료 세션의 임시 파일 {total/1024**2:.1f}MB를 삭제합니다. 최종 MP4는 유지합니다.\n'
            text+='\n'.join(str(c.folder) for c in candidates[:10])
            answer=QMessageBox.question(self,'완료 임시 세션 삭제 확인',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer==QMessageBox.Yes:
                self.submit(lambda:cleanup_sessions(Path(self.paths.temp),[c.folder for c in candidates]),
                            lambda removed:self.status.setText(f'완료 임시 세션 {len(removed)}개를 정리했습니다.'))
        self.submit(lambda:saved_sessions(Path(self.paths.temp)),preview)

    def open_picker(self, screen, purpose, selected):
        self.picker_pending=True
        self.refresh()
        self.picker=RegionPicker(screen,purpose)
        def done(rect):
            self.picker_pending=False
            selected(rect)
            self.refresh()
        def cancelled():
            self.picker_pending=False
            self.refresh()
        self.picker.selected.connect(done)
        self.picker.cancelled.connect(cancelled)
        self.picker.show()

    def change_recording_type(self):
        requested=self.recording_type.currentData()
        if self.state!='idle' or self.job or self._recording_transition:
            self.recording_type.blockSignals(True)
            self.recording_type.setCurrentIndex(self.recording_type.findData(self.policy.mode))
            self.recording_type.blockSignals(False);return
        try:
            policy=RecordingPolicy(requested);self.preferences.save(policy)
        except (ValueError,StorageError) as exc:
            QMessageBox.warning(self,'녹화 유형 설정',str(exc))
            self.recording_type.blockSignals(True);self.recording_type.setCurrentIndex(self.recording_type.findData(self.policy.mode));self.recording_type.blockSignals(False);return
        self.policy=policy;self.mode_hint.setText(policy.instructions)

    def active_border(self):return self.desktop_border if self.desktop_mode else self.border

    def set_desktop_region(self,physical,entries,bounds,signature):
        if self.state!='idle' or self.job or self._recording_transition:return
        physical=validate_rect(tuple(physical),bounds,[m for s,m in entries])
        self.desktop_mode=True;self.region=QRect(*physical)
        self.desktop_entries=entries;self.desktop_bounds=bounds;self.desktop_signature=signature
        self.refresh()

    def full_desktop(self):
        if self.state!='idle' or self.job:return
        try:
            entries,bounds,signature=desktop_layout(QApplication.screens(),self.coordinate_event,'full_desktop')
            self.set_desktop_region(bounds,entries,bounds,signature)
        except DisplayError as exc:QMessageBox.warning(self,'가상 데스크톱',str(exc)+'\n'+self.coordinate_log_location())

    def select_desktop_region(self):
        if self.state!='idle' or self.job:return
        try:
            entries,bounds,signature=desktop_layout(QApplication.screens(),self.coordinate_event,'desktop_picker')
            self.picker_pending=True;self.refresh()
            try:
                dialog=DesktopDialog(entries,bounds,tuple((self.region.x(),self.region.y(),self.region.width(),self.region.height())) if self.desktop_mode else None,self)
                accepted=dialog.exec()==QDialog.Accepted
            finally:self.picker_pending=False;self.refresh()
            if accepted:self.set_desktop_region(dialog.selected,entries,bounds,signature)
        except DisplayError as exc:QMessageBox.warning(self,'가상 데스크톱',str(exc)+'\n'+self.coordinate_log_location())

    def edit_desktop_region(self,physical):
        if self.state!='idle' or self.job or self._recording_transition:return
        x,y,w,h=physical;bx,by,bw,bh=self.desktop_bounds
        if w<32 or h<32:return
        physical=(max(bx,min(x,bx+bw-w)),max(by,min(y,by+bh-h)),w,h)
        try:
            # Keep original layout identity; do not silently adopt a changed monitor.
            self.map_selected('desktop_edit')
            validate_rect(physical,self.desktop_bounds,[m for s,m in self.desktop_entries])
            self.region=QRect(*physical);self.refresh()
        except DisplayError as exc:self.status.setText(str(exc))

    def current_screen(self):
        screen=self.screen.currentData()
        if screen not in QApplication.screens():
            raise DisplayError('화면 연결이 변경되었습니다. 앱을 재시작하세요.','SELECTED_SCREEN_REMOVED')
        return screen
    def fullscreen(self):
        self.set_region(self.current_screen().geometry())
    def set_region(self, rect, screen=None):
        if self.state!='idle' or self._recording_transition:return
        self.desktop_mode=False
        self.desktop_border.hide()
        self.region = QRect(rect)
        self.region_screen = screen or self.current_screen()
        self.selected_screen_identity = screen_snapshot(self.region_screen)
        self.refresh()
    def overlay_move_requested(self, point, original, dx, dy):
        if self.state!='idle' or self.job or self.capture_pending or self.picker_pending or self._recording_transition:return
        from .regions import move_to_monitor
        screens=QApplication.screens()
        values=lambda rect:(rect.x(),rect.y(),rect.width(),rect.height())
        target=QApplication.screenAt(point)
        if target not in screens:return  # gaps in a mixed-DPI desktop are not screens
        bounds=target.geometry()
        result=move_to_monitor(values(original),dx,dy,values(bounds))
        # Validate target identity and physical coordinates before changing ownership.
        try:physical_region(target,QRect(*result),qt_screens=screens,
                            diagnostics=self.coordinate_event,operation='overlay_monitor_transfer')
        except DisplayError as exc:
            self.status.setText(str(exc));return
        index=next((i for i in range(self.screen.count()) if self.screen.itemData(i)==target),-1)
        if index>=0:self.screen.setCurrentIndex(index)
        self.set_region(QRect(*result),target)

    def overlay_region_changed(self, rect):
        if self.state!='idle' or self.job or self.capture_pending or self.picker_pending or self._recording_transition:
            return
        self.set_region(rect,self.region_screen)

    def coordinate_log_location(self):
        if self.coordinate_log and not self.coordinate_log_error:return f'진단 로그: {self.coordinate_log.path}'
        return '진단 로그 저장 실패: '+str(self.coordinate_log_error or 'Temp 경로를 확인하세요.')

    def coordinate_event(self, event, **fields):
        try:
            if self.coordinate_log is None or self.coordinate_log_folder!=self.paths.temp:
                self.coordinate_log=new_coordinate_log(self.paths,self.settings.root)
                self.coordinate_log_folder=self.paths.temp
            self.coordinate_log.write(event,**fields)
            self.coordinate_log_error=self.coordinate_log.error
        except Exception as exc:self.coordinate_log_error=str(exc)

    def map_selected(self, operation):
        if self.desktop_mode:
            now=time.monotonic();log=operation!='preview' or now-self._last_coordinate_preview>=1
            if log:self._last_coordinate_preview=now
            entries,bounds,signature=desktop_layout(QApplication.screens(),self.coordinate_event if log else None,operation)
            if signature!=self.desktop_signature:
                self.coordinate_event('desktop_mapping_failed',operation=operation,failed_condition='SCREEN_LAYOUT_CHANGED')
                raise DisplayError('선택 후 화면 구성이 바뀌었습니다. 데스크톱 영역을 다시 선택하세요.','SCREEN_LAYOUT_CHANGED')
            try:result=validate_rect((self.region.x(),self.region.y(),self.region.width(),self.region.height()),bounds,[m for s,m in entries])
            except DisplayError as exc:
                self.coordinate_event('desktop_mapping_failed',operation=operation,failed_condition=exc.code,selected_region=(self.region.x(),self.region.y(),self.region.width(),self.region.height()))
                raise
            self.desktop_entries=entries
            if log:self.coordinate_event('desktop_mapping_ok',operation=operation,physical_region=result)
            return result
        if self.region_screen not in QApplication.screens():
            self.coordinate_event('display_mapping_failed',operation=operation,failed_condition='SELECTED_SCREEN_REMOVED')
            raise DisplayError('선택한 화면 연결이 변경되었습니다. 다시 선택하세요.','SELECTED_SCREEN_REMOVED')
        current=screen_snapshot(self.region_screen)
        selected=getattr(self,'selected_screen_identity',current)
        if current!=selected:
            self.coordinate_event('display_mapping_failed',operation=operation,failed_condition='SCREEN_LAYOUT_CHANGED',
                selection_screen=selected,current_screen=current)
            raise DisplayError('선택 후 화면 좌표 또는 배율이 변경되었습니다. 영역을 다시 선택하세요.','SCREEN_LAYOUT_CHANGED')
        now=time.monotonic()
        log=operation!='preview' or now-self._last_coordinate_preview>=1
        if log:self._last_coordinate_preview=now
        return physical_region(self.region_screen,self.region,qt_screens=QApplication.screens(),
            diagnostics=self.coordinate_event if log else None,operation=operation)

    def diagnose_display(self):
        if self.state!='idle' or self.job:return
        try:
            rect=self.map_selected('manual_diagnosis')
            message=f'선택 영역의 물리 좌표: {rect}\n'+self.coordinate_log_location()
        except DisplayError as exc:message=str(exc)+'\n'+self.coordinate_log_location()
        QMessageBox.information(self,'화면 좌표 진단',message)

    def sync_overlay(self, *unused):
        if not hasattr(self,'border_toggle'):return
        if not self.desktop_mode and self.region_screen not in QApplication.screens():
            self.region_valid=False
            self.border.hide()
            self.border_hint.setText('모니터가 변경되었습니다. 영역을 다시 선택하세요.')
            return
        physical=None
        try:physical=self.map_selected('preview')
        except DisplayError as exc:
            self.status.setText('화면 좌표 확인 필요: '+str(exc))
        self.region_valid=physical is not None
        live=getattr(self.recorder,'process',None) is not None
        phase='saving' if self.state=='saving' else 'save_failed' if self.state=='save_failed' else 'recording' if self.state=='recording' or self._recording_transition or live else 'paused' if self.state=='paused' else 'idle'
        editable=self.state=='idle' and not self.job and not self.capture_pending and not self.picker_pending and not self._recording_transition
        if self.desktop_mode:
            self.border.hide()
            if physical is not None:
                self.desktop_border.configure(physical,self.desktop_entries,phase,self.border_toggle.isChecked(),editable,
                    self.capture_pending or self.picker_pending,self._recording_transition or self.state=='recording' or live)
            else:self.desktop_border.hide()
            self.region_label.setText(f'가상 데스크톱 물리 영역: {physical or "확인 필요"}')
            self.update_overlay_feedback();return
        self.desktop_border.hide()
        self.border.configure(self.region,self.region_screen.geometry(),physical,phase,
            visible=self.border_toggle.isChecked(),editable=editable,
            suspended=self.capture_pending or self.picker_pending,
            capture_active=self._recording_transition or self.state=='recording' or getattr(self.recorder,'process',None) is not None)
        rect=self.region
        logical=f'선택 영역(논리): ({rect.x()}, {rect.y()}) {rect.width()}×{rect.height()}'
        pixels=f' | 물리 크기: {physical[2]}×{physical[3]} px' if physical else ' | 물리 크기 확인 필요'
        self.region_label.setText(logical+pixels)
        self.update_overlay_feedback()

    def update_overlay_feedback(self):
        if self.desktop_mode:self.desktop_border.refresh_exclusion()
        border=self.active_border()
        if not self.desktop_mode and self.region_screen not in QApplication.screens():
            self.region_valid=False
            border.hide()
            self.border_hint.setText('모니터가 변경되었습니다. 영역을 다시 선택하세요.')
            return
        if not self.border_toggle.isChecked():self.border_hint.setText('테두리 숨김')
        elif self.capture_pending or self.picker_pending:self.border_hint.setText('영역 선택/OCR 중 일시 숨김')
        elif not border.exclusion.applied:
            self.border_hint.setText('영상 제외 미확인 — 녹화 중 테두리 자동 숨김')
        else:self.border_hint.setText('영상 제외 속성 적용 · 녹화/일시정지 중 영역 고정')
        policy=self.overlay_policy()
        if policy!=self._last_overlay_policy:
            events=getattr(self.recorder,'events',None)
            if events:events.write('overlay_state',**policy)
            self._last_overlay_policy=policy

    def overlay_policy(self):
        border=self.active_border()
        return {'phase':border.phase,'capture_active':border.capture_active,
                'physical_rect':border.physical,'requested_visible':self.border_toggle.isChecked(),'visible':border.isVisible(),
                'exclusion_applied':border.exclusion.applied,'reason':border.exclusion.reason,
                'error_code':border.exclusion.error_code}

    def select_region(self):
        screen=self.current_screen()
        self.open_picker(screen,'녹화 영역',lambda rect:self.set_region(rect,screen))
    def check_storage(self):
        try:
            prepare_storage(self.paths, self.settings.root)
            self.status.setText('저장 폴더 준비 완료')
            return True
        except StorageError as exc:
            self.status.setText('저장 경로 오류 — 녹화를 시작할 수 없습니다. 저장 경로 설정을 확인하세요.')
            QMessageBox.warning(self, '드라이브 / 저장 경로 확인', str(exc))
            self.choose_folder()
            return False

    def choose_folder(self):
        if self.state != 'idle' or self.job:
            return
        dialog = StorageDialog(self.settings, self.paths, self)
        if dialog.exec() == QDialog.Accepted:
            self.paths = dialog.paths
            self.folder.setText(self.paths.recordings)
            self.status.setText('저장 경로 설정 완료. 다음 실행에도 유지됩니다.')

    def refresh(self):
        self.sync_overlay()
        busy = self.job is not None or self.capture_pending or self.picker_pending or self._recording_transition
        for control in self.controls:
            control.setEnabled(self.state == 'idle' and not busy)
        self.start_button.setEnabled(self.state == 'idle' and not busy and self.region_valid and self.engine_error is None and self.recorder is None)
        self.start_button.setToolTip(self.engine_error or ('화면 좌표 진단으로 영역을 확인하세요.' if not self.region_valid else '선택한 영역으로 새 녹화 시작'))
        self.start_button.setText('준비 중…' if self._recording_transition else '녹화 시작')
        self.pause_button.setEnabled(self.state in ('recording', 'paused') and not busy)
        self.pause_button.setText('재개' if self.state == 'paused' else '일시정지')
        self.stop_button.setEnabled(self.state in ('recording', 'paused', 'save_failed') and not busy)
        self.stop_button.setText('저장 중…' if self.state=='saving' else '저장 재시도' if self.state=='save_failed' else '종료 / MP4 저장')
        self.border_toggle.setEnabled(not busy)
    def submit(self, fn, success, reset_start=False, on_error=None):
        if self.job is not None:
            return
        self.job = Job(fn)
        def done(result, error):
            job = self.job
            job.wait()
            self.job = None
            job.deleteLater()
            if error and on_error:
                on_error(error)
            elif error:
                was_saving=self.state=='saving'
                self._recording_transition=False
                recovery = str(self.recorder.folder) if self.recorder else self.paths.temp
                if reset_start and (self.recorder is None or (self.recorder.process is None and not getattr(self.recorder,'audio',[]))):
                    self.state = 'idle'
                    self.recorder = None
                elif was_saving:
                    self.state='save_failed'
                elif self.recorder:
                    self.state = 'save_failed' if self.recorder.process is not None or getattr(self.recorder,'audio',[]) else 'paused'
                self.status.setText('오류 — 임시 파일 보존됨: ' + recovery)
                self.refresh()
                QMessageBox.critical(self, '오류 / 복구 경로', error[-4500:] + '\n\n임시 파일: ' + recovery)
            else:
                success(result)
            self.refresh()
        self.job.done.connect(done)
        self.job.start()
        self.refresh()
    def start(self):
        if not self.policy.permits('start',self.state) or self.job or self.capture_pending or self.picker_pending:
            return
        if self.recorder is not None:return
        if self.engine_error:
            QMessageBox.warning(self,'녹화 엔진 준비',self.engine_error);return
        if not self.check_storage():
            return
        try:
            if not self.desktop_mode and self.region_screen not in QApplication.screens():
                raise DisplayError('녹화 모니터가 변경되었습니다. 다시 선택하세요.')
            physical = self.map_selected('recording_start')
        except DisplayError as exc:
            QMessageBox.warning(self,'화면 좌표 / DPI 확인',str(exc)+'\n'+self.coordinate_log_location())
            return
        opts = Options(folder=Path(self.paths.recordings), title=self.title.text(),
            rect=physical, temp_folder=Path(self.paths.temp),
            converted_folder=Path(self.paths.converted), fps=int(self.fps.currentText()),
            crf=[18, 23, 28][self.quality.currentIndex()], cursor=self.cursor.isChecked(),
            system=self.system.isChecked(), mic=self.mic.isChecked(),
            system_device=self.output_device.currentData(), title_source=self.title_source,recording_mode=self.policy.mode)
        def work():
            self.recorder = Recorder(opts)
            events=getattr(self.recorder,'events',None)
            if events:events.write('overlay_capture_policy',**policy)
            self.recorder.start()
        self._recording_transition=True
        self.set_clock(0)
        self.sync_overlay()
        policy=self.overlay_policy()
        self.status.setText('장치 준비 중… 선택한 출력 장치로 소리를 재생하세요. 첫 패킷 지연은 즉시 실패 처리하지 않습니다.')
        self.submit(work, self.started, reset_start=True)
    def started(self, _):
        self._recording_transition=False
        self.state = 'recording'
        self.sync_overlay()
        self.status.setText('녹화 중 — ' + self.recorder.audio_status())
    def pause(self):
        if self.job or not self.policy.permits('resume' if self.state=='paused' else 'pause',self.state):
            return
        if self.state == 'paused':
            self._recording_transition=True
            self.sync_overlay()
            events=getattr(self.recorder,'events',None)
            if events:events.write('overlay_resume_policy',**self.overlay_policy())
            self.submit(self.recorder.start, self.started)
        else:
            def finished(_):
                self.state = 'paused'
                self.sync_overlay()
                self.status.setText('일시정지 — 구간 파일 보존됨')
            self.submit(self.recorder.pause, finished)
    def stop(self):
        if self.job or not self.policy.permits('stop',self.state):
            return
        self.state='saving'
        self.sync_overlay()
        self.status.setText('MP4 저장 중… 창을 닫지 마세요.')
        def finished(path):
            previous=self.recorder
            self.last=path
            duration=previous.final_duration if previous.final_duration is not None else previous.elapsed
            warnings=list(dict.fromkeys(previous.manifest['warnings']))
            log=previous.diagnostics.path
            # Release session ownership BEFORE restoring editable idle UI.
            self.recorder=None
            self._recording_transition=False
            self.state='idle'
            self.set_clock(duration)
            self.refresh()
            self.status.setText('저장 완료: '+str(path)+'\n대기 — 같은 영역으로 시작하거나 초록 테두리를 이동하세요. 임시 원본은 보존되었습니다.')
            if warnings:
                QMessageBox.warning(self,'저장 완료 / 오디오 확인 필요','\n'.join(warnings)[-3000:]+f'\n로그: {log}\n영상은 저장되었습니다. 오디오를 직접 확인하세요.')
        self.submit(self.recorder.finish, finished)
    def set_clock(self, seconds):
        seconds=max(0,int(seconds))
        self.clock.setText(f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')

    def tick(self):
        self.update_overlay_feedback()
        if self.state=='idle' and not self.job and time.monotonic()-self._last_idle_validation>=1:
            self._last_idle_validation=time.monotonic()
            self.refresh()
        if self.state=='idle' and not self.job and os.name=='nt':
            try:
                external=foreground_window()
                if external is not None: self.last_external_window=external
            except TitleError: pass
        if not self.recorder:
            return
        seconds = self.recorder.elapsed
        if self.recorder.process:
            now = self.recorder.stop_requested_at or time.monotonic()
            seconds += max(0,now-self.recorder.started)
        self.set_clock(seconds)
        if self.state == 'recording' and not self.job:
            error = self.recorder.health()
            if error:
                self.status.setText(error)
                self.pause()
            else:
                self.status.setText('녹화 중 — ' + self.recorder.audio_status())
    def open_folder(self):
        path = self.last.parent if self.last else Path(self.folder.text())
        try:
            os.startfile(str(path))
        except Exception as exc:
            QMessageBox.warning(self, '폴더 열기 실패', str(exc))
    def closeEvent(self, event):
        if self.job or self.capture_pending or self.state in ('recording','saving') or (self.recorder is not None and (self.recorder.process is not None or getattr(self.recorder,'audio',[]))):
            QMessageBox.information(self,'작업 진행 중','녹화 중이면 종료 / MP4 저장을 완료하고, 인식·저장 작업 중이면 완료된 뒤 창을 닫으세요.')
            event.ignore()
            return
        if self.state in ('paused','save_failed') and self.recorder is not None:
            answer=QMessageBox.question(self,'원본을 보존하고 종료',
                f'MP4 저장을 완료하지 않았습니다. 원본 세션을 보존하고 종료할까요?\n{self.recorder.folder}',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:
                event.ignore()
                return
            self.recorder.events.write('closed_without_final_mp4')
        if self.picker is not None: self.picker.close()
        self.border.close()
        self.desktop_border.close()
        event.accept()


def main():
    if os.name != 'nt':
        raise SystemExit('MyRecorder GUI는 Windows 11/10 전용입니다.')
    from .dpi_bootstrap import prepare_dpi
    state=prepare_dpi()
    if state.get('error'):raise SystemExit(str(state))
    app = QApplication(sys.argv)
    try:
        window = Window()
    except StorageError as exc:
        QMessageBox.critical(None, '설정 파일 오류', str(exc))
        raise SystemExit(1)
    window.show()
    sys.exit(app.exec())
