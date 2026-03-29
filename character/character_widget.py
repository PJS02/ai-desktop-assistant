
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from ai.ai_service import ask_ai

class CharacterWidget(QLabel):

    def __init__(self):
        super().__init__()

        self.click_count=0
        pixmap = QPixmap("assets/idle.png")
        self.setPixmap(pixmap)
        self.adjustSize()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
    
    def mousePressEvent(self, event):

        self.set_emotion("talking")

        reply = ask_ai("사용자가 캐릭터를 클릭했습니다. 간단히 인사하세요.")
        print("AI:", reply)

        self.set_emotion("happy")
        
        if self.click_count >= 5:
            self.set_emotion("idle")
            self.click_count = 0

    def set_emotion(self, emotion):

        if emotion == "idle":
            self.setPixmap(QPixmap("assets/idle.png"))

        elif emotion == "talking":
            self.setPixmap(QPixmap("assets/talking.png"))

        elif emotion == "happy":
            self.setPixmap(QPixmap("assets/happy.png"))
