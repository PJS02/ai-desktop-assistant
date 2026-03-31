# 캐릭터 위젯을 관리하는 파일
import os
import random
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QTimer, Qt
from ai.ai_service import ask_ai
from .mood_system import MoodSystem

class CharacterWidget(QLabel):
    def __init__(self):
        super().__init__()

        # 배경창 투명화
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 캐릭터 fsm 적용 기본 상태는 "idle"
        self.mood_system = MoodSystem()
        self.current_action = "idle"

        self.drag_pos = None

        self.setFixedSize(800, 800)
        self.update_render("idle")

        # 타이머 (시간에 따른 감정 변화)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_mood)
        self.timer.start(1000)

        # 랜덤하게 움직이게 함 2초? 정도로 텀을 둘까 싶음
        self.move_timer = QTimer()
        self.move_timer.timeout.connect(self.random_move)
        self.move_timer.start(1000)

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
            print(f"[지금 상태] {self.mood_system.mood}")

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
    
    # 캐릭터 랜덤 이동, 자유이동
    def random_move(self):
        if self.is_dragging:
            return #드래그 중엔 이동 불가
        
        if random.random() > 0.6: #60퍼센트 확률로 움직임
            return
        
        mood = self.mood_system.decide_emotion()
        emotion = mood['emotion']

        if emotion == "happy":
            dx = random.randint(-100, 100)
            dy = random.randint(-500, 500)
        elif emotion == "angry":
            dx = random.randint(-800, 800)
            dy = random.randint(-300, 300)
        elif emotion == "bored":
            dx = random.randint(-100, 100)
            dy = random.randint(-100, 100)
        else:
            dx = random.randint(-200, 200)
            dy = random.randint(-200, 200)
        
        steps =10
        step_x = dx//steps
        step_y = dy//steps

        # 기존 애니메이션 있으면 중지
        if hasattr(self, "_move_timer"):
            self._move_timer.stop()

        self._remaining_steps = steps

        def smooth_moving():
                if self._remaining_steps <= 0:
                    self._move_timer.stop()
                    return

                self.move(self.x() + step_x, self.y() + step_y)
                self._remaining_steps -= 1

         # 부드러운 이동 타이머 생성
        self._move_timer = QTimer()
        self._move_timer.timeout.connect(smooth_moving) 
        self._move_timer.start(20)

