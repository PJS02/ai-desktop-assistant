"""One settings entry point; remote controls use acknowledged process messages."""
from copy import deepcopy

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .personality_system import PersonalitySystem
from .tts_service import available_voices
from .motion_options import CHARACTER_OPTION_RANGES, normalize_character_options


class SettingsDialog(QDialog):
    apply_requested = pyqtSignal(dict)
    refresh_requested = pyqtSignal(bool)

    def __init__(self, local, parent=None):
        super().__init__(parent)
        local = deepcopy(local)
        local['character'].update(normalize_character_options(local['character']))
        self.setWindowTitle('통합 설정')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.resize(700, 640)
        self.setMinimumSize(520, 430)
        self.local_baseline = deepcopy(local)
        self.remote_baseline = None
        self.pending = False
        self.close_on_success = False
        self.tabs = QTabWidget()
        self.controls = {}
        root = QVBoxLayout(self)
        title = QLabel('통합 설정')
        title.setStyleSheet('font-size: 22px; font-weight: 600;')
        root.addWidget(title)
        root.addWidget(QLabel('캐릭터와 인식 기능의 설정을 한곳에서 관리하세요.'))
        root.addWidget(self.tabs, 1)
        self._character_page(local)
        self._voice_page(local)
        self._recognition_page()
        self._ai_page(local)
        self.status = QLabel('설정을 변경한 뒤 적용을 누르세요.')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton('닫기')
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = QPushButton('적용')
        self.apply_button.clicked.connect(lambda: self.submit(False))
        self.ok_button = QPushButton('저장 후 닫기')
        self.ok_button.clicked.connect(lambda: self.submit(True))
        self.ok_button.setDefault(True)
        for button in (self.cancel_button, self.apply_button, self.ok_button):
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.setStyleSheet('''
            QDialog { background: #f6f8fb; color: #202936; }
            QTabWidget::pane { border: 1px solid #dce2ea; background: white; }
            QTabBar::tab { padding: 10px 18px; background: #eef2f7; color: #607085; border: 0; border-bottom: 2px solid transparent; margin-right: 2px; }
            QTabBar::tab:selected { color: #2463b6; background: white; border-bottom: 2px solid #2463b6; }
            QScrollArea { border: none; background: white; }
            QScrollArea > QWidget > QWidget { background: white; }
            QLineEdit, QComboBox, QSpinBox { min-height: 28px; padding: 3px; border: 1px solid #dce2ea; border-radius: 5px; background: white; }
            QPushButton { padding: 8px 15px; }
            QLabel { color: #202936; }
            QScrollBar:vertical { width: 8px; background: #f6f8fb; }
            QScrollBar::handle:vertical { background: #cbd5e1; min-height: 40px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        ''')
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._timed_out)

    def _page(self, name, description):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 22)
        hint = QLabel(description)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, name)
        return content, layout, form

    @staticmethod
    def _combo(choices, current):
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _character_page(self, local):
        _, _, form = self._page('캐릭터', '크기와 이동 속도는 바로 적용되고, 점프 높이는 다음 점프부터 반영됩니다. 활동 범위와 점프는 화면 안으로 제한됩니다.')
        self.character_sliders = {}
        self.character_inputs = {}
        for key, label, suffix in (
            ('size_percent', '캐릭터 크기', ' %'),
            ('movement_speed', '이동 속도', ' px/초'),
            ('jump_height', '점프 높이', ' px'),
        ):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            spin = QSpinBox()
            low, high = CHARACTER_OPTION_RANGES[key]
            slider.setRange(low, high)
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            spin.setMinimumWidth(120)
            slider.setValue(local['character'][key])
            spin.setValue(local['character'][key])
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            self.character_sliders[key] = slider
            self.character_inputs[key] = spin
            line.addWidget(slider, 1)
            line.addWidget(spin)
            form.addRow(label, row)
        self.size_preview = QLabel()
        form.addRow('', self.size_preview)
        self.character_inputs['size_percent'].valueChanged.connect(self._describe_size)
        self._describe_size()
        self.show_hitboxes = QCheckBox('히트박스·인식한 창 표시')
        self.show_hitboxes.setChecked(local['character']['show_hitboxes'])
        form.addRow(self.show_hitboxes)
        overlay_hint = QLabel('캐릭터의 표시 영역, 겹치는 창 영역과 인식한 창 이름을 표시합니다.')
        overlay_hint.setWordWrap(True)
        form.addRow('', overlay_hint)
        self.resolution_preset = self._combo([
            ('사용자 정의', None), ('720p · 1280 × 720', (1280, 720)),
            ('1080p · 1920 × 1080', (1920, 1080)), ('1440p · 2560 × 1440', (2560, 1440)),
        ], None)
        form.addRow('활동 범위', self.resolution_preset)
        self.width = QSpinBox()
        self.width.setRange(640, 7680)
        self.width.setSuffix(' px')
        self.width.setValue(local['character']['width'])
        self.height = QSpinBox()
        self.height.setRange(480, 4320)
        self.height.setSuffix(' px')
        self.height.setValue(local['character']['height'])
        form.addRow('너비', self.width)
        form.addRow('높이', self.height)
        self.resolution_preset.currentIndexChanged.connect(self._set_resolution_preset)
        self.width.valueChanged.connect(self._match_resolution_preset)
        self.height.valueChanged.connect(self._match_resolution_preset)
        self._match_resolution_preset()
        self.personality = self._combo([(name, name) for name in PersonalitySystem.PERSONALITY_PRESETS], local['character']['personality'])
        form.addRow('성격', self.personality)
        self.personality_description = QLabel()
        self.personality_description.setWordWrap(True)
        form.addRow('', self.personality_description)
        self.personality.currentIndexChanged.connect(self._describe_personality)
        self._describe_personality()

    def _describe_size(self):
        percent = self.character_inputs['size_percent'].value()
        self.size_preview.setText(f"크기 배율: {percent}% · 가로세로 비율 유지")

    def _set_resolution_preset(self):
        value = self.resolution_preset.currentData()
        if value:
            self.width.blockSignals(True)
            self.height.blockSignals(True)
            self.width.setValue(value[0])
            self.height.setValue(value[1])
            self.width.blockSignals(False)
            self.height.blockSignals(False)

    def _match_resolution_preset(self):
        self.resolution_preset.blockSignals(True)
        value = (self.width.value(), self.height.value())
        index = next((i for i in range(1, self.resolution_preset.count())
                      if tuple(self.resolution_preset.itemData(i)) == value), 0)
        self.resolution_preset.setCurrentIndex(index)
        self.resolution_preset.blockSignals(False)

    def _describe_personality(self):
        preset = PersonalitySystem.PERSONALITY_PRESETS[self.personality.currentData()]
        self.personality_description.setText(preset['description'])

    def _voice_page(self, local):
        _, _, form = self._page('음성', 'AI 답변을 읽는 목소리를 선택하세요. 적용 즉시 바뀌며 다음 실행에도 유지됩니다.')
        self.tts_enabled = QCheckBox('AI 답변 음성으로 읽기')
        self.tts_enabled.setChecked(local['voice']['enabled'])
        self.voice = self._combo([(voice.name, voice.id) for voice in available_voices()], local['voice']['voice_id'])
        self.voice.setEnabled(self.tts_enabled.isChecked())
        self.tts_enabled.toggled.connect(self.voice.setEnabled)
        form.addRow(self.tts_enabled)
        form.addRow('목소리', self.voice)

    def _recognition_page(self):
        _, layout, self.remote_form = self._page('사용자 인식', '카메라·감정 인식은 실행 중에 적용됩니다. 마이크·STT 옵션을 바꾸면 실행 중인 음성 인식을 자동으로 다시 시작합니다.')
        self.remote_status = QLabel('인식 기능에 연결하는 중…')
        self.remote_status.setWordWrap(True)
        layout.insertWidget(1, self.remote_status)
        self.refresh_button = QPushButton('장치 새로고침')
        self.refresh_button.clicked.connect(lambda: self.refresh_requested.emit(True))
        layout.insertWidget(2, self.refresh_button)
        self.remote_fields = QWidget()
        self.fields_form = QFormLayout(self.remote_fields)
        self.fields_form.setContentsMargins(0, 0, 0, 0)
        self.fields_form.setVerticalSpacing(10)
        self.fields_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.remote_form.addRow(self.remote_fields)
        self.remote_fields.setEnabled(False)

    def set_remote(self, state, preserve_draft=False):
        draft = self.changes()['remote'] if preserve_draft else {}
        self.remote_baseline = deepcopy(state['values'])
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self.controls = {}
        choices = state['choices']
        labels = {'camera': '카메라', 'microphone': '마이크', 'mode': '인식 모드',
                  'emotion_model': '감정 인식 모델', 'provider': 'STT 서비스',
                  'language': '인식 언어', 'silence': '발화 종료 대기', 'sensitivity': '마이크 민감도'}
        for key, label in labels.items():
            combo = self._combo([(item['label'], item['value']) for item in choices[key]], state['values'].get(key))
            if not combo.count():
                combo.addItem('사용 가능한 장치 없음', None)
                combo.setEnabled(False)
            self.controls[key] = combo
            self.fields_form.addRow(label, combo)
        toggles = {'emotion': '감정 인식', 'always_recognition': '상시 동작 인식',
                   'tracking': '트래킹 표시', 'marker_only': '검은 화면에 마커만 표시',
                   'mirror': '좌우 반전', 'info_overlay': '화면 정보 표시', 'timestamps': 'STT 시간 표시'}
        for key, label in toggles.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(state['values'][key])
            self.controls[key] = checkbox
            self.fields_form.addRow(checkbox)
        if state.get('game_active'):
            self.controls['mode'].setEnabled(False)
        for key, value in draft.items():
            control = self.controls[key]
            if isinstance(control, QCheckBox):
                control.setChecked(value)
            else:
                index = control.findData(value)
                if index >= 0:
                    control.setCurrentIndex(index)
        self.remote_fields.setEnabled(True)
        self.remote_status.setText(state.get('status', '현재 설정을 불러왔습니다.'))

    def remote_unavailable(self, message):
        self.remote_status.setText(message)
        self.remote_fields.setEnabled(False)
        self.remote_baseline = None

    def _ai_page(self, local):
        _, _, form = self._page('AI', 'Gemini API 키와 모델을 설정하세요. 저장하면 이후 대화와 자동 대사 요청부터 적용됩니다.')
        self.api_key = QLineEdit(local['ai']['api_key'])
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText('API 키 입력')
        self.api_key.setClearButtonEnabled(True)
        form.addRow('API 키', self.api_key)
        reveal = QCheckBox('API 키 표시')
        reveal.toggled.connect(lambda checked: self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        form.addRow(reveal)
        self.model = QLineEdit(local['ai']['model'])
        self.model.setPlaceholderText('사용할 모델 ID 입력')
        form.addRow('모델 ID', self.model)

    def changes(self):
        local = {'character': {'width': self.width.value(), 'height': self.height.value(), 'personality': self.personality.currentData()},
                 'voice': {'enabled': self.tts_enabled.isChecked(), 'voice_id': self.voice.currentData()},
                 'ai': {'api_key': self.api_key.text().strip(), 'model': self.model.text().strip()}}
        local['character'].update({key: control.value() for key, control in self.character_inputs.items()})
        local['character']['show_hitboxes'] = self.show_hitboxes.isChecked()
        changed = {key: value for key, value in local.items() if value != self.local_baseline[key]}
        remote = {}
        if self.remote_baseline is not None:
            for key, control in self.controls.items():
                value = control.isChecked() if isinstance(control, QCheckBox) else control.currentData()
                if value != self.remote_baseline.get(key):
                    remote[key] = value
        return {'local': changed, 'remote': remote}

    def submit(self, close):
        if self.pending:
            return
        changes = self.changes()
        if 'ai' in changes['local'] and changes['local']['ai']['api_key'] and not changes['local']['ai']['model']:
            self.status.setText('API 키를 사용하려면 모델 ID를 입력하세요.')
            self.tabs.setCurrentIndex(3)
            return
        self.close_on_success = close
        if not changes['local'] and not changes['remote']:
            self.status.setText('변경된 설정이 없습니다.')
            if close:
                self.accept()
            return
        self.set_pending(True)
        self.apply_requested.emit(changes)

    def set_pending(self, pending):
        self.pending = pending
        self.tabs.setEnabled(not pending)
        for button in (self.apply_button, self.ok_button, self.cancel_button):
            button.setEnabled(not pending)
        if pending:
            self.status.setText('설정을 저장하고 적용하는 중…')
            self.timeout.start(45000)
        else:
            self.timeout.stop()

    def complete(self, message, success=True, local=None, remote=None):
        if local:
            self.local_baseline.update(deepcopy(local))
        if remote:
            self.set_remote(remote, preserve_draft=not success)
        self.set_pending(False)
        self.status.setText(message)
        if success and self.close_on_success:
            self.accept()

    def _timed_out(self):
        self.close_on_success = False
        self.complete('인식 기능의 응답이 지연되고 있습니다. 실제 적용 여부를 확인하려면 설정을 다시 열어 주세요.', False)

    def reject(self):
        if not self.pending:
            super().reject()

    def closeEvent(self, event):
        if self.pending:
            event.ignore()
        else:
            super().closeEvent(event)
