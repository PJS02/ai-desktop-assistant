"""Choose a personality before showing the desktop character."""

from pathlib import Path

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .personality_system import PersonalitySystem


PORTRAITS = Path(__file__).resolve().parents[1] / 'assets' / 'ui' / 'personality'
DEFAULT_CROP = (11, 55, 438, 582)
CARD_DETAILS = {
    PersonalitySystem.DEFAULT_PRESET: ('a', DEFAULT_CROP, '균형 잡힌 도우미', '#edf4fa'),
    '밝고 활발': ('c', (450, 55, 436, 582), '활기찬 대화', '#fff4dd'),
    '진중하고 신중': ('a', (884, 55, 420, 582), '차분한 설명', '#edf1f9'),
    '친근하고 따뜻': ('b', (1303, 55, 448, 582), '따뜻한 공감', '#ffffff'),
    '창의적이고 자유로움': ('a', (1732, 55, 432, 582), '새로운 관점', '#f1ebf8'),
}


class StartupPersonalityDialog(QDialog):
    start_requested = pyqtSignal(str)

    def __init__(self, saved_personality):
        super().__init__()
        self.setObjectName('startupPersonality')
        self.setWindowTitle('클라우디 · 성격 선택')
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setStyleSheet('''
            QDialog#startupPersonality, QWidget#personalityCards { background: #ffffff; }
            QLabel { color: #263645; font-family: "Malgun Gothic"; }
            QLabel#personalityTitle { font-size: 23px; font-weight: bold; }
            QLabel#personalityName { font-size: 13px; font-weight: bold; }
            QLabel#personalityCaption { color: #526174; font-size: 12px; }
            QPushButton#personalityCard { background: #ffffff; border: 1px solid #cbd3dc;
                border-radius: 10px; }
            QPushButton#personalityCard:hover { background: #f5f8fc; }
            QPushButton#personalityCard:checked { background: #eaf2fb; border-color: #325f90; }
            QPushButton#personalityCard:focus { border: 2px solid #4d6b89; }
            QPushButton#personalityStart { color: #ffffff; background: #325f90;
                border: 1px solid #325f90; border-radius: 7px; padding: 8px 16px;
                font-family: "Malgun Gothic"; font-size: 13px; font-weight: bold; }
            QPushButton#personalityStart:hover { background: #284e79; }
            QPushButton#personalityStart:focus { border: 2px solid #203952; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 17, 18, 15)
        layout.setSpacing(10)
        title = QLabel('어떤 성격으로 시작할까요?')
        title.setObjectName('personalityTitle')
        title.setWordWrap(True)
        layout.addWidget(title)

        self._cards = QScrollArea()
        self._cards.setFrameShape(QFrame.Shape.NoFrame)
        self._cards.setWidgetResizable(True)
        self._cards.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cards.setFixedHeight(236)
        card_panel = QWidget()
        card_panel.setObjectName('personalityCards')
        row = QHBoxLayout(card_panel)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(10)
        self._choices = QButtonGroup(self)
        buttons = {}
        sheets = {key: QPixmap(str(PORTRAITS / f'cloudy-{key}.png')) for key in ('a', 'b', 'c')}
        for preset, traits in PersonalitySystem.PERSONALITY_PRESETS.items():
            button = self._make_card(preset, traits['description'], sheets)
            self._choices.addButton(button)
            buttons[preset] = button
            row.addWidget(button, 1)
        self._cards.setWidget(card_panel)
        layout.addWidget(self._cards)

        footer = QHBoxLayout()
        self._selection = QLabel()
        self._selection.setObjectName('personalityCaption')
        self._selection.setWordWrap(True)
        start = QPushButton('시작하기')
        start.setObjectName('personalityStart')
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.setDefault(True)
        start.clicked.connect(self._start)
        footer.addWidget(self._selection, 1)
        footer.addWidget(start)
        layout.addLayout(footer)

        self._choices.buttonToggled.connect(self._update_selection)
        selected = buttons.get(saved_personality, buttons[PersonalitySystem.DEFAULT_PRESET])
        selected.setChecked(True)
        selected.setFocus()
        screen = QApplication.primaryScreen()
        width = min(864, screen.availableGeometry().width() - 24) if screen else 864
        self.resize(width, self.sizeHint().height())

    def _make_card(self, preset, description, sheets):
        sheet, crop, caption, tint = CARD_DETAILS.get(preset, ('a', DEFAULT_CROP, description, '#edf4fa'))
        name = '기본' if preset == PersonalitySystem.DEFAULT_PRESET else preset
        card = QPushButton()
        card.setObjectName('personalityCard')
        card.setProperty('preset', preset)
        card.setCheckable(True)
        card.setAutoDefault(False)
        card.setMinimumWidth(136)
        card.setFixedHeight(216)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setAccessibleName(name)
        card.setAccessibleDescription(description)
        card.setToolTip(description)
        contents = QVBoxLayout(card)
        contents.setContentsMargins(7, 7, 7, 7)
        contents.setSpacing(4)
        picture = QLabel()
        picture.setFixedHeight(128)
        picture.setStyleSheet(f'background: {tint}; border-radius: 7px;')
        picture.setPixmap(sheets[sheet].copy(QRect(*crop)).scaled(
            99, 126, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title = QLabel(name)
        title.setObjectName('personalityName')
        title.setFixedHeight(36)
        title.setWordWrap(True)
        detail = QLabel(caption)
        detail.setObjectName('personalityCaption')
        detail.setWordWrap(True)
        for label in (picture, title, detail):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            contents.addWidget(label)
        return card

    def _update_selection(self, button, checked):
        if checked:
            self._selection.setText(button.accessibleName() + ' 선택됨')
            self._cards.ensureWidgetVisible(button, 5, 0)

    def _start(self):
        self.start_requested.emit(self._choices.checkedButton().property('preset'))
