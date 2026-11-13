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
from .audio import Diagnostics, device_choices
from .titles import TitleError, foreground_window, list_windows, window_title, ocr_title
from .display import DisplayError, physical_region, capture_png
from .maintenance import saved_sessions, cleanup_sessions
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
            self.rect = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()
    def mouseReleaseEvent(self, event):
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


class Border(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor('#ff4040'), 2))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
    def mark(self, rect):
        # Draw outside the selected capture rectangle to minimize border capture.
        self.setGeometry(rect.adjusted(-3, -3, 3, 3))
        self.show()


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
        self.setWindowTitle('MyRecorder V0.4 — Windows 11')
        self.settings = store or SettingsStore()
        self.paths = self.settings.load()
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

        self.border = Border()
        self.picker = None
        root = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        grid = QGridLayout(root)
        self.default_title = time.strftime('강의_%Y%m%d_%H%M%S')
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
            self.screen.addItem(f'모니터 {i+1} ({screen.geometry().width()}×{screen.geometry().height()})')
        self.full = QPushButton('선택 모니터 전체')
        self.pick = QPushButton('영역 드래그 선택')
        self.full.clicked.connect(self.fullscreen)
        self.pick.clicked.connect(self.select_region)
        self.region_label = QLabel()
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
        rows = [(QLabel('강의 제목'), self.title, self.title_button),
                (self.title_mode, self.lecture_window, self.window_refresh),
                (self.ocr_pick, self.ocr_language, self.ocr_engine), (self.title_hint,), (QLabel('저장 경로'), self.folder, self.browse),
                (self.screen, self.full, self.pick), (self.region_label,),
                (self.system, self.mic, self.cursor),
                (QLabel('시스템 출력 장치'), self.output_device, self.refresh_devices_button), (self.audio_hint,), (QLabel('FPS'), self.fps, self.quality),
                (self.start_button, self.pause_button, self.stop_button), (self.clock, self.open_button, self.cleanup_button), (self.status,)]
        for r, widgets in enumerate(rows):
            for c, widget in enumerate(widgets):
                grid.addWidget(widget, r, c, 1, 3 if len(widgets)==1 else 1)
        self.controls = [self.title, self.folder, self.browse, self.screen, self.full, self.pick, self.system, self.mic, self.cursor, self.fps, self.quality, self.output_device, self.refresh_devices_button,
                         self.title_button, self.title_mode, self.lecture_window, self.window_refresh,
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

    def current_screen(self):
        return QApplication.screens()[self.screen.currentIndex()]
    def fullscreen(self):
        self.set_region(self.current_screen().geometry())
    def set_region(self, rect, screen=None):
        self.region = rect
        self.region_screen = screen or self.current_screen()
        self.region_label.setText(f'영역: x={rect.x()}, y={rect.y()}, {rect.width()}×{rect.height()} — 변경하려면 다시 선택')
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
        busy = self.job is not None or self.capture_pending or self.picker_pending
        for control in self.controls:
            control.setEnabled(self.state == 'idle' and not busy)
        self.start_button.setEnabled(self.state == 'idle' and not busy)
        self.pause_button.setEnabled(self.state in ('recording', 'paused') and not busy)
        self.pause_button.setText('재개' if self.state == 'paused' else '일시정지')
        self.stop_button.setEnabled(self.state in ('recording', 'paused') and not busy)
    def submit(self, fn, success, reset_start=False, on_error=None):
        if self.job is not None:
            return
        self.job = Job(fn)
        def done(result, error):
            job = self.job
            job.wait()
            self.job = None
            if error and on_error:
                on_error(error)
            elif error:
                self.border.hide()
                recovery = str(self.recorder.folder) if self.recorder else self.paths.temp
                if reset_start and (self.recorder is None or self.recorder.process is None):
                    self.state = 'idle'
                    self.recorder = None
                elif self.recorder and self.recorder.process is None:
                    self.state = 'paused'
                self.status.setText('오류 — 임시 파일 보존됨: ' + recovery)
                QMessageBox.critical(self, '오류 / 복구 경로', error[-4500:] + '\n\n임시 파일: ' + recovery)
            else:
                success(result)
            self.refresh()
        self.job.done.connect(done)
        self.job.start()
        self.refresh()
    def start(self):
        if self.state != 'idle' or self.job or self.capture_pending or self.picker_pending:
            return
        if not self.check_storage():
            return
        try:
            if self.region_screen not in QApplication.screens():
                raise DisplayError('녹화 모니터가 변경되었습니다. 다시 선택하세요.')
            physical = physical_region(self.region_screen,self.region)
        except DisplayError as exc:
            QMessageBox.warning(self,'화면 좌표 / DPI 확인',str(exc))
            return
        opts = Options(folder=Path(self.paths.recordings), title=self.title.text(),
            rect=physical, temp_folder=Path(self.paths.temp),
            converted_folder=Path(self.paths.converted), fps=int(self.fps.currentText()),
            crf=[18, 23, 28][self.quality.currentIndex()], cursor=self.cursor.isChecked(),
            system=self.system.isChecked(), mic=self.mic.isChecked(),
            system_device=self.output_device.currentData(), title_source=self.title_source)
        def work():
            self.recorder = Recorder(opts)
            self.recorder.start()
        self.status.setText('장치 준비 중… 선택한 출력 장치로 소리를 재생하세요. 첫 패킷 지연은 즉시 실패 처리하지 않습니다.')
        self.submit(work, self.started, reset_start=True)
    def started(self, _):
        self.state = 'recording'
        self.border.mark(self.region)
        self.status.setText('녹화 중 — ' + self.recorder.audio_status())
    def pause(self):
        if self.job or self.state not in ('recording', 'paused'):
            return
        if self.state == 'paused':
            self.submit(self.recorder.start, self.started)
        else:
            def finished(_):
                self.state = 'paused'
                self.border.hide()
                self.status.setText('일시정지 — 구간 파일 보존됨')
            self.submit(self.recorder.pause, finished)
    def stop(self):
        if self.job or self.state not in ('recording', 'paused'):
            return
        self.status.setText('MP4 저장 중… 창을 닫지 마세요.')
        def finished(path):
            self.last = path
            self.state = 'idle'
            self.border.hide()
            self.set_clock(self.recorder.final_duration if self.recorder.final_duration is not None else self.recorder.elapsed)
            self.status.setText('저장 완료: ' + str(path) + '\n복구용 임시 폴더는 확인 후 직접 삭제하세요.')
            warnings = list(dict.fromkeys(self.recorder.manifest['warnings']))
            log = self.recorder.diagnostics.path
            self.recorder = None
            if warnings:
                QMessageBox.warning(self, '저장 완료 / 오디오 확인 필요', '\n'.join(warnings)[-3000:] + f'\n로그: {log}\n영상은 저장되었습니다. 오디오를 직접 확인하세요.')
        self.submit(self.recorder.finish, finished)
    def set_clock(self, seconds):
        seconds=max(0,int(seconds))
        self.clock.setText(f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')

    def tick(self):
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
        if self.job or self.capture_pending or self.state == 'recording':
            QMessageBox.information(self,'작업 진행 중','녹화 중이면 종료 / MP4 저장을 완료하고, 인식·저장 작업 중이면 완료된 뒤 창을 닫으세요.')
            event.ignore()
            return
        if self.state == 'paused' and self.recorder is not None:
            answer=QMessageBox.question(self,'원본을 보존하고 종료',
                f'MP4 저장을 완료하지 않았습니다. 원본 세션을 보존하고 종료할까요?\n{self.recorder.folder}',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:
                event.ignore()
                return
            self.recorder.events.write('closed_without_final_mp4')
        if self.picker is not None: self.picker.close()
        self.border.close()
        event.accept()


def main():
    if os.name != 'nt':
        raise SystemExit('MyRecorder GUI는 Windows 11/10 전용입니다.')
    # Qt 6 selects per-monitor DPI awareness itself. Do not mix the legacy
    # SetProcessDPIAware call with Qt's SetProcessDpiAwarenessContext setup.
    app = QApplication(sys.argv)
    try:
        window = Window()
    except StorageError as exc:
        QMessageBox.critical(None, '설정 파일 오류', str(exc))
        raise SystemExit(1)
    window.show()
    sys.exit(app.exec())
