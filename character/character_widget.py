# 캐릭터 위젯을 관리하는 파일
import random
from pathlib import Path
from PyQt6.QtWidgets import QLabel, QApplication
from PyQt6.QtGui import QPixmap, QTransform, QPainter, QPen, QColor, QBrush
from PyQt6.QtCore import QTimer, Qt, QPoint, QRect
from .mood_system import MoodSystem
from .animations import AnimationController
from .sprite_animator import SpriteAnimator

try:
    import pygetwindow as gw
    HAS_PYGETWINDOW = True
except ImportError:
    HAS_PYGETWINDOW = False

# Windows API를 사용한 창 상태 확인
try:
    import ctypes
    from ctypes import windll
    HAS_WINDOWS_API = True
except (ImportError, OSError):
    HAS_WINDOWS_API = False


class Surface:
    """캐릭터가 올라갈 수 있는 표면 (바닥, 팝업창 등)"""
    def __init__(self, name: str, y_level: int, x_min: int = 0, x_max: int = 10000, height: int | None = None, source_key: str | None = None):
        self.name = name           # 표면 이름
        self.y_level = y_level     # 캐릭터가 올라갈 Y좌표
        self.x_min = x_min         # 표면의 X 범위 시작 (좌)
        self.x_max = x_max         # 표면의 X 범위 끝 (우)
        self.height = height       # 표면 높이 (창 테두리 표시용)
        self.source_key = source_key  # 창 추적용 고유 키
    
    def __repr__(self):
        return f"Surface({self.name}, y={self.y_level}, x=[{self.x_min},{self.x_max}], h={self.height})"

class CharacterWidget(QLabel):
    def __init__(self):
        super().__init__()

        # 배경창 투명화
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("AI Desktop Assistant")

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
        
        # 이미지 별도로 축소 대응
        self.setFixedSize(300, 400)
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
        self._self_window_handle = None  # 자기 창 제외용 핸들
        
        # 기본 표면: 작업표시줄 위 (화면 최하단)
        # 다양한 해상도 대응을 위해 동적 계산
        screen = QApplication.primaryScreen()
        screen_height = screen.geometry().height()
        screen_width = screen.geometry().width()
        
        # 지면 Y좌표 = 화면 맨 아래
        ground_y = screen_height  # 화면 완전 바닥
        
        # 기본 ground surface 추가 (화면 전체 너비)
        ground_surface = Surface("ground", ground_y, x_min=0, x_max=screen_width)
        self.add_surface(ground_surface)
        self.current_surface = ground_surface
        
        print(f"[Surface 시스템 초기화]")
        print(f"  화면 해상도: {screen_width}x{screen_height}px")
        print(f"  캐릭터 높이: {self.height()}px")
        print(f"  기본 표면(ground): y={ground_y}px")
        
        # 윈도우 감지 타이머 (500ms마다 창 스캔)
        if HAS_PYGETWINDOW:
            self._window_scan_timer = QTimer()
            self._window_scan_timer.timeout.connect(self._scan_windows)
            self._window_scan_timer.start(500)  # 500ms
            self._last_window_keys = set()  # 이전 스캔의 창 키 추적
        else:
            print("[경고] pygetwindow 미설치 - 창 감지 비활성화")
        
        # 중력 시스템
        self.velocity_y = 0  # 수직 속도 (중력 영향)
        self.gravity = 0.5   # 중력 가속도
        self.on_ground = False  # 시작할 때는 떨어진 상태 (중력 작동)
        
        # 중력 타이머
        self._gravity_timer = QTimer()
        self._gravity_timer.timeout.connect(self._apply_gravity)
        self._gravity_timer.start(16)  # 16ms = 60fps (30ms에서 개선)
        
        # 점프 시스템
        self.jump_force = 15  # 점프 초기 속도 (위로)
        self.can_jump = True  # 점프 가능 여부 (지면에 있을 때만)
        self.is_jumping = False  # 현재 점프 중인지
        
        # 디버그 모드 (collision 박스 및 ground indicator 표시)
        self.show_debug = True  # True면 디버그 표시
        
        # 착지 감지 상태 추적 (로그 중복 제거)
        self._last_surface_name = None  # 이전 착지 표면 이름

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

    def _get_self_window_handle(self):
        if self._self_window_handle is None:
            try:
                self._self_window_handle = int(self.winId())
            except Exception:
                self._self_window_handle = None
        return self._self_window_handle

    def _is_interactive_window(self, window, screen_geometry, debug=False):
        """사용자가 직접 상호작용하는 창만 감지 (VS Code, Chrome 같은 앱)"""
        if not window.title:
            return False

        # 최소화되었으면 제외
        if getattr(window, "isMinimized", False):
            if debug:
                print(f"  ✗ {window.title}: 최소화됨")
            return False

        # 창 크기 검증
        if window.width <= 0 or window.height <= 0:
            if debug:
                print(f"  ✗ {window.title}: 잘못된 크기 ({window.width}x{window.height})")
            return False

        # 너무 작은 창 제외 (1x1, 160x28 등)
        if window.width < 300 or window.height < 200:
            if debug:
                print(f"  ✗ {window.title}: 너무 작음 ({window.width}x{window.height})")
            return False

        # 최소화된 창 좌표 제외 (-32000)
        if window.left <= -30000 or window.top <= -30000:
            if debug:
                print(f"  ✗ {window.title}: 최소화된 좌표 ({window.left}, {window.top})")
            return False

        # ====== 명백한 시스템 창들만 제외 ======
        # 화면 전체를 차지하는 창 제외 (배경/시스템)
        if (window.width >= screen_geometry.width() - 10 and 
            window.height >= screen_geometry.height() - 10):
            if debug:
                print(f"  ✗ {window.title}: 전체 화면 크기 ({window.width}x{window.height})")
            return False

        # 명시적 시스템 창 제외 (정확한 창 이름으로만)
        system_exact_names = [
            "Program Manager",
            "Magnifier", "OnScreen Keyboard",
            "NVIDIA GeForce Overlay",
            "Windows 입력 환경"
        ]
        for exact_name in system_exact_names:
            if window.title.strip() == exact_name or exact_name in window.title and len(window.title) < 50:
                if debug:
                    print(f"  ✗ {window.title}: 시스템 창 ('{exact_name}')")
                return False

        # 유해한 서브스트링만 필터링
        harmful_substrings = [
            "Program Manager", "Magnifier", "OnScreen Keyboard", "NVIDIA",
            "Windows 입력", "Narrator", "Peek", "Widgets", "Cortana", "Action Center"
        ]
        for substring in harmful_substrings:
            if substring.lower() in window.title.lower():
                if debug:
                    print(f"  ✗ {window.title}: 시스템 관련 ('{substring}')")
                return False

        # "설정"은 명시적으로 제외 (설정 앱)
        if window.title.strip() == "설정":
            if debug:
                print(f"  ✗ {window.title}: 설정 앱 정확히")
            return False

        # 화면과 교집합 확인
        window_rect = QRect(window.left, window.top, window.width, window.height)
        if not window_rect.intersects(screen_geometry):
            if debug:
                print(f"  ✗ {window.title}: 화면 범위 밖 ({window.left}, {window.top})")
            return False

        # 작업표시줄 패턴 제외 (높이 매우 낮고 너비가 전체)
        if window.height < 100 and window.width > 2000:
            if debug:
                print(f"  ✗ {window.title}: 작업표시줄 같은 패턴 ({window.width}x{window.height})")
            return False

        if debug:
            print(f"  ✓ 수락: {window.title} ({window.width}x{window.height}) @ ({window.left}, {window.top})")
        return True

    def _window_key(self, window):
        handle = getattr(window, "_hWnd", None)
        if handle is not None:
            return f"hWnd:{handle}"

        return f"{window.title}|{window.left}|{window.top}|{window.width}|{window.height}"

    def _surface_name_for_window(self, window, window_key):
        safe_title = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in window.title).strip()
        if not safe_title:
            safe_title = "window"
        safe_title = safe_title[:24]
        return f"window_{safe_title}_{window_key.replace(':', '_')}"
    
    def get_landing_surface(self, y_pos: int, x_pos: int = None) -> Surface:
        """
        주어진 Y좌표에서 캐릭터가 착지할 표면을 찾음
        X 좌표도 범위 내에 있는지 확인
        
        Args:
            y_pos: 캐릭터 Y 좌표
            x_pos: 캐릭터 X 좌표 (중심)
        """
        if x_pos is None:
            x_pos = self.x()
        
        # 현재 Y보다 아래에 있는 표면 중 가장 가까운 것 찾기
        valid_surfaces = []
        for s in self.surfaces:
            # Y 범위 확인: 캐릭터 하단이 surface 상단 높이에 닿아야 함
            if s.y_level >= y_pos - self.height():
                # X 범위 확인
                char_left = x_pos
                char_right = x_pos + self.width()
                
                # 표면과 캐릭터가 X축에서 겹치는지 확인
                if not (char_right < s.x_min or char_left > s.x_max):
                    valid_surfaces.append(s)
        
        if valid_surfaces:
            # Y 값이 가장 작은 (가장 위에 있는) surface에 착지
            landing = min(valid_surfaces, key=lambda s: s.y_level)
            
            # 착지 표면이 변했을 때만 로그 출력
            if landing.name != self._last_surface_name:
                print(f"[착지!] {self._last_surface_name} -> {landing.name}")
                self._last_surface_name = landing.name
            return landing
        else:
            # 착지 표면이 없어졌을 때 로그 출력
            if self._last_surface_name is not None:
                print(f"[공중] {self._last_surface_name} -> 없음 (떨어지는 중)")
                self._last_surface_name = None
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
        
        # 일관된 크기로 스케일링 (300x400)
        target_width = 300
        target_height = 400
        scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
        # 높이도 맞춰서 조정
        if scaled_pixmap.height() != target_height:
            scaled_pixmap = scaled_pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        
        self.setFixedSize(target_width, target_height)
        if self.is_flipped:
            # 좌우반전
            transform = QTransform()
            transform.scale(-1, 1)  # 가로 반전
            flipped_pixmap = scaled_pixmap.transformed(transform)
            self.setPixmap(flipped_pixmap)
        else:
            self.setPixmap(scaled_pixmap)
        
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
            
            # 드래그 시작 시 hovering 애니메이션 로드 (한 번만)
            self.current_action = "hovering"
            self.update_render("hovering")

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

    # ====== 점프 시스템 ======
    def jump(self):
        """캐릭터 점프 실행 (지면에 있을 때만)"""
        if not self.on_ground:
            print(f"[점프 불가] on_ground={self.on_ground}")
            return
        
        print(f"[점프!] velocity_y 설정: {-self.jump_force}")
        self.is_jumping = True
        self.on_ground = False
        self.velocity_y = -self.jump_force  # 음수 = 위로
        self.can_jump = False
        
        # 점프 애니메이션 (나중에 jump/ 폴더가 생기면 사용)
        # 지금은 현재 감정 상태로 표시
        mood = self.mood_system.decide_emotion()
        emotion = mood["emotion"]
        self.current_action = emotion
        self.update_render(emotion)
        
        # 점프 직후 화면 업데이트 (다음 _apply_gravity 호출까지 기다리지 않음)
        self.move(self.x(), self.y() - 5)  # 즉시 5px 위로 이동
        self.repaint()
    
    # ====== 디버그 렌더링 ======
    def paintEvent(self, event):
        """화면 그리기 (collision box 및 ground indicator)"""
        # 부모의 paintEvent 호출 (이미지 표시)
        super().paintEvent(event)
        
        if not self.show_debug:
            return
        
        # 추가 디버그 그리기
        painter = QPainter(self)
        
        # 1. 빨간색 collision box 그리기
        red_pen = QPen(QColor(255, 0, 0), 3)  # 빨강, 두께 3px
        rect = self.rect()  # 위젯 기준 좌표 (0, 0)에서 width×height
        painter.setPen(red_pen)
        painter.drawRect(rect)
        
        # 2. 초록색 ground indicator 그리기 (지면에 닿아있을 때만)
        if self.on_ground and self.current_surface:
            green_pen = QPen(QColor(0, 255, 0), 3)  # 초록, 두께 3px
            green_brush = QBrush(QColor(0, 255, 0, 100))  # 반투명 초록
            
            # 지면을 나타내는 수평선 (캐릭터 밑 10px 높이의 사각형)
            ground_rect = QRect(0, self.height() - 10, self.width(), 10)
            
            painter.setPen(green_pen)
            painter.setBrush(green_brush)
            painter.drawRect(ground_rect)
        
        # 3. 점프 중일 때 상태 표시
        if self.is_jumping:
            blue_pen = QPen(QColor(0, 150, 255), 2)
            painter.setPen(blue_pen)
            painter.drawEllipse(self.width() // 2 - 20, 10, 40, 40)
        
        # 4. 스크린 좌표 기반 디버그 정보 표시
        # 절대 위치를 스크린 좌표로 표시
        screen_pos = self.mapToGlobal(self.rect().topLeft())
        emotion = self.mood_system.decide_emotion()
        mood_text = emotion.get("emotion", "idle")
        debug_text = f"Pos:({screen_pos.x()},{screen_pos.y()}) Ground:{self.on_ground}"
        
        painter.setPen(QColor(255, 0, 0))
        painter.drawText(10, 20, 200, 30, Qt.AlignmentFlag.AlignLeft, debug_text)
        
        # 5. 현재 Surface 정보 표시
        if self.current_surface:
            surface_text = f"Surface: {self.current_surface.name}"
            painter.drawText(10, 45, 300, 30, Qt.AlignmentFlag.AlignLeft, surface_text)
        
        # 6. 현재 Mood 상태 표시
        painter.setPen(QColor(255, 0, 0))
        mood_display_text = f"Mood: {mood_text}"
        painter.drawText(10, 70, 200, 30, Qt.AlignmentFlag.AlignLeft, mood_display_text)
        
        # 6. Ground surface를 주황색 선으로 표시
        ground_pen = QPen(QColor(255, 165, 0), 4)  # 주황, 두께 4px
        painter.setPen(ground_pen)
        widget_screen_top_left = self.mapToGlobal(QPoint(0, 0))
        
        for surface in self.surfaces:
            if surface.name == "ground":
                # ground는 수평선으로 표시
                ground_y_widget = int(surface.y_level - widget_screen_top_left.y())
                ground_x_min_widget = int(surface.x_min - widget_screen_top_left.x())
                ground_x_max_widget = int(surface.x_max - widget_screen_top_left.x())
                
                # 화면에 보이는 범위만 그리기
                if 0 <= ground_y_widget < self.height():
                    painter.drawLine(ground_x_min_widget, ground_y_widget, ground_x_max_widget, ground_y_widget)
                break
        
        # 7. 감지된 창 Surface의 테두리를 노란색으로 표시
        yellow_pen = QPen(QColor(255, 255, 0), 2)  # 노랑, 두께 2px
        yellow_brush = QBrush(QColor(255, 255, 0, 35))
        painter.setPen(yellow_pen)
        painter.setBrush(yellow_brush)

        for surface in self.surfaces:
            if not surface.name.startswith("window_"):
                continue

            if surface.height is None:
                continue

            surface_rect = QRect(
                int(surface.x_min - widget_screen_top_left.x()),
                int(surface.y_level - widget_screen_top_left.y()),
                int(surface.x_max - surface.x_min),
                int(surface.height),
            )

            if surface_rect.width() > 0 and surface_rect.height() > 0:
                painter.drawRect(surface_rect)
        
        painter.end()

    def update_dragging(self):
        if self.is_dragging:
            self.drag_time += 0.1
            self.mood_system.mood["angry"] += 0.02
            self.mood_system.mood["happy"] *= 0.98
            # hovering 애니메이션은 draq 시작 시에만 로드됨
    
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
        
        # ====== 랜덤 점프 (30% 확률) ======
        if random.random() < 0.3:
            print(f"[랜덤 점프] 점프 실행!")
            self.jump()
            return  # 점프 시 이동하지 않음
        
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
        walk_happy/, walk_angry/ 등이 생기면 자동으로 사용되고, 없으면 기존 walk/ 폴더 사용하게 할겅ㅇ
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
            
            # walk 애니메이션 중지 후 현재 감정 상태로 복귀 (idle 깜빡임 방지)
            self.sprite_animator.stop()
            
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
            
            self.animation_controller.update_base_pos(self.pos())
            self.animation_controller.start_idle()
            return

        self.move(self.x() + self.step_x, self.y() + self.step_y)
        self.update()  
        self._remaining_steps -= 1
    
    def _apply_gravity(self):
        """중력 적용 - 캐릭터가 착지할 표면을 찾아 떨어짐"""
        # 드래그 중이면 중력 작동 안 함 (이동 중은 중력 계속 작용)
        if self.is_dragging:
            self.on_ground = False
            self.velocity_y = 0
            return
        
        current_y = self.y()
        current_x = self.x()
        current_surface = self.get_landing_surface(current_y, current_x)
        
        # 이미 착지했으면 중력 작동 안 함
        # 착지 조건: 캐릭터 하단이 surface 상단보다 크거나 같을 때
        if current_surface and current_y + self.height() >= current_surface.y_level:
            # 처음 착지했을 때만 처리
            if not self.on_ground:
                self.on_ground = True
                self.velocity_y = 0
                self.current_surface = current_surface
                self.is_jumping = False  # 착지 시 점프 상태 해제
                self.can_jump = True  # 다시 점프 가능
                # 표면에 정확히 맞춤 (캐릭터 하단이 surface 상단과 닿아야 함)
                landing_y = int(current_surface.y_level - self.height())
                self.move(self.x(), landing_y)
                
                print(f"[착지!] 표면: {current_surface.name}, surface_y={current_surface.y_level}px -> char_y={landing_y}px, velocity_y={self.velocity_y}")
                
                # 착지 후 현재 감정 상태로 복구 (이동 중이 아닐 때만)
                if not self.is_moving:
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
        
        # 중력 가속도 적용 (이동 중이어도 Y축 중력은 계속 적용)
        self.on_ground = False
        self.velocity_y += self.gravity
        
        # 속도 제한 (터미널 속도)
        max_velocity = 20
        if self.velocity_y > max_velocity:
            self.velocity_y = max_velocity
        
        # 새 위치 계산
        new_y = current_y + self.velocity_y
        
        # 착지 표면 확인 (X 범위도 포함)
        landing_surface = self.get_landing_surface(new_y, current_x)
        if landing_surface and new_y >= landing_surface.y_level:
            # 캐릭터 하단이 surface 상단과 닿아야 함
            new_y = int(landing_surface.y_level - self.height())
            self.on_ground = True
            self.velocity_y = 0
            self.current_surface = landing_surface
            self.is_jumping = False  # 착지 시 점프 상태 해제
            self.can_jump = True  # 다시 점프 가능
        
        self.move(self.x(), int(new_y))
        self.repaint()  # 화면 갱신 (디버그 표시 업데이트)
    
    # ====== 윈도우 감지 시스템 ======
    def _scan_windows(self):
        """활성 창들을 스캔해서 Surface 자동 추가/제거 및 좌표 업데이트"""
        if not HAS_PYGETWINDOW:
            return
        
        try:
            # 현재 활성 창 목록
            windows = gw.getAllWindows()
            current_window_keys = set()
            screen_geometry = QApplication.primaryScreen().geometry()
            self_hwnd = self._get_self_window_handle()

            # 첫 스캔 여부 확인
            first_scan = not hasattr(self, '_first_scan_done')
            
            # 디버그: 첫 스캔만 요약 출력
            if first_scan:
                print("[윈도우 감지] 화면에 보이는 창만 Surface로 등록 (실시간 좌표 업데이트)")
                print(f"  화면 범위: ({screen_geometry.left()}, {screen_geometry.top()}) ~ ({screen_geometry.right()}, {screen_geometry.bottom()})")
                print(f"  ===== 감지된 모든 창 목록 (첫 스캔) =====")
                for i, w in enumerate(windows):
                    print(f"    [{i}] {w.title} | {w.width}x{w.height} @ ({w.left}, {w.top})")
                print(f"  =====================================")
                self._first_scan_done = True
            
            # Window 객체를 key로 빠르게 찾을 수 있도록 맵 생성
            window_map = {}  # window_key -> window 객체
            
            for window in windows:
                window_handle = getattr(window, "_hWnd", None)

                # 자기 창은 제외
                if self_hwnd is not None and window_handle == self_hwnd:
                    continue

                # 화면에 실제로 보이는 창만 사용 (첫 스캔에만 debug 로그 출력)
                if not self._is_interactive_window(window, screen_geometry, debug=first_scan):
                    continue
                
                window_key = self._window_key(window)
                current_window_keys.add(window_key)
                window_map[window_key] = window
                
                # 새로운 창이면 Surface 추가
                if window_key not in self._last_window_keys:
                    surface_name = self._surface_name_for_window(window, window_key)
                    surface_y = window.top
                    surface_x_min = window.left
                    surface_x_max = window.left + window.width
                    visible_height = min(window.height, screen_geometry.bottom() - window.top + 1)
                    
                    new_surface = Surface(
                        surface_name, 
                        surface_y, 
                        x_min=surface_x_min, 
                        x_max=surface_x_max,
                        height=visible_height,
                        source_key=window_key,
                    )
                    self.add_surface(new_surface)
                    print(f"[창 감지] {surface_name}")
                    print(f"  위치: ({window.left}, {window.top}) ~ ({window.left + window.width}, {window.top})")
            
            # 기존 window surface의 좌표 업데이트 (창을 움직이거나 크기 변경했을 때)
            for surface in self.surfaces[:]:
                if not surface.name.startswith("window_"):
                    continue
                
                if surface.source_key in window_map:
                    window = window_map[surface.source_key]
                    # 좌표 업데이트
                    surface.y_level = window.top
                    surface.x_min = window.left
                    surface.x_max = window.left + window.width
                    surface.height = min(window.height, screen_geometry.bottom() - window.top + 1)
                else:
                    # 창이 없어졌으면 Surface 제거
                    self.remove_surface(surface.name)
                    print(f"[창 제거] {surface.name}")
            
            # 닫힌 창 제거 (ground는 제외)
            removed = self._last_window_keys - current_window_keys
            for window_key in removed:
                for surface in self.surfaces[:]:
                    if surface.name.startswith("window_") and surface.source_key == window_key:
                        self.remove_surface(surface.name)
                        print(f"[창 제거] {surface.name}")
                        break
            
            self._last_window_keys = current_window_keys
            
        except Exception as e:
            print(f"[윈도우 감지 오류] {e}")