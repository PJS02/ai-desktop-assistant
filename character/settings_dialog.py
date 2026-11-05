"""One settings entry point; remote controls use acknowledged process messages."""
from copy import deepcopy
import base64
import binascii
from app_logging import log_event

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .personality_system import PersonalitySystem
from .tts_service import available_voices
from .tts_models import ENGINE_NAMES, download_manager
from .tts_backend import runtime_python
from .motion_options import CHARACTER_OPTION_RANGES, normalize_character_options, random_movement_scale
from .manual_control import COMMAND_ROWS, DISPLAY_EMOTIONS, DISPLAY_EMOTION_NAMES
from .dialogue_styles import DIALOGUE_STYLES, normalize_dialogue_style
from .dialogue_widget import DialogueBubble
from .hand_overlay_options import HAND_OVERLAY_OPTION_RANGES, normalize_hand_overlay_options
from .game_rules import DEFAULT_GAME_RULES, normalize_game_rules, running_process_names


class _SettingsComboBox(QComboBox):
    def wheelEvent(self, event):
        # Let the settings page scroll without changing the selected option.
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return
            parent = parent.parentWidget()
        event.ignore()


class _PreviewImage(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._image = QImage()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet('background: #15202c; color: #dce5f0; border-radius: 6px;')

    def set_image(self, image):
        self._image = image
        self._render_image()

    def set_message(self, text):
        self._image = QImage()
        self.clear()
        self.setText(text)

    def _render_image(self):
        if not self._image.isNull():
            self.setPixmap(QPixmap.fromImage(self._image).scaled(
                max(1, self.width()), max(1, self.height()),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_image()


class SettingsDialog(QDialog):
    apply_requested = pyqtSignal(dict)
    apply_timeout = pyqtSignal(str)
    refresh_requested = pyqtSignal(bool)
    character_command_requested = pyqtSignal(str)
    dialogue_generation_requested = pyqtSignal()
    manual_dialogue_requested = pyqtSignal(str, str)
    manual_speech_requested = pyqtSignal(str, str)
    manual_dialogue_hide_requested = pyqtSignal()
    display_emotion_requested = pyqtSignal(str)
    preview_requested = pyqtSignal(bool)
    device_requested = pyqtSignal(str)

    def __init__(self, local, parent=None, model_manager=None):
        super().__init__(parent)
        local = deepcopy(local)
        local['character'].update(normalize_character_options(local['character']))
        local['voice'].setdefault('sync_bubble', False)
        local['game_rules'] = normalize_game_rules(local.get('game_rules'))
        self.setWindowTitle('설정')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.resize(700, 640)
        self.setMinimumSize(520, 430)
        self.local_baseline = deepcopy(local)
        self.remote_baseline = None
        self.pending = False
        self.log_trace_id = None
        self.close_on_success = False
        self.tabs = QTabWidget()
        self.controls = {}
        self.model_manager = model_manager if model_manager is not None else download_manager()
        root = QVBoxLayout(self)
        title = QLabel('설정')
        title.setStyleSheet('font-size: 22px; font-weight: 600;')
        root.addWidget(title)
        root.addWidget(self.tabs, 1)
        self._character_page(local)
        self.local_baseline['character']['personality'] = self.personality.currentData()
        self.local_baseline['character']['personality_traits'] = {
            key: control.value() / 100.0 for key, control in self.personality_trait_inputs.items()
        }
        self._voice_page(local)
        self._recognition_page(local)
        self._ai_page(local)
        self._manual_page()
        self._game_rules_page(local)
        self._preview_active = False
        self.tabs.currentChanged.connect(self._sync_preview)
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
            QLineEdit, QComboBox { min-height: 28px; padding: 3px; border: 1px solid #dce2ea; border-radius: 5px; background: #ffffff; color: #202936; }
            QComboBox QAbstractItemView { background: #ffffff; color: #202936; selection-background-color: #2463b6; selection-color: #ffffff; border: 1px solid #cbd5e1; outline: 0; }
            QComboBox QAbstractItemView::item { min-height: 26px; padding: 4px 8px; }
            QSpinBox { min-height: 28px; padding: 0 21px 0 6px; border: 1px solid #dce2ea; border-radius: 5px; background: #ffffff; color: #202936; selection-background-color: #2463b6; selection-color: #ffffff; }
            QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 16px; border-left: 1px solid #dce2ea; background: #f6f8fb; }
            QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 4px; }
            QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 4px; }
            QCheckBox { color: #202936; background: transparent; spacing: 8px; }
            QCheckBox:disabled { color: #68778b; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #607085; border-radius: 3px; background: #ffffff; }
            QCheckBox::indicator:checked { background: #2463b6; border: 3px solid #b7cfee; }
            QCheckBox::indicator:disabled { background: #e3e8f0; border-color: #9aa7b8; }
            QPlainTextEdit { background: #ffffff; color: #202936; border: 1px solid #dce2ea; selection-background-color: #2463b6; selection-color: #ffffff; }
            QPushButton { padding: 8px 15px; background: #ffffff; color: #202936; border: 1px solid #cbd5e1; border-radius: 5px; }
            QPushButton:hover { background: #eef4fd; border-color: #2463b6; }
            QPushButton:pressed, QPushButton:checked { background: #e8f1fd; color: #174b91; border-color: #2463b6; }
            QPushButton:disabled { background: #edf0f5; color: #68778b; border-color: #dce2ea; }
            QPushButton#emotionButton { background: white; color: #202936; border: 1px solid #dce2ea; border-radius: 5px; }
            QPushButton#emotionButton:checked { background: #e8f1fd; color: #2463b6; border: 2px solid #2463b6; font-weight: 600; }
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
        combo = _SettingsComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _character_page(self, local):
        _, _, form = self._page('캐릭터', '크기·이동 속도·달리기 속도는 바로 적용되고, 이동 폭은 다음 랜덤 이동부터, 점프 높이는 다음 점프부터 반영됩니다. 활동 범위와 점프는 화면 안으로 제한됩니다.')
        self.character_sliders = {}
        self.character_inputs = {}
        for key, label, suffix in (
            ('boredom_minutes', '지루함 최댓값 도달 시간', '분'),
            ('size_percent', '캐릭터 크기', ' %'),
            ('movement_speed', '이동 속도', ' px/초'),
            ('running_speed', '달리기 속도', ' px/초'),
            ('movement_range_extra_percent', '추가 이동 폭 비율', ' %'),
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
            if key == 'boredom_minutes':
                slider.setToolTip('0분이면 지루함이 쌓이지 않습니다.')
                spin.setToolTip('0분이면 지루함이 쌓이지 않습니다.')
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
        self.movement_range_preview = QLabel()
        self.movement_range_preview.setWordWrap(True)
        form.addRow('', self.movement_range_preview)
        range_hint = QLabel('감정별 기본 이동 폭에 (캐릭터 크기 비율 + 추가 비율)을 적용합니다.\n'
                           '추가 0%는 크기만 반영하고, 음수는 줄이고 양수는 늘립니다.')
        range_hint.setWordWrap(True)
        form.addRow('', range_hint)
        for key in ('size_percent', 'movement_range_extra_percent'):
            self.character_inputs[key].valueChanged.connect(self._describe_movement_range)
        self._describe_movement_range()
        self.show_hitboxes = QCheckBox('충돌 박스 표시 (개발자용)')
        self.show_hitboxes.setToolTip('충돌 박스, 좌표, 활성 창 정보를 함께 켜거나 끕니다. 적용 버튼을 누르면 저장됩니다.')
        self.show_hitboxes.setChecked(local['character']['show_hitboxes'])
        form.addRow(self.show_hitboxes)
        overlay_hint = QLabel('켜면 충돌 박스, 좌표, 활성 창 정보를 표시합니다.\n'
                             '끄면 개발자 표시만 숨기며, 충돌 판정은 유지됩니다. 적용 버튼을 눌러 저장하세요.')
        overlay_hint.setWordWrap(True)
        form.addRow('', overlay_hint)
        self.window_occlusion = QCheckBox('다른 창 뒤에 숨기 · 오래 가려지면 찢고 나오기')
        self.window_occlusion.setChecked(local['character'].get('window_occlusion', True))
        self.window_occlusion.setToolTip('앞쪽 창에 가려진 채 8초가 지나면 종이를 찢는 효과로 나온 뒤 창이나 작업 표시줄 위를 걷습니다.')
        form.addRow(self.window_occlusion)
        self.game_spectator_enabled = QCheckBox('게임 활동에 반응하기 (관람·응원)')
        self.game_spectator_enabled.setChecked(local['character'].get('game_spectator', True))
        self.game_spectator_enabled.setToolTip('기존 STEAM/GAME/UNITY 분류를 사용합니다. 평소 이동과 자율활동을 유지하면서 가끔 팝콘을 먹거나 응원합니다.')
        form.addRow(self.game_spectator_enabled)
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
        self.personality_traits = {}
        initial_traits = local['character'].get('personality_traits')
        if not isinstance(initial_traits, dict):
            initial_traits = PersonalitySystem(local['character']['personality']).personality.to_dict()
        self.personality_trait_inputs = {}
        trait_labels = {
            'openness': ('개방성', '익숙한 방식', '새로운 시도'),
            'conscientiousness': ('성실성', '즉흥적', '계획적'),
            'extraversion': ('외향성', '차분함', '활발함'),
            'agreeableness': ('친화성', '비판적', '협조적'),
            'neuroticism': ('신경질적', '정서적 안정', '민감함'),
        }
        for key, (label, low_label, high_label) in trait_labels.items():
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            ends = QLabel(low_label)
            ends.setMinimumWidth(68)
            ends.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            value = QSpinBox()
            value.setRange(-100, 100)
            value.setSuffix(' %')
            value.setMinimumWidth(88)
            numeric = round(max(-1.0, min(1.0, float(initial_traits.get(key, 0.0)))) * 100)
            slider.setValue(numeric)
            value.setValue(numeric)
            slider.valueChanged.connect(value.setValue)
            value.valueChanged.connect(slider.setValue)
            self.personality_trait_inputs[key] = value
            line.addWidget(ends)
            line.addWidget(slider, 1)
            line.addWidget(value)
            line.addWidget(QLabel(high_label))
            form.addRow(label, row)
        self.personality.currentIndexChanged.connect(self._load_personality_preset)
        self.dialogue_style = self._combo(DIALOGUE_STYLES,
            normalize_dialogue_style(local.get('dialogue', {}).get('style')))
        form.addRow('말풍선 UI', self.dialogue_style)
        self.dialogue_preview = DialogueBubble(
            '안녕하세요! 오늘은 어떤 이야기를 나눌까요?\n선택한 말풍선으로 대화를 표시합니다.',
            duration=0, preview=True)
        form.addRow('미리보기', self.dialogue_preview)
        self.dialogue_style.currentIndexChanged.connect(self._preview_dialogue_style)
        self._preview_dialogue_style()
        bubble_hint = QLabel('대화 내용과 음성 출력은 그대로 유지됩니다.\n'
                             '적용한 스타일은 다음 실행에도 유지됩니다. 긴 대화는 스크롤해서 읽을 수 있습니다.')
        bubble_hint.setWordWrap(True)
        form.addRow('', bubble_hint)

    def _preview_dialogue_style(self):
        self.dialogue_preview.set_style(self.dialogue_style.currentData())

    def _describe_size(self):
        percent = self.character_inputs['size_percent'].value()
        self.size_preview.setText(f"크기 배율: {percent}% · 가로세로 비율 유지")

    def _manual_page(self):
        _, _, form = self._page('직접 조작',
            '버튼을 누르면 즉시 실행합니다. 속도와 점프 높이는 현재 적용된 설정값을 사용합니다. '
            '변경한 설정으로 조작하려면 먼저 적용을 누르세요.')
        self.manual_status = QLabel('자동 행동 중')
        self.manual_status.setWordWrap(True)
        self.manual_status.setStyleSheet('font-weight: 600; color: #2463b6; padding: 8px 0;')
        form.addRow(self.manual_status)
        self.generate_dialogue_button = QPushButton('대사 생성')
        self.generate_dialogue_button.setAutoDefault(False)
        self.generate_dialogue_button.clicked.connect(lambda _checked=False: self.dialogue_generation_requested.emit())
        form.addRow(self.generate_dialogue_button)
        heading = QLabel('말풍선 직접 입력')
        heading.setStyleSheet('font-weight: 600; padding-top: 8px;')
        form.addRow(heading)
        self.manual_user_text = QPlainTextEdit()
        self.manual_character_text = QPlainTextEdit()
        self.manual_user_text.setPlaceholderText('사용자 말풍선에 표시할 대사')
        self.manual_character_text.setPlaceholderText('캐릭터 말풍선에 표시할 대사')
        for label, editor in (('사용자 대사', self.manual_user_text),
                              ('캐릭터 대사', self.manual_character_text)):
            editor.setAccessibleName(label)
            editor.setFixedHeight(70)
            form.addRow(label, editor)
        line = QWidget()
        buttons = QHBoxLayout(line)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.manual_bubble_buttons = {}
        for target, label in (('user', '사용자 표시'), ('character', '캐릭터 표시'), ('both', '둘 다 표시')):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, value=target: self._show_manual_bubbles(value))
            self.manual_bubble_buttons[target] = button
            buttons.addWidget(button)
        form.addRow(line)
        line = QWidget()
        buttons = QHBoxLayout(line)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.speak_manual_dialogue_button = QPushButton('말하기')
        self.speak_manual_dialogue_button.setAutoDefault(False)
        self.speak_manual_dialogue_button.clicked.connect(self._speak_manual_bubbles)
        buttons.addWidget(self.speak_manual_dialogue_button)
        self.hide_manual_bubbles_button = QPushButton('말풍선 숨기기')
        self.hide_manual_bubbles_button.setAutoDefault(False)
        self.hide_manual_bubbles_button.setEnabled(False)
        self.hide_manual_bubbles_button.clicked.connect(lambda: self.manual_dialogue_hide_requested.emit())
        buttons.addWidget(self.hide_manual_bubbles_button)
        form.addRow(line)
        hint = QLabel('입력한 대사를 그대로 표시합니다. 설정창을 닫아도 숨기기 전까지 유지됩니다.\n'
                      '말하기를 누르면 캐릭터 대사를 현재 설정된 음성으로 읽습니다.\n'
                      'AI 답변은 생성하지 않으며, 일반 대화를 시작하면 직접 표시가 해제됩니다.')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.command_buttons = {}
        for row in COMMAND_ROWS:
            line = QWidget()
            layout = QHBoxLayout(line)
            layout.setContentsMargins(0, 0, 0, 0)
            for command, label in row:
                button = QPushButton(label)
                button.setAutoDefault(False)
                button.clicked.connect(lambda _checked=False, value=command: self.character_command_requested.emit(value))
                self.command_buttons[command] = button
                layout.addWidget(button, 1)
            form.addRow(line)
        hint = QLabel('직접 조작 중에는 랜덤 이동·자동 점프·공 따라가기·자동 인사를 멈춥니다.\n'
                      '설정창을 닫아도 유지됩니다. 자동 행동 재개를 누르면 해제됩니다.\n'
                      '가만히 있기는 공중에서 좌우 이동만 멈춥니다. 인사·생각·잠자기는 착지 후 실행합니다.\n'
                      '기본 위치는 앱을 시작한 가로 위치의 바닥입니다.')
        hint.setWordWrap(True)
        form.addRow(hint)
        heading = QLabel('보이는 감정 설정')
        heading.setStyleSheet('font-weight: 600; padding-top: 8px;')
        form.addRow(heading)
        self.display_emotion_buttons = {}
        self.display_emotion_group = QButtonGroup(self)
        self.display_emotion_group.setExclusive(True)
        buttons = QWidget()
        grid = QGridLayout(buttons)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        for index, (emotion, label) in enumerate(DISPLAY_EMOTIONS):
            button = QPushButton(label)
            button.setObjectName('emotionButton')
            button.setAutoDefault(False)
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.clicked.connect(
                lambda _checked=False, value=emotion: self.display_emotion_requested.emit(value))
            self.display_emotion_group.addButton(button)
            self.display_emotion_buttons[emotion] = button
            grid.addWidget(button, index // 3, index % 3)
        form.addRow(buttons)
        self.display_emotion_reset = QPushButton('실제 감정 따르기')
        self.display_emotion_reset.setObjectName('emotionButton')
        self.display_emotion_reset.setAutoDefault(False)
        self.display_emotion_reset.setCheckable(True)
        self.display_emotion_group.addButton(self.display_emotion_reset)
        self.display_emotion_reset.clicked.connect(lambda: self.display_emotion_requested.emit(''))
        form.addRow(self.display_emotion_reset)
        self.display_emotion_status = QLabel()
        self.display_emotion_status.setWordWrap(True)
        form.addRow(self.display_emotion_status)
        face_hint = QLabel('화면에 보이는 표정만 바꿉니다. 실제 감정값·판단·기록은 계속 갱신됩니다.\n'
                           '설정창을 닫아도 유지되며 앱을 다시 실행하면 해제됩니다.\n'
                           'PNG 캐릭터에서는 보유한 대표 표정으로 표시합니다.')
        face_hint.setWordWrap(True)
        form.addRow(face_hint)
        self.set_display_emotion_state('')

    def set_manual_status(self, message):
        self.manual_status.setText(message)

    def _show_manual_bubbles(self, target):
        user = self.manual_user_text.toPlainText().strip() if target != 'character' else ''
        character = self.manual_character_text.toPlainText().strip() if target != 'user' else ''
        if not user and not character:
            self.status.setText('표시할 대사를 입력해 주세요.')
            return
        self.manual_dialogue_requested.emit(user, character)

    def _speak_manual_bubbles(self):
        user = self.manual_user_text.toPlainText().strip()
        character = self.manual_character_text.toPlainText().strip()
        if not character:
            self.status.setText('말할 캐릭터 대사를 입력해 주세요.')
            return
        self.manual_speech_requested.emit(user, character)

    def set_manual_dialogue_state(self, available, visible, *, voice_enabled=True, speaking=False):
        for button in self.manual_bubble_buttons.values():
            button.setEnabled(available)
            button.setToolTip('진행 중인 대화·음성 출력이 끝나면 표시할 수 있어요.' if not available else '')
        self.hide_manual_bubbles_button.setEnabled(available and visible)
        self.speak_manual_dialogue_button.setEnabled(available and voice_enabled)
        self.speak_manual_dialogue_button.setText('말하는 중…' if speaking else '말하기')
        self.speak_manual_dialogue_button.setToolTip(
            '음성 탭에서 AI 답변 음성으로 읽기를 켜 주세요.' if not voice_enabled else
            '진행 중인 대화·음성 출력이 끝나면 말할 수 있어요.' if not available else
            '입력한 캐릭터 대사를 현재 설정된 음성으로 읽습니다.')

    def set_dialogue_generation_state(self, generating, available=True):
        self.generate_dialogue_button.setText('대사 생성 중…' if generating else '대사 생성')
        self.generate_dialogue_button.setEnabled(not generating and available)
        self.generate_dialogue_button.setToolTip(
            '진행 중인 대사 생성을 기다려 주세요.' if generating else
            '대화·음성 출력이 끝나면 다시 생성할 수 있어요.' if not available else '')

    def set_display_emotion_state(self, emotion):
        selected = self.display_emotion_buttons.get(emotion, self.display_emotion_reset)
        selected.setChecked(True)
        self.display_emotion_status.setText(
            f'표정 고정 중 · {DISPLAY_EMOTION_NAMES[emotion]}' if emotion else '현재 표정: 실제 감정 따르기')

    def _describe_movement_range(self):
        size = self.character_inputs['size_percent'].value()
        extra = self.character_inputs['movement_range_extra_percent'].value()
        total = round(random_movement_scale(size, extra) * 100)
        self.movement_range_preview.setText(
            f'최종 이동 폭: 감정별 기본 폭의 {total}% (크기 {size}% + 추가 {extra:+d}%)'
            + (' · 랜덤 걷기 없음' if total == 0 else '')
        )

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

    def _load_personality_preset(self):
        preset = PersonalitySystem.PERSONALITY_PRESETS[self.personality.currentData()]
        for key, control in self.personality_trait_inputs.items():
            control.setValue(round(preset[key] * 100))

    def _voice_page(self, local):
        _, _, form = self._page('음성', 'AI 답변을 읽는 목소리를 선택하세요. 적용 즉시 바뀌며 다음 실행에도 유지됩니다.')
        self.tts_enabled = QCheckBox('AI 답변 음성으로 읽기')
        self.tts_enabled.setChecked(local['voice']['enabled'])
        self.voice = self._combo([(voice.name, voice.id) for voice in available_voices()], local['voice']['voice_id'])
        self.voice.setEnabled(self.tts_enabled.isChecked())
        self.tts_enabled.toggled.connect(self.voice.setEnabled)
        form.addRow(self.tts_enabled)
        form.addRow('목소리', self.voice)
        self.sync_bubble = QCheckBox('말풍선과 음성 재생 동기화')
        self.sync_bubble.setChecked(local['voice']['sync_bubble'])
        self.sync_bubble.setToolTip('켜면 음성이 실제로 시작될 때 말풍선을 표시합니다.\n'
                                   '끄면 답변을 먼저 표시합니다. 음성을 재생하지 못하면 텍스트만 표시합니다.')
        form.addRow(self.sync_bubble)
        self.voice_runtime_status = QLabel()
        self.voice_runtime_status.setWordWrap(True)
        form.addRow(self.voice_runtime_status)
        self.model_rows = {}
        for engine, name in ENGINE_NAMES.items():
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 6, 0, 6)
            heading = QHBoxLayout()
            heading.addWidget(QLabel(name))
            heading.addStretch()
            button = QPushButton('다운로드')
            button.clicked.connect(lambda checked=False, key=engine: self._download_voice_model(key))
            heading.addWidget(button)
            layout.addLayout(heading)
            status = QLabel()
            status.setWordWrap(True)
            layout.addWidget(status)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.hide()
            layout.addWidget(progress)
            form.addRow(row)
            self.model_rows[engine] = (button, status, progress)
        self.model_manager.changed.connect(self._refresh_voice_models)
        self.model_manager.progress_changed.connect(self._voice_download_progress)
        self.model_manager.finished.connect(self._voice_download_finished)
        self._refresh_voice_models()

    def _refresh_voice_models(self):
        try:
            runtime_python()
            ready = True
            self.voice_runtime_status.setText('추가 음성 실행 환경이 준비되어 있습니다.')
        except ValueError:
            ready = False
            self.voice_runtime_status.setText('추가 음성은 프로젝트의 setup_tts_runtime.cmd로 실행 환경을 먼저 준비해 주세요.')
        store, active = self.model_manager.store, self.model_manager.active_engine
        for engine, (button, status, progress) in self.model_rows.items():
            installed = store.installed(engine)
            self.voice.model().item(self.voice.findData(engine)).setEnabled(installed and ready)
            if active == engine:
                button.setText('취소')
                button.setEnabled(True)
                progress.show()
                status.setText('음성 모델을 다운로드하고 검증하는 중입니다.')
            else:
                progress.hide()
                button.setText('설치 완료' if installed else '다시 다운로드' if engine in self.model_manager.last_result else '다운로드')
                button.setEnabled(active is None and not installed and store.published(engine))
                if engine in self.model_manager.last_result:
                    status.setText(self.model_manager.last_result[engine][1])
                elif installed:
                    status.setText('설치 완료 — 목소리를 선택하고 적용해 주세요.')
                elif not store.published(engine):
                    status.setText('배포 준비 중 — 학습한 목소리가 게시되면 다운로드할 수 있습니다.')
                else:
                    size = sum(a['size'] for a in store.assets(engine)) / 1024**3
                    status.setText(f'미설치 · 최대 {size:.2f} GiB 다운로드 · 공통 파일은 재사용합니다.')

    def _download_voice_model(self, engine):
        if self.model_manager.active_engine == engine:
            self.model_manager.cancel()
            self.model_rows[engine][1].setText('취소 중…')
        else:
            self.model_rows[engine][2].setValue(0)
            self.model_manager.start(engine)

    def _voice_download_progress(self, engine, value, text):
        _, status, progress = self.model_rows[engine]
        progress.setValue(value)
        status.setText(text)

    def _voice_download_finished(self, engine, ok, message):
        self._refresh_voice_models()
        self.model_rows[engine][1].setText(message)

    def _recognition_page(self, local):
        _, layout, self.remote_form = self._page('사용자 인식', '카메라·감정 인식은 실행 중에 적용됩니다. 마이크·STT 옵션을 바꾸면 실행 중인 음성 인식을 자동으로 다시 시작합니다.')
        self.remote_status = QLabel('인식 기능에 연결하는 중…')
        self.remote_status.setWordWrap(True)
        layout.insertWidget(1, self.remote_status)
        self.refresh_button = QPushButton('장치 새로고침')
        self.refresh_button.clicked.connect(lambda: self.refresh_requested.emit(True))
        layout.insertWidget(2, self.refresh_button)
        self._hand_overlay_fields(local)
        heading = QLabel('카메라·음성 인식')
        heading.setStyleSheet('font-weight: 600; padding-top: 12px;')
        self.remote_form.addRow(heading)
        self.remote_fields = QWidget()
        self.fields_form = QFormLayout(self.remote_fields)
        self.fields_form.setContentsMargins(0, 0, 0, 0)
        self.fields_form.setVerticalSpacing(10)
        self.fields_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.remote_form.addRow(self.remote_fields)
        self.remote_fields.setEnabled(False)
        self.preview_button = QPushButton('카메라 미리보기')
        self.preview_button.setCheckable(True)
        self.preview_button.toggled.connect(self._sync_preview)
        self.preview_enlarge_button = QPushButton('크게 보기')
        self.preview_enlarge_button.setAutoDefault(False)
        self.preview_enlarge_button.clicked.connect(self._show_large_preview)
        preview_buttons = QHBoxLayout()
        preview_buttons.addWidget(self.preview_button, 1)
        preview_buttons.addWidget(self.preview_enlarge_button)
        self.remote_form.insertRow(0, preview_buttons)
        self.preview_window = None
        self.preview_label = _PreviewImage('미리보기를 켜면 카메라 영상과 인식 결과가 표시됩니다.')
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setMaximumHeight(240)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.preview_label.setStyleSheet('background: #15202c; color: #dce5f0; border-radius: 6px;')
        self.remote_form.insertRow(1, self.preview_label)
        self.preview_status = QLabel('')
        self.preview_status.setWordWrap(True)
        self.remote_form.insertRow(2, self.preview_status)
        self.device_buttons = {}
        device_row = QHBoxLayout()
        for operation, label in [('camera_start', '카메라 시작'), ('camera_stop', '카메라 중지'),
                                 ('stt_start', '음성 인식 시작'), ('stt_stop', '음성 인식 중지')]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, op=operation: self.device_requested.emit(op))
            device_row.addWidget(button)
            self.device_buttons[operation] = button
        self.remote_form.insertRow(3, device_row)
        for button in self.device_buttons.values():
            button.setEnabled(False)

    def _sync_preview(self, *_args):
        if not hasattr(self, '_preview_active'):
            return
        enabled = (self.isVisible() and not self.isMinimized() and self.tabs.currentIndex() == 2
                   and self.preview_button.isChecked())
        if enabled != self._preview_active:
            self._preview_active = enabled
            self.preview_requested.emit(enabled)
            if not enabled:
                self._preview_message('미리보기가 꺼져 있습니다. 카메라 인식은 계속됩니다.')
                self.preview_status.clear()
                if self.preview_window is not None:
                    self.preview_window.close()

    def _show_large_preview(self):
        self.preview_button.setChecked(True)
        if self.preview_window is None:
            self.preview_window = QDialog(self, Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint
                                           | Qt.WindowType.WindowCloseButtonHint)
            self.preview_window.setWindowTitle('카메라 미리보기 · 크게 보기')
            self.preview_window.resize(1000, 750)
            self.preview_window.setMinimumSize(480, 360)
            layout = QVBoxLayout(self.preview_window)
            self.large_preview_label = _PreviewImage('카메라 화면을 기다리는 중…')
            layout.addWidget(self.large_preview_label, 1)
            close_button = QPushButton('닫기')
            close_button.clicked.connect(self.preview_window.close)
            layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        if not self.preview_label._image.isNull():
            self.large_preview_label.set_image(self.preview_label._image)
        else:
            self.large_preview_label.set_message(self.preview_label.text())
        self.preview_window.show()
        self.preview_window.raise_()
        self.preview_window.activateWindow()

    def _preview_message(self, text):
        self.preview_label.set_message(text)
        if self.preview_window is not None:
            self.large_preview_label.set_message(text)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_preview()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_preview()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_preview()

    def show_preview_packet(self, packet):
        if not self._preview_active:
            return
        try:
            encoded = packet['jpeg']
            if not isinstance(encoded, str) or len(encoded) > 270_000:
                return
            image = QImage.fromData(base64.b64decode(encoded, validate=True), 'JPEG')
        except (ValueError, KeyError, TypeError, binascii.Error):
            return
        if image.isNull() or image.width() > 1280 or image.height() > 1280:
            return
        self.preview_label.set_image(image)
        if self.preview_window is not None and self.preview_window.isVisible():
            self.large_preview_label.set_image(image)
        state = packet.get('state') or {}
        emotion = (state.get('emotion') or {}).get('label') or '인식 대기'
        self.preview_status.setText(f"{state.get('result', '')}\n감정: {emotion}\n음성: {state.get('speech', '')}")

    def _hand_overlay_fields(self, local):
        options = normalize_hand_overlay_options(local.get('hand_overlay'))
        heading = QLabel('바탕화면 손 표시')
        heading.setStyleSheet('font-weight: 600; padding-top: 8px;')
        self.remote_form.addRow(heading)
        self.hand_display = QCheckBox('바탕화면에 손 랜드마크 표시')
        self.hand_display.setToolTip(
            '검지만 펴고 나머지는 굽힌 채 머리 윗부분에 닿으면 쓰다듬습니다.\n'
            '엄지·검지를 살짝 굽혀 머리를 잡고, 손가락을 모두 펴면 놓습니다.\n'
            '검지로 볼을 찌르면 뒤로 밀립니다.\n'
            '공은 엄지·검지를 맞대어 집고, 손을 펴서 놓습니다.\n'
            '편 손을 가로로 놓으면 캐릭터를 손 위에 태울 수 있습니다.\n'
            '공은 캐릭터 우클릭 메뉴의 공 꺼내기로 만드세요.')
        self.hand_display.setChecked(options['enabled'])
        self.remote_form.addRow(self.hand_display)
        self.hand_inputs = {}
        self.hand_sliders = {}
        for key, label in (('size_percent', '손 표시 크기'), ('range_percent', '카메라 이동 범위')):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            spin = QSpinBox()
            low, high = HAND_OVERLAY_OPTION_RANGES[key]
            slider.setRange(low, high)
            spin.setRange(low, high)
            spin.setSuffix(' %')
            spin.setMinimumWidth(100)
            slider.setValue(options[key])
            spin.setValue(options[key])
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            self.hand_sliders[key] = slider
            self.hand_inputs[key] = spin
            line.addWidget(slider, 1)
            line.addWidget(spin)
            self.remote_form.addRow(label, row)
        self.hand_range_preview = QLabel()
        self.hand_range_preview.setWordWrap(True)
        self.remote_form.addRow('', self.hand_range_preview)
        self.hand_inputs['range_percent'].valueChanged.connect(self._describe_hand_range)
        self._describe_hand_range()
        self.hand_count = self._combo([('한 손', 1), ('두 손', 2)], options['max_hands'])
        self.remote_form.addRow('표시할 손 수', self.hand_count)
        self.hand_smooth = QCheckBox('손 움직임 보정')
        self.hand_smooth.setChecked(options['smooth'])
        self.remote_form.addRow(self.hand_smooth)
        hint = QLabel('기존 카메라의 손 좌표를 사용합니다. 카메라가 꺼져 있거나 손을 인식하지 못하면 표시하지 않습니다.')
        hint.setWordWrap(True)
        self.remote_form.addRow('', hint)

    def _describe_hand_range(self):
        percent = self.hand_inputs['range_percent'].value()
        self.hand_range_preview.setText(
            f'카메라 중앙의 가로·세로 {percent}% 영역을 화면 전체에 대응합니다.\n'
            '영역 밖에서는 화면 가장자리 위치를 유지합니다. 비율을 줄이면 더 작은 손 이동으로 화면 끝까지 도달합니다.')

    def set_remote(self, state, preserve_draft=False):
        draft = self.changes()['remote'] if preserve_draft else {}
        self.remote_baseline = deepcopy(state['values'])
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self.controls = {}
        choices = state['choices']
        labels = {'camera': '카메라', 'microphone': '마이크',
                  'mode': '인식 도구', 'emotion_model': '감정 인식 모델', 'provider': 'STT 서비스',
                  'language': '인식 언어', 'silence': '발화 종료 대기', 'sensitivity': '마이크 민감도'}
        for key, label in labels.items():
            if key not in choices:
                continue
            combo = self._combo([(item['label'], item['value']) for item in choices[key]], state['values'].get(key))
            if not combo.count():
                combo.addItem('사용 가능한 장치 없음', None)
                combo.setEnabled(False)
            self.controls[key] = combo
            self.fields_form.addRow(label, combo)
            if key == 'mode':
                combo.setEnabled(not state.get('game_active', False))
        for key, label in [('tracking', '추적 지점 표시'), ('marker_only', '검은 배경에 추적 지점 표시'),
                           ('mirror', '좌우 반전'), ('info_overlay', '영상에 상태 표시'),
                           ('cham_overlay', '영상에 참참참 방향 표시'),
                           ('emotion', '영상에 감정 결과 표시'), ('always_recognition', '영상에 동작 결과 표시')]:
            if key not in state['values']:
                continue
            check = QCheckBox(label)
            check.setChecked(bool(state['values'].get(key)))
            self.controls[key] = check
            self.fields_form.addRow(check)
        for key, value in draft.items():
            if key not in self.controls:
                continue
            control = self.controls[key]
            if isinstance(control, QCheckBox):
                control.setChecked(value)
            else:
                index = control.findData(value)
                if index >= 0:
                    control.setCurrentIndex(index)
        self.remote_fields.setEnabled(True)
        self.remote_status.setText(state.get('status', '현재 설정을 불러왔습니다.'))
        if not state.get('camera_running', False) and self._preview_active:
            self._preview_message('카메라가 중지되어 있습니다. 카메라 시작을 눌러 주세요.')
        for operation, button in self.device_buttons.items():
            running = state.get('camera_running', False) if operation.startswith('camera_') else state.get('stt_running', False)
            button.setEnabled(bool(running) != operation.endswith('_start'))

    def remote_unavailable(self, message):
        self.remote_status.setText(message)
        self.remote_fields.setEnabled(False)
        self.remote_baseline = None
        self._preview_message('인식 작업에 연결하지 못했습니다. 장치 새로고침으로 다시 연결하세요.')
        self.preview_status.clear()
        for button in self.device_buttons.values():
            button.setEnabled(False)

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

    def _game_rules_page(self, local):
        _, _, form = self._page('게임 목록', '게임으로 인식할 프로그램을 편집하세요. 한 줄에 하나씩 입력하고 적용을 눌러 저장합니다.')
        self.game_rules_tab = self.tabs.widget(self.tabs.count()-1)
        self.game_processes = QPlainTextEdit()
        self.game_processes.setPlaceholderText('MyGame.exe\n실행 파일 이름을 정확히 입력하세요.')
        self.game_processes.setPlainText('\n'.join(local['game_rules']['included_processes']))
        self.game_processes.setMinimumHeight(90)
        self.game_processes.setMaximumHeight(130)
        self.game_processes.setAccessibleName('게임으로 등록한 실행 파일 목록')
        form.addRow('등록한 게임', self.game_processes)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.game_running_processes = _SettingsComboBox()
        line.addWidget(self.game_running_processes, 1)
        add = QPushButton('목록에 추가')
        add.clicked.connect(self._add_running_game)
        line.addWidget(add)
        refresh = QPushButton('새로고침')
        refresh.clicked.connect(self._refresh_game_processes)
        line.addWidget(refresh)
        form.addRow('실행 중인 앱', row)
        self.game_rules_hint = QLabel('게임 실행 파일 이름으로 정확히 일치시킵니다. 삭제하려면 해당 줄을 지우세요.')
        self.game_rules_hint.setWordWrap(True)
        form.addRow('', self.game_rules_hint)
        self.game_keywords = QPlainTextEdit()
        self.game_keywords.setPlainText('\n'.join(local['game_rules']['keywords']))
        self.game_keywords.setMinimumHeight(75)
        self.game_keywords.setMaximumHeight(110)
        self.game_keywords.setAccessibleName('게임 분류 키워드')
        form.addRow('기본 키워드', self.game_keywords)
        reset = QPushButton('키워드 기본값 복원')
        reset.clicked.connect(lambda: self.game_keywords.setPlainText('\n'.join(DEFAULT_GAME_RULES['keywords'])))
        form.addRow('', reset)
        self.game_excluded_processes = QPlainTextEdit()
        self.game_excluded_processes.setPlaceholderText('게임으로 잘못 인식한 프로그램.exe')
        self.game_excluded_processes.setPlainText('\n'.join(local['game_rules']['excluded_processes']))
        self.game_excluded_processes.setMinimumHeight(75)
        self.game_excluded_processes.setMaximumHeight(110)
        self.game_excluded_processes.setAccessibleName('게임 분류에서 제외할 실행 파일 목록')
        form.addRow('제외할 앱', self.game_excluded_processes)
        hint = QLabel('제외 목록이 등록 목록·키워드보다 우선합니다. 게임 관람 동작은 캐릭터 탭의 게임 활동 반응 설정을 따릅니다.')
        hint.setWordWrap(True)
        form.addRow('', hint)
        self._refresh_game_processes()

    def _refresh_game_processes(self):
        selected = self.game_running_processes.currentData()
        self.game_running_processes.clear()
        self.game_running_processes.addItem('실행 중인 프로그램 선택', None)
        try:
            for name in running_process_names():
                self.game_running_processes.addItem(name, name)
        except OSError:
            self.game_rules_hint.setText('실행 중인 앱을 읽지 못했습니다. 위 목록에 실행 파일 이름을 직접 입력할 수 있습니다.')
        index = self.game_running_processes.findData(selected)
        if index >= 0:
            self.game_running_processes.setCurrentIndex(index)

    def _add_running_game(self):
        process = self.game_running_processes.currentData()
        if not process:
            self.game_rules_hint.setText('추가할 프로그램을 선택하세요.')
            return
        values = self.game_processes.toPlainText().splitlines()
        if process not in {name.strip().lower() for name in values}:
            values.append(process)
            self.game_processes.setPlainText('\n'.join(values))
        self.game_rules_hint.setText(f'{process}을(를) 추가했습니다. 적용을 눌러 저장하세요.')

    def changes(self):
        local = {'character': {'width': self.width.value(), 'height': self.height.value(),
                               'personality': self.personality.currentData(),
                               'personality_traits': {key: control.value() / 100.0
                                                     for key, control in self.personality_trait_inputs.items()}},
                 'voice': {'enabled': self.tts_enabled.isChecked(), 'voice_id': self.voice.currentData(),
                           'sync_bubble': self.sync_bubble.isChecked()},
                 'ai': {'api_key': self.api_key.text().strip(), 'model': self.model.text().strip()}}
        local['character'].update({key: control.value() for key, control in self.character_inputs.items()})
        local['character']['show_hitboxes'] = self.show_hitboxes.isChecked()
        local['character']['window_occlusion'] = self.window_occlusion.isChecked()
        local['character']['game_spectator'] = self.game_spectator_enabled.isChecked()
        changed = {key: value for key, value in local.items() if value != self.local_baseline[key]}
        game_rules = normalize_game_rules({
            'included_processes': self.game_processes.toPlainText().splitlines(),
            'keywords': self.game_keywords.toPlainText().splitlines(),
            'excluded_processes': self.game_excluded_processes.toPlainText().splitlines(),
        })
        if game_rules != self.local_baseline['game_rules']:
            changed['game_rules'] = game_rules
        dialogue = {'style': self.dialogue_style.currentData()}
        baseline = {'style': normalize_dialogue_style(self.local_baseline.get('dialogue', {}).get('style'))}
        if dialogue != baseline:
            changed['dialogue'] = dialogue
        hand_overlay = {'enabled': self.hand_display.isChecked(),
                        **{key: control.value() for key, control in self.hand_inputs.items()},
                        'max_hands': self.hand_count.currentData(), 'smooth': self.hand_smooth.isChecked()}
        if hand_overlay != normalize_hand_overlay_options(self.local_baseline.get('hand_overlay')):
            changed['hand_overlay'] = hand_overlay
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
        try:
            changes = self.changes()
        except ValueError as exc:
            self.status.setText(str(exc))
            self.tabs.setCurrentWidget(self.game_rules_tab)
            self.game_processes.setFocus()
            return
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
        log_event('settings.remote.timeout', '인식 설정 응답 시간이 지나 실제 적용 여부를 알 수 없습니다.',
                  trace_id=self.log_trace_id, level='WARNING', result='unknown', timeout_seconds=45)
        self.apply_timeout.emit(self.log_trace_id or '')
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
