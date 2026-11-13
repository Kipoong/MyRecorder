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
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QMessageBox, QGridLayout, QDialog, QDialogButtonBox)
from .recorder import Options, Recorder
from .audio import Diagnostics, device_choices
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
    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.origin = None
        self.rect = QRect()
        self.setCursor(Qt.CrossCursor)
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rectified_screen(), QColor(0, 0, 0, 95))
        painter.setPen(QPen(QColor('#ff5050'), 2))
        painter.drawRect(self.rect)
        painter.setPen(Qt.white)
        painter.drawText(20, 35, '마우스로 영역을 드래그하세요. Esc: 취소 / 한 모니터 안에서 선택')
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
            self.selected.emit(self.rect.translated(self.geometry().topLeft()))
            self.close()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


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
        self.setWindowTitle('MyRecorder V0.3 — Windows 11')
        self.settings = store or SettingsStore()
        self.paths = self.settings.load()
        self.recorder = None
        self.state = 'idle'
        self.job = None
        self.last = None
        self.region = QApplication.primaryScreen().geometry()
        self.border = Border()
        self.picker = None
        root = QWidget()
        self.setCentralWidget(root)
        grid = QGridLayout(root)
        self.title = QLineEdit(time.strftime('강의_%Y%m%d_%H%M%S'))
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
        self.status = QLabel('대기 — Windows 실기 검증이 필요한 MVP입니다.')
        self.status.setWordWrap(True)
        rows = [(QLabel('강의 제목'), self.title), (QLabel('저장 경로'), self.folder, self.browse),
                (self.screen, self.full, self.pick), (self.region_label,),
                (self.system, self.mic, self.cursor),
                (QLabel('시스템 출력 장치'), self.output_device, self.refresh_devices_button), (self.audio_hint,), (QLabel('FPS'), self.fps, self.quality),
                (self.start_button, self.pause_button, self.stop_button), (self.clock, self.open_button), (self.status,)]
        for r, widgets in enumerate(rows):
            for c, widget in enumerate(widgets):
                grid.addWidget(widget, r, c, 1, 3 if len(widgets)==1 else 1)
        self.controls = [self.title, self.folder, self.browse, self.screen, self.full, self.pick, self.system, self.mic, self.cursor, self.fps, self.quality, self.output_device, self.refresh_devices_button]
        for key, fn in [('Ctrl+Shift+R', self.start), ('Ctrl+Shift+P', self.pause), ('Ctrl+Shift+S', self.stop)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(fn)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        self.fullscreen()
        self.refresh()
        self.resize(900, 480)
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

    def current_screen(self):
        return QApplication.screens()[self.screen.currentIndex()]
    def fullscreen(self):
        self.set_region(self.current_screen().geometry())
    def set_region(self, rect):
        self.region = rect
        self.region_label.setText(f'영역: x={rect.x()}, y={rect.y()}, {rect.width()}×{rect.height()} — 변경하려면 다시 선택')
    def select_region(self):
        self.picker = RegionPicker(self.current_screen())
        self.picker.selected.connect(self.set_region)
        self.picker.show()
    def check_storage(self):
        try:
            prepare_storage(self.paths, self.settings.root)
            self.status.setText('저장 폴더 준비 완료 — Windows 실기 검증이 필요한 MVP입니다.')
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
        busy = self.job is not None
        for control in self.controls:
            control.setEnabled(self.state == 'idle' and not busy)
        self.start_button.setEnabled(self.state == 'idle' and not busy)
        self.pause_button.setEnabled(self.state in ('recording', 'paused') and not busy)
        self.pause_button.setText('재개' if self.state == 'paused' else '일시정지')
        self.stop_button.setEnabled(self.state in ('recording', 'paused') and not busy)
    def submit(self, fn, success, reset_start=False):
        if self.job is not None:
            return
        self.job = Job(fn)
        def done(result, error):
            job = self.job
            job.wait()
            self.job = None
            if error:
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
        if self.state != 'idle' or self.job:
            return
        if not self.check_storage():
            return
        if any(abs(s.devicePixelRatio() - 1.0) > 0.01 for s in QApplication.screens()):
            QMessageBox.warning(self, '화면 배율 제한', 'MVP는 모든 모니터의 Windows 디스플레이 배율 100%가 필요합니다. 배율 변경 후 앱을 다시 실행하세요. 혼합 DPI 지원은 후속 단계입니다.')
            return
        r = self.region
        opts = Options(folder=Path(self.paths.recordings), title=self.title.text(),
            rect=(r.x(), r.y(), r.width(), r.height()), temp_folder=Path(self.paths.temp),
            converted_folder=Path(self.paths.converted), fps=int(self.fps.currentText()),
            crf=[18, 23, 28][self.quality.currentIndex()], cursor=self.cursor.isChecked(),
            system=self.system.isChecked(), mic=self.mic.isChecked(),
            system_device=self.output_device.currentData())
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
            self.status.setText('저장 완료: ' + str(path) + '\n복구용 임시 폴더는 확인 후 직접 삭제하세요.')
            warnings = list(dict.fromkeys(self.recorder.manifest['warnings']))
            log = self.recorder.diagnostics.path
            self.recorder = None
            if warnings:
                QMessageBox.warning(self, '저장 완료 / 오디오 확인 필요', '\n'.join(warnings)[-3000:] + f'\n로그: {log}\n영상은 저장되었습니다. 오디오를 직접 확인하세요.')
        self.submit(self.recorder.finish, finished)
    def tick(self):
        if not self.recorder:
            return
        seconds = self.recorder.elapsed
        if self.recorder.process:
            seconds += time.monotonic() - self.recorder.started
        seconds = int(seconds)
        self.clock.setText(f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')
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
        if self.job or self.state != 'idle':
            QMessageBox.information(self, '녹화 종료 필요', '종료 / MP4 저장을 완료한 뒤 창을 닫으세요. 저장 실패 시 임시 폴더를 보존하고 작업 관리자에서 종료할 수 있습니다.')
            event.ignore()
        else:
            self.border.close()
            event.accept()


def main():
    if os.name != 'nt':
        raise SystemExit('MyRecorder GUI는 Windows 11/10 전용입니다.')
    # gdigrab uses physical pixels; disable Qt automatic scaling for matching geometry.
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
    os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
    app = QApplication(sys.argv)
    try:
        window = Window()
    except StorageError as exc:
        QMessageBox.critical(None, '설정 파일 오류', str(exc))
        raise SystemExit(1)
    window.show()
    sys.exit(app.exec())
