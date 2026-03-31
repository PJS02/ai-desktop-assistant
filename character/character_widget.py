# 캐릭터 위젯을 관리하는 파일
import os
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QTimer, Qt
from ai.ai_service import ask_ai
from .mood_system import MoodSystem

class CharacterWidget(QLabel):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.mood_system = MoodSystem()
        self.current_action = "idle"

        self.drag_pos = None

        self.setFixedSize(800, 800)
        self.update_render("idle")

        # 타이머 (시간에 따른 감정 변화)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_mood)
        self.timer.start(1000)

        # 드래그 타이머 및 드래그 초기화
        self.is_dragging = False
        self.drag_time = 0
        self.drag_timer = QTimer()
        self.drag_timer.timeout.connect(self.update_dragging)
        self.drag_timer.start(100) #0.1초 갱신

    #  캐릭터 감정 변화
    def update_mood(self):
        if self.is_dragging:
            return
        
        self.mood_system.decay()
        mood = self.mood_system.decide_emotion()
        self.update_action(mood)

    # 행동 결정
    def update_action(self, mood):
        emotion = mood["emotion"]
        intensity = mood["intensity"]

        if emotion == "happy":
            self.current_action = "happy"
        elif emotion == "angry":
            self.current_action = "angry"
        elif emotion == "bored":
            self.current_action = "bored"
        else:
            self.current_action = "idle"

        self.render()

    # 출력 (나중에 애니메이션으로 교체 예정)
    def render(self):
        self.update_render(self.current_action)

    def update_render(self, action):
        path = os.path.join("assets", f"{action}.png")
        pixmap = QPixmap(path)
        self.setPixmap(pixmap)

    # 클릭 이벤트
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mood_system.on_click()
            self.drag_pos = event.globalPosition().toPoint()

            self.is_dragging = True
            self.drag_time = 0
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.is_dragging and self.drag_pos:
            self.move(self.pos() + event.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
         self.is_dragging = False
         self.drag_time = 0
         self.drag_pos = None

    def update_dragging(self):
        if self.is_dragging:
            self.drag_time += 0.1

            #  오래 끌수록 화남
            self.mood_system.mood["angry"] += 0.02

            #  조금씩 행복 감소
            self.mood_system.mood["happy"] *= 0.98

            #  드래그 중 표정 고정(일단 idle로)
            self.update_render("talking")