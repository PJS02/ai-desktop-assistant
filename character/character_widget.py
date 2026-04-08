# 캐릭터 위젯을 관리하는 파일
import random
from pathlib import Path
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import QTimer, Qt, QPoint
from .mood_system import MoodSystem
from .animations import AnimationController

class CharacterWidget(QLabel):
    def __init__(self):
        super().__init__()

        # 배경창 투명화
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 기본 설정
        self.mood_system = MoodSystem()
        self.current_action = "idle"
        self.drag_pos = None
        self.current_pixmap = None
        self.is_flipped = False
        self.assets_path = Path(__file__).resolve().parent.parent / "assets"
        
        self.setFixedSize(800, 800)
        self.update_render("idle")
        
        # 애니메이션 컨트롤러
        self.animation_controller = AnimationController(self.pos())
        self.animation_controller.position_changed.connect(self.on_animation_position_changed)
        self.animation_controller.start_idle()

        # 타이머들
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_mood)
        self.timer.start(1000)

        self.move_timer = QTimer()
        self.move_timer.timeout.connect(self.random_move)
        self.move_timer.start(1000)

        # 드래그 관련
        self.is_dragging = False
        self.drag_time = 0
        self.drag_timer = QTimer()
        self.drag_timer.timeout.connect(self.update_dragging)
        self.drag_timer.start(100)

        # 이동 타이머 미리 생성
        self._move_timer = QTimer()
        self._move_timer.timeout.connect(self._smooth_moving)
        self._remaining_steps = 0
        self.step_x = 0
        self.step_y = 0

        self.is_moving = False

    # 애니메이션 신호 처리
    def on_animation_position_changed(self, new_pos):
        """애니메이션이 위치 변경을 요청 (이동 중에는 멈춤)"""
        if not self.is_moving and not self.is_dragging:
            self.move(new_pos)

    def update_mood(self):
        if self.is_dragging or self.is_moving:
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

    # 출력
    def render(self):
        self.update_render(self.current_action)

    def update_render(self, action):
        path = self.assets_path / f"{action}.png"
        pixmap = QPixmap(str(path))
        self.current_pixmap = pixmap  # 원본 이미지 저장 (필수!)
        self.setPixmap(pixmap)

    #좌우 반전 
    def set_pixmap_with_flip(self, pixmap):
        """좌우반전 상태에 따라 이미지 설정"""
        if pixmap is None:
            print("pixmap: NONE!")
            return
        if self.is_flipped:
            # 좌우반전
            transform = QTransform()
            transform.scale(-1, 1)  # 가로 반전
            flipped_pixmap = pixmap.transformed(transform)
            self.setPixmap(flipped_pixmap)
        else:
            self.setPixmap(pixmap)
        
        self.repaint()

    # 클릭 이벤트
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mood_system.on_click()
            self.drag_pos = event.globalPosition().toPoint()
            print(f"[지금 상태] {self.mood_system.mood}")

            self.is_dragging = True
            self.drag_time = 0

    def mouseMoveEvent(self, event):
        if self.is_dragging and self.drag_pos:
            self.move(self.pos() + event.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = event.globalPosition().toPoint()
            self.animation_controller.update_base_pos(self.pos())

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.drag_time = 0
        self.drag_pos = None
        self.animation_controller.update_base_pos(self.pos())
        self.animation_controller.start_idle()

    def update_dragging(self):
        if self.is_dragging:
            self.drag_time += 0.1
            self.mood_system.mood["angry"] += 0.02
            self.mood_system.mood["happy"] *= 0.98
            self.update_render("talking")
    
    # 캐릭터 랜덤 이동
    def random_move(self):
        print(f"[random_move 시작] is_dragging={self.is_dragging}, is_moving={self.is_moving}")
        if self.is_dragging or self.is_moving:
            print(f"[early return] 드래그 중 또는 이동 중 스킵")
            return
        
        if random.random() > 0.8:  # 20% 확률로 이동 스킵
            print(f"[random skip] 확률로 스킵")
            return
        
        mood = self.mood_system.decide_emotion()
        emotion = mood['emotion']
        print(f"[감정] emotion={emotion}")


        # 감정에 따라 움직이는 범위 결정
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

        # 이동 방향에 따라 좌우반전 결정
        if dx > 0:
            self.is_flipped = True
        elif dx < 0:
            self.is_flipped = False

        print(f"이동: dx={dx}, dy={dy}, is_flipped={self.is_flipped}, pixmap_none={self.current_pixmap is None}")
        
        # 이미지 반전 적용
        if self.current_pixmap is not None:
            self.set_pixmap_with_flip(self.current_pixmap)
        
        # 이동 설정
        steps = 10
        self.step_x = dx // steps if steps > 0 else 0
        self.step_y = dy // steps if steps > 0 else 0
        self._remaining_steps = steps
        
        # 이동 시작
        self.is_moving = True
        self.animation_controller.idle.stop()
        self._move_timer.start(20)
    
    def _smooth_moving(self):
        """슬라이딩 이동 애니메이션"""
        if self._remaining_steps <= 0:
            self._move_timer.stop()
            self.is_moving = False
            self.animation_controller.update_base_pos(self.pos())
            self.animation_controller.start_idle()
            return

        self.move(self.x() + self.step_x, self.y() + self.step_y)
        self.update()  
        self._remaining_steps -= 1