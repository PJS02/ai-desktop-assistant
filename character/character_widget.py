# 캐릭터 위젯을 관리하는 파일
import random
from pathlib import Path
from PyQt6.QtWidgets import QLabel, QApplication
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import QTimer, Qt, QPoint
from .mood_system import MoodSystem
from .animations import AnimationController
from .sprite_animator import SpriteAnimator


class Surface:
    """캐릭터가 올라갈 수 있는 표면 (바닥, 팝업창 등)"""
    def __init__(self, name: str, y_level: int):
        self.name = name      # 표면 이름
        self.y_level = y_level  # 캐릭터가 올라갈 Y좌표
    
    def __repr__(self):
        return f"Surface({self.name}, y={self.y_level})"

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
        
        # 스프라이트 애니메이터 초기화
        self.sprite_animator = SpriteAnimator(self.assets_path)
        self.sprite_animator.frame_changed.connect(self.on_sprite_frame_changed)
        self.sprite_animator.animation_finished.connect(self.on_animation_finished)
        
        
        # 이미지는 별도로 축소하여 대응
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
        self.move_timer.start(3000)  # 1초 → 3초 (걷기 빈도 감소)

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
        
        # ====== Surface 시스템 (바닥, 팝업창 등) ======
        self.surfaces = []  # 캐릭터가 올라갈 수 있는 모든 표면
        self.current_surface = None  # 현재 캐릭터가 위에 있는 표면
        
        # 기본 표면: 작업표시줄 위 (화면 최하단)
        # 다양한 해상도 대응을 위해 동적 계산
        screen = QApplication.primaryScreen()
        screen_height = screen.geometry().height()
        screen_width = screen.geometry().width()
        
        # 지면 Y좌표 = 화면 높이 - 캐릭터 높이 - 마진(작업표시줄)
        # 작업표시줄은 보통 40-50px이므로 안전하게 캐릭터 높이만큼 빼고 상단 여유만 확보
        ground_y = screen_height - self.height() - 5  # 5px 여유
        
        # 기본 ground surface 추가
        ground_surface = Surface("ground", ground_y)
        self.add_surface(ground_surface)
        self.current_surface = ground_surface
        
        print(f"[Surface 시스템 초기화]")
        print(f"  화면 해상도: {screen_width}x{screen_height}px")
        print(f"  캐릭터 높이: {self.height()}px")
        print(f"  기본 표면(ground): y={ground_y}px")
        
        # 중력 시스템
        self.velocity_y = 0  # 수직 속도 (중력 영향)
        self.gravity = 0.5   # 중력 가속도
        self.on_ground = False  # 시작할 때는 떨어진 상태 (중력 작동)
        
        # 중력 타이머
        self._gravity_timer = QTimer()
        self._gravity_timer.timeout.connect(self._apply_gravity)
        self._gravity_timer.start(16)  # 16ms = 60fps (30ms에서 개선)

    # 애니메이션 신호 처리
    def on_animation_position_changed(self, new_pos):
        """애니메이션이 위치 변경을 요청 (이동 중에는 멈춤)"""
        # 중력이 적용되도록, X좌표만 갱신하고 Y는 현재 유지
        if not self.is_moving and not self.is_dragging:
            # X만 변경, Y는 현재 값 유지 (중력 효과 보존)
            self.move(new_pos.x(), self.y())
    
    # ====== Surface 시스템 메서드 ======
    def add_surface(self, surface: Surface):
        """새로운 표면 추가 (팝업창 위 등)"""
        self.surfaces.append(surface)
        self.surfaces.sort(key=lambda s: s.y_level)  # Y값으로 정렬
        print(f"[Surface 추가] {surface.name}: y={surface.y_level}px")
    
    def remove_surface(self, surface_name: str):
        """표면 제거 (팝업창 닫힐 때)"""
        self.surfaces = [s for s in self.surfaces if s.name != surface_name]
        print(f"[Surface 제거] {surface_name}")
    
    def get_landing_surface(self, y_pos: int) -> Surface:
        """
        주어진 Y좌표에서 캐릭터가 착지할 표면을 찾음
        캐릭터가 떨어지면서 만나는 첫 번째 표면 반환
        """
        # 현재 Y보다 아래에 있는 표면 중 가장 가까운 것 찾기
        valid_surfaces = [s for s in self.surfaces if s.y_level >= y_pos - self.height()]
        if valid_surfaces:
            return min(valid_surfaces, key=lambda s: s.y_level)
        return None

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
        """애니메이션 폴더 또는 기존 PNG 파일 로드"""
        # 스프라이트 폴더가 있으면 애니메이션 재생
        animation_dir = self.assets_path / action
        if animation_dir.exists() and animation_dir.is_dir():
            # 스프라이트 애니메이션 재생
            self.sprite_animator.play(action, fps=24, loop=True)
        else:
            # 기존 단일 PNG 파일 사용
            path = self.assets_path / f"{action}.png"
            if path.exists():
                pixmap = QPixmap(str(path))
                self.current_pixmap = pixmap  # 원본 이미지 저장 (필수!)
                self.set_pixmap_with_flip(pixmap)
            else:
                print(f"[경고] 애니메이션/이미지 파일 없음: {action}")
    
    def on_sprite_frame_changed(self, pixmap):
        """스프라이트 애니메이터에서 새 프레임 받음"""
        self.current_pixmap = pixmap
        self.set_pixmap_with_flip(pixmap)
    
    def on_animation_finished(self):
        """애니메이션이 종료됨 (loop=False인 경우)"""
        # walk 애니메이션 끝나면 다시 idle로
        if self.current_action.startswith("walk"):
            self.current_action = "idle"
            self.update_render("idle")
    
    def stop_animation(self):
        """현재 실행 중인 스프라이트 애니메이션 중지"""
        self.sprite_animator.stop()

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
            
            # 진행 중인 이동 로직 완전히 중지
            if self.is_moving:
                print(f"[드래그 시작] 이동 중단")
                self._move_timer.stop()
                self.is_moving = False
                self.sprite_animator.stop()
                
                # 현재 감정 상태로 복구
                mood = self.mood_system.decide_emotion()
                emotion = mood["emotion"]
                
                if emotion == "happy":
                    self.current_action = "happy"
                elif emotion == "angry":
                    self.current_action = "angry"
                elif emotion == "bored":
                    self.current_action = "bored"
                else:
                    self.current_action = "idle"
                
                self.update_render(self.current_action)

    def mouseMoveEvent(self, event):
        if self.is_dragging and self.drag_pos:
            self.move(self.pos() + event.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = event.globalPosition().toPoint()
            self.animation_controller.update_base_pos(self.pos())

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.drag_time = 0
        self.drag_pos = None
        
        # 중력 즉시 활성화 (첫 프레임 바로 적용)
        self.on_ground = False
        self.velocity_y = 0
        self._apply_gravity()  # ← 즉시 호출로 지연 제거
        
        # 현재 감정 상태 유지 (walk 애니메이션 아님)
        mood = self.mood_system.decide_emotion()
        emotion = mood["emotion"]
        
        # 떨어지는 동안 현재 감정 애니메이션 표시
        # (나중에 fall 애니메이션으로 교체)
        falling_action = self._get_falling_action(emotion)
        self.current_action = falling_action
        self.update_render(falling_action)
        
        # 호흡 애니메이션 비활성화 (떨어지는 중이므로)
        self.animation_controller.update_base_pos(self.pos())
        self.animation_controller.idle.stop()

    def update_dragging(self):
        if self.is_dragging:
            self.drag_time += 0.1
            self.mood_system.mood["angry"] += 0.02
            self.mood_system.mood["happy"] *= 0.98
            self.update_render("talking")
    
    # 캐릭터 랜덤 이동
    def random_move(self):
        print(f"[random_move 시작] is_dragging={self.is_dragging}, is_moving={self.is_moving}, on_ground={self.on_ground}")
        
        # 떨어지는 중이면 이동 방지
        if not self.on_ground:
            print(f"[아직 공중] 떨어지는 중이므로 이동 스킵")
            return
        
        if self.is_dragging or self.is_moving:
            print(f"[early return] 드래그 중 또는 이동 중 스킵")
            return
        
        if random.random() > 0.8:  # 20% 확률로 이동 스킵
            print(f"[random skip] 확률로 스킵")
            return
        
        mood = self.mood_system.decide_emotion()
        emotion = mood['emotion']
        print(f"[감정] emotion={emotion}")

        # 감정에 따라 움직이는 범위 결정 (X축만: 왼쪽/오른쪽)
        # Y축은 중력에 의해서만 제어됨
        if emotion == "happy":
            dx = random.randint(-100, 100)
            dy = 0  # 수직 이동 없음 (중력만 작용)
        elif emotion == "angry":
            dx = random.randint(-50, 50)
            dy = 0
        elif emotion == "bored":
            dx = random.randint(-30, 30)
            dy = 0
        else:
            dx = random.randint(-200, 200)
            dy = 0

        # 화면 경계 내로 이동 위치 제한
        screen = QApplication.primaryScreen()
        screen_width = screen.geometry().width()
        screen_height = screen.geometry().height()
        
        target_x = self.x() + dx
        target_y = self.y() + dy  # dy = 0이므로 target_y = self.y()
        
        # 경계 체크 및 조정
        if target_x < 0:
            target_x = 0
        elif target_x + self.width() > screen_width:
            target_x = screen_width - self.width()
        
        if target_y < 0:
            target_y = 0
        elif target_y + self.height() > screen_height:
            target_y = screen_height - self.height()
        
        # 실제 이동 거리 재계산
        actual_dx = target_x - self.x()
        actual_dy = target_y - self.y()
        
        print(f"위치 이동: ({self.x()}, {self.y()}) -> ({target_x}, {target_y})")
        print(f"[이동] actual_dx={actual_dx}, actual_dy={actual_dy}, is_flipped={self.is_flipped}")

        # 이동 방향에 따라 좌우반전 결정
        if actual_dx > 0:
            self.is_flipped = True
        elif actual_dx < 0:
            self.is_flipped = False
        
        # 이미지 반전 적용
        if self.current_pixmap is not None:
            self.set_pixmap_with_flip(self.current_pixmap)
        
        # walk 애니메이션 재생 (기분별 폴더 지원 예정임 ㅇㅇㅇ)
        # 우선순위: walk_${emotion}/ → walk/
        walk_animation = self._get_walk_animation(emotion)
        self.current_action = walk_animation
        
        self.sprite_animator.play(walk_animation, fps=24, loop=True)
        
        # 이동 설정 (더 많은 스텝으로 천천히 이동 안바꾸니까 순간이동 하던데 ㅇㅇ..)
        steps = 25
        self.step_x = actual_dx // steps if steps > 0 else 0
        self.step_y = 0  # *** Y축은 절대 변경 안 함 (중력만 제어) ***
        self._remaining_steps = steps
        self._target_x = target_x
        self._target_y = self.y()  # 현재 Y좌표 저장 (변경 없음)
        
        # 이동 시작
        self.is_moving = True
        self.animation_controller.idle.stop()
        # 이동 타이머 간격 증가 (20 → 50ms) //너무 빨리 움직이더라
        self._move_timer.start(50)
    
    def _get_walk_animation(self, emotion):
        """
        기분에 맞는 walk 애니메이션 폴더명 반환
        
        우선순위:
        1. walk_${emotion}/ (예: walk_happy/)
        2. walk/ (기본, idle 표정)
        
        나중에 walk_happy/, walk_angry/ 등이 생기면 자동으로 사용되고, 없으면 기존 walk/ 폴더 사용하게 할겅ㅇ
        """
        emotion_walk = f"walk_{emotion}"
        emotion_walk_path = self.assets_path / emotion_walk
        
        if emotion_walk_path.exists() and emotion_walk_path.is_dir():
            print(f"[walk 애니메이션] {emotion_walk}/ 사용")
            return emotion_walk
        else:
            print(f"[walk 애니메이션] walk/ 사용 (기본)")
            return "walk"
    
    def _get_falling_action(self, emotion):
        """
        떨어지는 중 표시할 애니메이션
        
        우선순위:
        1. fall_${emotion}/ (예: fall_happy/)  - 나중에 구현
        2. fall/                              - 나중에 구현
        3. ${emotion}/                        - 현재 감정 상태 유지 (임시)
        4. idle/                              - 기본
        
        ==== 나중에 fall 애니메이션 추가하려면 ====
        assets/ 아래에
        - fall/
        - fall_happy/
        - fall_angry/
        - fall_bored/
        등의 폴더를 만들면 자동으로 사용됨
        """
        # TODO: fall 애니메이션 구현
        # emotion_fall = f"fall_{emotion}"
        # emotion_fall_path = self.assets_path / emotion_fall
        # if emotion_fall_path.exists():
        #     return emotion_fall
        # else:
        #     fall_path = self.assets_path / "fall"
        #     if fall_path.exists():
        #         return "fall"
        
        # 임시: 현재 감정 상태 유지
        return emotion
    
    def _smooth_moving(self):
        """슬라이딩 이동 애니메이션"""
        if self._remaining_steps <= 0:
            self._move_timer.stop()
            self.is_moving = False
            
            # walk 애니메이션 중지 후 idle로 복귀
            self.sprite_animator.stop()
            self.current_action = "idle"
            self.update_render("idle")
            
            self.animation_controller.update_base_pos(self.pos())
            self.animation_controller.start_idle()
            return

        self.move(self.x() + self.step_x, self.y() + self.step_y)
        self.update()  
        self._remaining_steps -= 1
    
    def _apply_gravity(self):
        """중력 적용 - 캐릭터가 착지할 표면을 찾아 떨어짐"""
        # 드래그 중이거나 이동 중이면 중력 작동 안 함
        if self.is_dragging or self.is_moving:
            self.on_ground = False
            self.velocity_y = 0
            return
        
        current_y = self.y()
        current_surface = self.get_landing_surface(current_y)
        
        # 이미 착지했으면 중력 작동 안 함
        if current_surface and current_y >= current_surface.y_level:
            # 처음 착지했을 때만 처리
            if not self.on_ground:
                self.on_ground = True
                self.velocity_y = 0
                self.current_surface = current_surface
                # 표면에 정확히 맞춤
                self.move(self.x(), int(current_surface.y_level))
                
                # 착지 후 현재 감정 상태로 복구
                mood = self.mood_system.decide_emotion()
                emotion = mood["emotion"]
                
                if emotion == "happy":
                    self.current_action = "happy"
                elif emotion == "angry":
                    self.current_action = "angry"
                elif emotion == "bored":
                    self.current_action = "bored"
                else:
                    self.current_action = "idle"
                
                self.update_render(self.current_action)
            return
        
        # 중력 가속도 적용
        self.on_ground = False
        self.velocity_y += self.gravity
        
        # 속도 제한 (터미널 속도)
        max_velocity = 20
        if self.velocity_y > max_velocity:
            self.velocity_y = max_velocity
        
        # 새 위치 계산
        new_y = current_y + self.velocity_y
        
        # 착지 표면 확인
        landing_surface = self.get_landing_surface(new_y)
        if landing_surface and new_y >= landing_surface.y_level:
            new_y = int(landing_surface.y_level)
            self.on_ground = True
            self.velocity_y = 0
            self.current_surface = landing_surface
        
        self.move(self.x(), int(new_y))