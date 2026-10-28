"""Small, shared readiness display driven by actual initialization events."""
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from app_logging import subscribe


LABELS = {
    'character': '캐릭터 화면', 'tracker': '얼굴·자세 인식', 'emotion': '감정 인식',
    'camera': '카메라', 'microphone': '음성 입력', 'voice': '음성 출력', 'hands': '손 추적',
}
STATE_TEXT = {'waiting': '대기', 'loading': '준비 중', 'ready': '완료',
              'idle': '사용 시 준비', 'off': '꺼짐', 'error': '확인 필요'}
COLORS = {'loading': '#2463b6', 'error': '#b42318'}

# Existing events remain the source of truth; no polling or model imports here.
EVENTS = {
    'renderer.worker.started': ('character', 'loading', '그림과 동작을 불러오는 중'),
    'renderer.worker.ready': ('character', 'loading', '그림·동작 준비 완료 · 화면을 초기화하는 중'),
    'renderer.opengl.ready': ('character', 'ready', '화면 표시 준비 완료'),
    'renderer.sprite.ready': ('character', 'ready', '그림 표시 준비 완료'),
    'renderer.initialization_failed': ('character', 'loading', '대체 화면을 준비하는 중'),
    'renderer.opengl.failed': ('character', 'loading', '대체 화면을 준비하는 중'),
    'recognition.tracker.loading': ('tracker', 'loading', 'MediaPipe 모델을 불러오는 중'),
    'recognition.tracker.configured': ('tracker', 'ready', 'MediaPipe 준비 완료'),
    'recognition.model.loading': ('emotion', 'loading', '감정 모델을 불러오는 중'),
    'recognition.model.ready': ('emotion', 'ready', '감정 모델 준비 완료'),
    'recognition.model.failed': ('emotion', 'error', '감정 모델을 불러오지 못했어요'),
    'device.camera.discovery.started': ('camera', 'loading', '사용할 카메라를 찾는 중'),
    'device.camera.discovery.empty': ('camera', 'error', '연결된 카메라가 없어요'),
    'device.camera.discovery.failed': ('camera', 'error', '카메라를 찾지 못했어요'),
    'device.camera.starting': ('camera', 'loading', '카메라와 첫 화면을 준비하는 중'),
    'device.camera.started': ('camera', 'ready', '카메라 연결 완료'),
    'device.camera.failed': ('camera', 'error', '카메라를 열지 못했어요'),
    'device.camera.frame_failed': ('camera', 'error', '카메라 연결을 확인해 주세요'),
    'device.camera.released': ('camera', 'off', '카메라 중지'),
    'device.microphone.discovery.started': ('microphone', 'loading', '사용할 마이크를 찾는 중'),
    'device.microphone.discovery.empty': ('microphone', 'error', '연결된 마이크가 없어요'),
    'device.microphone.discovery.failed': ('microphone', 'error', '마이크를 찾지 못했어요'),
    'stt.start.requested': ('microphone', 'loading', '마이크를 연결하는 중'),
    'stt.microphone.opened': ('microphone', 'ready', '마이크 입력 준비 완료'),
    'stt.start.failed': ('microphone', 'error', '음성 입력을 시작하지 못했어요'),
    'stt.worker.failed': ('microphone', 'error', '마이크 연결을 확인해 주세요'),
    'stt.stop.requested': ('microphone', 'off', '음성 입력 중지'),
    'hand_overlay.model.loading': ('hands', 'loading', '손 추적 모델을 불러오는 중'),
    'hand_overlay.model.ready': ('hands', 'ready', '손 추적 모델 준비 완료'),
    'hand_overlay.tracking.failed': ('hands', 'error', '손 추적을 시작하지 못했어요'),
    'tts.model_loading': ('voice', 'loading', '음성 모델을 불러오는 중'),
    'tts.model_ready': ('voice', 'ready', '음성 모델 준비 완료'),
    'tts.model_failed': ('voice', 'error', '음성 모델을 준비하지 못했어요'),
    'tts.model_unloaded': ('voice', 'idle', '다음 발화 때 모델을 준비해요'),
}


class PreparationStatus(QObject):
    changed = pyqtSignal()
    _event_received = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.states = {key: ('waiting', '앞 단계가 끝나면 준비해요') for key in LABELS}
        self.states['character'] = ('loading', '그림과 동작을 불러오는 중')
        self.states['voice'] = ('idle', '첫 발화 때 모델을 준비해요')
        self.states['hands'] = ('off', '손 표시를 켜면 준비해요')
        self.stage_progress = {key: None for key in LABELS}
        self.voice_enabled = True
        self.voice_model = 'supertonic-3'
        self.ready_voice_models = set()
        self.hands_enabled = False
        self._event_received.connect(self.accept)
        self._unsubscribe = subscribe(self._receive)

    def close(self):
        self._unsubscribe()

    def _receive(self, event):
        if event.event in EVENTS or event.event in (
                'tts.configuration', 'tts.model_progress', 'tts.synthesis_failed', 'hand_overlay.settings.applied',
                'recognition.process_started', 'recognition.process_exited',
                'recognition.process_start_failed', 'recognition.process.failed',
                'recognition.recovery.exhausted'):
            self._event_received.emit(event)

    def set_state(self, key, state, detail, *, progress=None):
        value = (state, detail)
        if state == 'ready':
            progress = (1, 1)
        elif state == 'error':
            previous = self.stage_progress[key]
            progress = previous if previous is not None and previous[0] < previous[1] else None
        if self.states[key] != value or self.stage_progress[key] != progress:
            self.states[key] = value
            self.stage_progress[key] = progress
            self.changed.emit()

    def configure_hands(self, enabled):
        self.hands_enabled = bool(enabled)
        self.set_state('hands', 'waiting' if enabled else 'off',
                       '카메라가 연결되면 준비해요' if enabled else '손 표시를 켜면 준비해요')

    def accept(self, event):
        name, data = event.event, event.data
        if name == 'tts.configuration':
            self.voice_enabled = data['enabled']
            voice = data['voice_id']
            self.voice_model = voice if voice in ('gpt_sovits', 'openvoice_v2') else 'supertonic-3'
            state = ('ready' if self.voice_model in self.ready_voice_models else 'idle') if self.voice_enabled else 'off'
            self.set_state('voice', state, '음성 출력 꺼짐' if not self.voice_enabled else
                           '음성 모델 준비 완료' if state == 'ready' else '첫 발화 때 모델을 준비해요')
        elif name == 'hand_overlay.settings.applied':
            enabled = data['options']['enabled']
            if enabled != self.hands_enabled:
                self.configure_hands(enabled)
        elif name == 'recognition.process_started':
            for key in ('tracker', 'emotion', 'camera', 'microphone'):
                self.set_state(key, 'waiting', '인식 작업을 시작하는 중')
            self.configure_hands(self.hands_enabled)
        elif name in ('recognition.process_start_failed', 'recognition.process.failed',
                      'recognition.recovery.exhausted', 'recognition.process_exited'):
            if not data.get('shutdown_requested'):
                for key in ('tracker', 'emotion', 'camera', 'microphone'):
                    self.set_state(key, 'error', '인식 작업에 연결할 수 없어요')
                if self.hands_enabled:
                    self.set_state('hands', 'error', '인식 작업에 연결할 수 없어요')
        elif name == 'tts.model_progress':
            done, total = data.get('completed'), data.get('total')
            if (self.voice_enabled and data.get('model') == self.voice_model
                    and type(done) is int and type(total) is int and 0 <= done < total):
                self.set_state('voice', 'loading', str(data.get('detail', '음성 모델을 준비하는 중'))[:160],
                               progress=(done, total))
        elif name == 'tts.synthesis_failed':
            if self.states['voice'][0] == 'loading':
                self.set_state('voice', 'error', '음성 모델을 준비하지 못했어요')
        elif name in EVENTS:
            key, state, detail = EVENTS[name]
            if key == 'voice':
                model = data.get('model')
                if state == 'ready':
                    self.ready_voice_models.add(model)
                elif state in ('idle', 'loading', 'error'):
                    self.ready_voice_models.discard(model)
                if not self.voice_enabled or model != self.voice_model:
                    return
            if key == 'hands' and not self.hands_enabled:
                return
            # Reopening a camera first releases the old stream.
            if name == 'device.camera.released' and self.states['camera'][0] == 'loading':
                return
            self.set_state(key, state, detail,
                           progress=(1, 2) if name == 'renderer.worker.ready' else None)
            if key == 'camera' and self.hands_enabled and state in ('off', 'error'):
                self.set_state('hands', state, '카메라가 연결되면 손 추적을 준비해요')

    @property
    def settled(self):
        return all(state in ('ready', 'idle', 'off') for state, _ in self.states.values())

class PreparationView(QWidget):
    """The popup and settings render the same state, with their own row subset."""
    def __init__(self, status, keys=None, parent=None, *, compact=False):
        super().__init__(parent)
        self.status = status
        self.compact = compact
        self.keys = tuple(keys or LABELS)
        self.rows = {}
        self.bars = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8 if compact else 12)
        self.setStyleSheet('''
            QLabel { color: #202936; font-size: 14px; background: transparent; }
            QLabel#detail { color: #5f6368; font-size: 12px; }
            QProgressBar { background: #eef2f7; border: none; border-radius: 4px; }
            QProgressBar::chunk { background: #2463b6; border-radius: 4px; }
        ''')
        for key in self.keys:
            row = QVBoxLayout()
            row.setSpacing(3)
            heading = QHBoxLayout()
            label, value = QLabel(LABELS[key]), QLabel()
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            heading.addWidget(label)
            heading.addWidget(value)
            detail = QLabel()
            detail.setObjectName('detail')
            detail.setWordWrap(True)
            for widget in (label, value, detail):
                widget.setTextFormat(Qt.TextFormat.PlainText)
            row.addLayout(heading)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setAccessibleName(f'{LABELS[key]} 준비 진행률')
            row.addWidget(bar)
            row.addWidget(detail)
            layout.addLayout(row)
            self.rows[key] = (value, detail)
            self.bars[key] = bar
        status.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        for key, (value, detail) in self.rows.items():
            state, text = self.status.states[key]
            bar = self.bars[key]
            progress = self.status.stage_progress[key]
            caption = STATE_TEXT[state]
            if progress is not None:
                done, total = progress
                caption = f'{done * 100 // total}% · {caption}'
                bar.setRange(0, total)
                bar.setValue(done)
                bar.setToolTip(f'준비 단계 {done}/{total} 완료. 남은 시간 비율이 아닙니다.' if state != 'ready' else '준비 완료')
            else:
                bar.setRange(0, 0 if state == 'loading' else 100)
                bar.setValue(0)
                if state == 'waiting':
                    caption = '0% · 대기'
                bar.setToolTip('내부 진행률을 제공하지 않는 작업입니다.' if state == 'loading' else caption)
            bar.setVisible(state not in ('off', 'idle'))
            bar.setAccessibleDescription(f'{caption}. {text}')
            value.setText(caption)
            value.setStyleSheet(f'color: {COLORS.get(state, "#5f6368")}; font-size: 12px;')
            detail.setText(text)
            detail.setVisible(not self.compact or state in ('loading', 'error'))
            value.setAccessibleName(f'{LABELS[key]} {caption}')


class PreparationPanel(QFrame):
    settings_requested = pyqtSignal()

    def __init__(self, status):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.status = status
        self.dismissed = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('프로그램 준비 상태')
        self.setObjectName('preparationPanel')
        self.setFixedWidth(344)
        self.setStyleSheet('''
            QFrame#preparationPanel { background: white; border: 1px solid #e5e7eb; border-radius: 8px; }
            QLabel { color: #202936; background: transparent; }
            QPushButton { background: #f1f3f5; color: #202936; border: none; border-radius: 4px;
                          padding: 7px 12px; font-size: 12px; }
            QPushButton:hover { background: #e5e7eb; }
            QPushButton:focus { border: 2px solid #2463b6; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(16)
        self.title = QLabel('프로그램 준비 중')
        self.title.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(self.title)
        layout.addWidget(PreparationView(status))
        footer = QHBoxLayout()
        self.settings_button = QPushButton('설정 열기')
        self.settings_button.setEnabled(False)
        self.settings_button.clicked.connect(self.settings_requested)
        footer.addWidget(self.settings_button)
        footer.addStretch()
        hide_button = QPushButton('숨기기')
        hide_button.clicked.connect(self.dismiss)
        footer.addWidget(hide_button)
        layout.addLayout(footer)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(3000)
        self.hide_timer.timeout.connect(self.hide)
        status.changed.connect(self.refresh)
        self.adjustSize()
        self.reposition()
        app = QApplication.instance()
        app.primaryScreenChanged.connect(self.reposition)
        if app.primaryScreen() is not None:
            app.primaryScreen().availableGeometryChanged.connect(self.reposition)

    def bind_character(self, character):
        self.settings_button.setEnabled(True)
        self.reposition()

    def dismiss(self):
        self.dismissed = True
        self.hide_timer.stop()
        self.hide()

    def refresh(self):
        states = [state for state, _ in self.status.states.values()]
        error = 'error' in states
        self.title.setText('준비 상태 확인' if error else
                           '준비 완료' if self.status.settled else '프로그램 준비 중')
        if error or not self.status.settled:
            self.hide_timer.stop()
            if not self.dismissed:
                if not self.isVisible():
                    self.reposition()
                self.show()
        elif not self.hide_timer.isActive() and self.isVisible():
            self.hide_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reposition()

    def reposition(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x, y = area.right() - self.width() - 20, area.bottom() - self.height() - 20
        self.move(max(area.left() + 12, min(x, area.right() - self.width() - 12)),
                  max(area.top() + 12, min(y, area.bottom() - self.height() - 12)))
