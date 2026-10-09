# 캐릭터 위젯을 관리하는 파일
import random
import shutil
import json
import os
import threading
import time
import math
import inspect
from app_logging import log_event, log_throttled, new_trace_id
from pathlib import Path
from PyQt6.QtWidgets import QLabel, QApplication, QFileIconProvider, QMenu
from PyQt6.QtGui import QPixmap, QTransform, QPainter, QPen, QColor, QBrush, QIcon, QFont, QCursor, QShortcut, QKeySequence, QContextMenuEvent, QRegion
from PyQt6.QtCore import QTimer, Qt, QPoint, QRect, QMimeData, QUrl, QFileInfo, pyqtSignal, pyqtSlot
from perception.controller import PerceptionController
from perception.receiver import QtPerceptionReceiver
from .emotion_assets import resolve_animation_asset
from .mood_system import MoodSystem
from .animations import AnimationController
from .sprite_animator import SpriteAnimator
from .rig_state import RigAnimator
from .dialogue_system import DialogueSystem, QuickDialoguePresets
from .russell_emotion_dialog import RussellEmotionDialog
from .personality_system import PersonalitySystem
from .sandbox_manager import SandboxManager
from .rps_game import RpsGameOverlay
from .motion_options import DEFAULT_CHARACTER_OPTIONS, normalize_character_options, random_movement_scale
from .manual_control import ManualControl, SPRITE_DISPLAY_EMOTIONS


# Context 모듈 import
try:
    from context.active_window_classifier import (
        get_active_window_info,
        call_gemini,
        extract_dialogue,
        build_gemini_prompt
    )
    HAS_CONTEXT = True
except ImportError:
    print("[경고] context 모듈 import 실패 - 자동 대사 생성 비활성화")
    HAS_CONTEXT = False

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


def _with_log_context(callback, *args, log_context=None, **kwargs):
    """Keep existing injected providers and test doubles with older signatures."""
    try:
        parameters = inspect.signature(callback).parameters.values()
        if log_context and log_context.get('trace_id') and any(p.name == 'log_context' or p.kind == p.VAR_KEYWORD for p in parameters):
            kwargs['log_context'] = log_context
    except (ValueError, TypeError):
        pass
    return callback(*args, **kwargs)


class Surface:
    """캐릭터가 올라갈 수 있는 표면 (바닥, 팝업창 등)"""
    def __init__(self, name: str, y_level: int, x_min: int = 0, x_max: int = 10000, height: int | None = None, source_key: str | None = None, window_title: str | None = None):
        self.name = name           # 표면 이름
        self.y_level = y_level     # 캐릭터가 올라갈 Y좌표
        self.x_min = x_min         # 표면의 X 범위 시작 (좌)
        self.x_max = x_max         # 표면의 X 범위 끝 (우)
        self.height = height       # 표면 높이 (창 테두리 표시용)
        self.source_key = source_key  # 창 추적용 고유 키
        self.window_title = window_title
    
    def __repr__(self):
        return f"Surface({self.name}, y={self.y_level}, x=[{self.x_min},{self.x_max}], h={self.height})"

class CharacterWidget(QLabel):
    # 신호들
    show_ai_response = pyqtSignal(str)  # AI 응답 신호
    automatic_response_ready = pyqtSignal(object)
    CHARACTER_WIDTH = 150
    CHARACTER_HEIGHT = 200
    PET_MIN_SAMPLE_INTERVAL = 0.1
    PET_MIN_DISTANCE = 6

    # ====== 감정별 캐릭터 반응 영역 ======
    # 감정별 표정, 걷기 애니메이션, 랜덤 이동 범위는 여기서 관리한다.
    EMOTION_RESPONSE_PROFILES = {
        "joy": {"animation": "happy", "move_range": 100},
        "delight": {"animation": "happy", "move_range": 100},
        "excitement": {"animation": "happy", "move_range": 100},
        "interest": {"animation": "happy", "move_range": 100},
        "contentment": {"animation": "happy", "move_range": 80},
        "calm": {"animation": "idle", "move_range": 60},
        "peaceful": {"animation": "idle", "move_range": 60},
        "anger": {"animation": "angry", "move_range": 50},
        "disgust": {"animation": "angry", "move_range": 50},
        "fear": {"animation": "scared", "move_range": 70},
        "anxiety": {"animation": "scared", "move_range": 70},
        "sadness": {"animation": "sad", "move_range": 40},
        "melancholy": {"animation": "sad", "move_range": 40},
        "despair": {"animation": "sad", "move_range": 30},
        "happy": {"animation": "happy", "move_range": 100},
        "angry": {"animation": "angry", "move_range": 50},
        "scared": {"animation": "scared", "move_range": 70},
        "sad": {"animation": "sad", "move_range": 40},
        "bored": {"animation": "idle", "move_range": 30},
        "neutral": {"animation": "idle", "move_range": 200},
        "idle": {"animation": "idle", "move_range": 200},
    }
    
    def __init__(
        self,
        screen_width=None,
        screen_height=None,
        personality_preset=None,
        on_show_perception_console=None,
        on_show_log_window=None,
        on_close_log_window=None,
        on_rps_command=None,
        on_show_settings=None,
        character_options=None,
    ):
        super().__init__()
        options = normalize_character_options(character_options)
        self.size_percent = options['size_percent']
        self.movement_speed = options['movement_speed']
        self.jump_height = options['jump_height']
        self.movement_range_extra_percent = options['movement_range_extra_percent']
        self.show_debug = options['show_hitboxes']

        # MediaPipe 프로세스는 main.py가 관리하고, 캐릭터는 창 표시만 요청한다.
        self._show_perception_console_callback = on_show_perception_console
        self._show_log_window_callback = on_show_log_window
        self._close_log_window_callback = on_close_log_window
        self._rps_command_callback = on_rps_command
        self._show_settings_callback = on_show_settings
        self.rps_game = None

        # 배경창 투명화
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setWindowTitle("AI Desktop Assistant")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 기본 설정
        self.personality_system = PersonalitySystem(personality_preset or "Russell (기본)")
        self.mood_system = MoodSystem(self.personality_system)  # 성격을 mood_system에 전달
        self.russell_dialog = None
        self.current_action = "idle"
        self.drag_pos = None
        self.current_pixmap = None
        self.is_flipped = False
        self.assets_path = Path(__file__).resolve().parent.parent / "assets"
        
        # 드래그 앤 드롭 시스템 (초기화)
        self.held_items = []  # 들고있는 파일/폴더 리스트 (여러 개 가능)
        self.held_items_icons = {}  # 아이템별 아이콘 캐시
        self.setAcceptDrops(True)  # 드롭 이벤트 수용

        # 디버그 단축키: 다이얼로그 직접 열기
        self._russell_shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        self._russell_shortcut.activated.connect(self.show_russell_dialog)
        self._ball_shortcut = QShortcut(QKeySequence("Ctrl+Shift+B"), self)
        self._ball_shortcut.activated.connect(self.select_ball)
        self._menu_shortcut = QShortcut(QKeySequence("Shift+F10"), self)
        self._menu_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._menu_shortcut.activated.connect(
            lambda: self._show_context_menu(
                self.mapToGlobal(self.rect().center()), include_dialogue=True))

        self.sandbox_manager = SandboxManager(self)
        
        # 아이템 반환 타이머 (순차 배치용)
        self._release_timer = None
        self._remaining_items_to_release = []  # 반환 대기 중인 아이템
        
        # 캐릭터 아이템 폴더 생성
        self.character_items_path = self.assets_path.parent / "character_items"
        self.character_items_path.mkdir(parents=True, exist_ok=True)
        print(f"[캐릭터 아이템 폴더] {self.character_items_path}")
        
        # 이벤트 트래킹
        self.last_interaction_time = 0  # 마지막 상호작용 시간
        self._last_character_interaction_time = time.monotonic()
        self.idle_counter = 0  # idle 카운터 (neglected 감지용)
        self._last_autonomous_event_time = 0.0 #캐릭터 혼자 있을때 자동 이벤트 발생 시간
        self._autonomous_event_cooldown = random.uniform(10.0, 60.0)
        self.drag_speed = 0  # 드래그 속도
        self.last_window_count = 0  # 이전 창 개수 (급격한 변화 감지용)
        self.window_change_count = 0  # 창 변화 횟수
        
        # 스프라이트 애니메이터 초기화
        self.rig_view = None
        self._rig_manual_action = None
        self._rig_preferred_yaw = 0
        self._rig_fallback_pending = False
        self._rig_overlay_key = None
        self._character_closing = False
        self.setFixedSize(*self._scaled_character_size())
        self._initialize_character_renderer()
        
        # 이미지 별도로 축소 대응
        self.setFixedSize(*self._scaled_character_size())
        self.update_render("idle")
        
        # 애니메이션 컨트롤러
        self.animation_controller = AnimationController(self.pos())
        self.animation_controller.position_changed.connect(self.on_animation_position_changed)
        self.animation_controller.start_idle()

        # 타이머들
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_mood)
        self.timer.start(1000)

        self.emotion_timer = QTimer()
        self.emotion_timer.timeout.connect(self.advance_emotion)
        self.emotion_timer.start(100)

        self.move_timer = QTimer()
        self.move_timer.timeout.connect(self.random_move)
        self.move_timer.start(3000)  # 1초 → 3초 (걷기 빈도 감소)

        # 드래그 관련
        self.is_dragging = False
        self.drag_time = 0
        self._drag_velocity_x = 0  # 드래그 중 X축 속도 저장
        self._drag_velocity_y = 0  # 드래그 중 Y축 속도 저장
        self.drag_timer = QTimer()
        self.drag_timer.timeout.connect(self.update_dragging)
        self.drag_timer.start(100)

        # 이동 타이머 미리 생성
        self._move_timer = QTimer()
        self._move_timer.timeout.connect(self._smooth_moving)
        self._movement_x = float(self.x())
        self._walk_last_time = None
        self._chase_last_time = None

        self.is_moving = False
        self._pet_last_position = None
        self._pet_last_time = 0.0
        self._cursor_over_character = False
        self._last_pet_time = 0.0
        self._pet_log_count = 0
        self._pet_total_count = 0
        self._pet_log_reward = 0.0
        self._pet_session_logged = False
        self._pet_refusal_session_logged = False
        
        # ====== Surface 시스템 (바닥, 팝업창 등) ======
        self.surfaces = []  # 캐릭터가 올라갈 수 있는 모든 표면
        self.current_surface = None  # 현재 캐릭터가 위에 있는 표면
        self._self_window_handle = None  # 자기 창 제외용 핸들
        
        # 캐릭터는 작업표시줄 영역을 포함한 화면 전체를 사용한다.
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geometry = screen.geometry()
            available_width = screen_geometry.width()
            available_height = screen_geometry.height()
        else:
            available_width = screen_width or 1920
            available_height = screen_height or 1080

        if screen_width is None:
            screen_width = available_width
        else:
            screen_width = min(screen_width, available_width)

        if screen_height is None:
            screen_height = available_height
        else:
            screen_height = min(screen_height, available_height)
        
        # 커스텀 해상도 저장 (나중에 경계 확인 시 사용)
        self.custom_screen_width = screen_width
        self.custom_screen_height = screen_height
        self._screen_origin = screen_geometry.topLeft() if screen is not None else QPoint(0, 0)
        self._screen_auto_width = screen_width >= available_width
        self._screen_auto_height = screen_height >= available_height
        print(f"[해상도 초기화] custom: {self.custom_screen_width}x{self.custom_screen_height}px")
        
        # 지면 Y좌표 = 화면 맨 아래 (커스텀 해상도 사용)
        ground_y = self._screen_origin.y() + screen_height
        
        # 기본 ground surface 추가 (화면 전체 너비)
        ground_surface = Surface("ground", ground_y, x_min=self._screen_origin.x(),
                                 x_max=self._screen_origin.x() + screen_width)
        self.add_surface(ground_surface)
        self.current_surface = ground_surface
        
        print(f"[Surface 시스템 초기화]")
        print(f"  설정된 해상도: {screen_width}x{screen_height}px")
        print(f"  캐릭터 높이: {self.height()}px")
        print(f"  기본 표면(ground): y={ground_y}px, x=[0, {screen_width}]px")
        
        # 윈도우 감지 타이머 (500ms마다 창 스캔)
        if HAS_PYGETWINDOW:
            self._window_scan_timer = QTimer()
            self._window_scan_timer.timeout.connect(self._scan_windows)
            self._window_scan_timer.start(500)  # 500ms
            self._last_window_keys = set()  # 이전 스캔의 창 키 추적
        else:
            print("[경고] pygetwindow 미설치 - 창 감지 비활성화")
        
        # 중력 및 이동 시스템
        self.velocity_x = 0  # 수평 속도 (드래그에서 나옴)
        self.velocity_y = 0  # 수직 속도 (중력 영향)
        self.gravity = 0.5   # 중력 가속도
        self._gravity_last_time = time.monotonic()
        self._physics_position_y = None
        self._physics_position_x = None
        self.bounce_damping = 0.6  # 경계 충돌 시 속도 감소 (0.6 = 60% 유지)
        self.friction = 0.98  # 공기 저항 (0.98 = 2% 감소)
        self.on_ground = False  # 시작할 때는 떨어진 상태 (중력 작동)
        
        # 중력 타이머
        self._gravity_timer = QTimer()
        self._gravity_timer.timeout.connect(self._apply_gravity)
        self._gravity_timer.start(16)  # 16ms = 60fps (30ms에서 개선)
        
        # 점프 시스템
        self.jump_force = math.sqrt(2 * self.gravity * self.jump_height)
        self._jump_physics_y = None
        self._jump_apex_y = None
        self.can_jump = True  # 점프 가능 여부 (지면에 있을 때만)
        self.is_jumping = False  # 현재 점프 중인지
        
        # 디버그 모드 (collision 박스 및 ground indicator 표시)
        # The visibility setting is shared by both sprite and native renderers.
        
        # 착지 감지 상태 추적 (로그 중복 제제거)
        self._last_surface_name = None  # 이전 착지 표면 이름
        
        # ====== 컨텍스트 모니터링 & 자동 대사 생성 ======
        self.gemini_config = {}
        self.last_detected_activity = None  # 마지막 감지한 활동
        self.last_dialogue_time = 0  # 마지막 대사 시간
        self.dialogue_cooldown = 5  # 수동 대화 쿨다운: 5초
        self.last_auto_dialogue_time = 0  # 마지막 자동 대사 시간
        self.auto_dialogue_cooldown = 20  # 자동 감지 쿨다운: 20초 (API 제한 방지)
        
        if HAS_CONTEXT:
            # Gemini 설정 파일 로드
            self._load_gemini_config()
            
            # 활성 창 모니터링 타이머 (30초마다 체크, 120초 쿨다운으로 최대 2분마다 요청)
            self._activity_monitor_timer = QTimer()
            self._activity_monitor_timer.timeout.connect(self._on_activity_monitor)
            self._activity_monitor_timer.start(30000)  # 30초마다 체크
            
            print("[자동 대사 생성 시스템 초기화 완료]")
        else:
            print("[자동 대사 생성 시스템 비활성화]")
        
        
        
        # ====== 대화 시스템 초기화 ======
        self.dialogue_system = DialogueSystem(self)
        self._automatic_request_generation = 0
        self._automatic_request_active = False
        print("[대화 시스템 초기화 완료]")
        
        # 신호 연결
        self.show_ai_response.connect(self._show_automatic_ai_response)
        self.automatic_response_ready.connect(
            self._finish_automatic_response, Qt.ConnectionType.QueuedConnection)
        if hasattr(self.dialogue_system.tts, "speaking_changed"):
            self.dialogue_system.tts.speaking_changed.connect(self._on_speaking_changed)

        # ====== 외부 감정/동작 인식 수신 ======
        self._pending_user_greeting_until = None
        self._greeting_retry_timer = QTimer(self)
        self._greeting_retry_timer.setInterval(100)
        self._greeting_retry_timer.timeout.connect(self._try_user_greeting)
        self.manual_control = ManualControl(self, self)
        # 모델 종류와 무관하게 공통 perception 이벤트만 캐릭터 반응으로 전달한다.
        self.perception_controller = PerceptionController(
            mood_system=self.mood_system,
            on_dialogue=self._show_perception_dialogue,
            on_greeting=self._request_user_greeting,
            on_speech=self.dialogue_system.submit_speech,
            on_speech_with_context=self.dialogue_system.submit_speech_with_context,
            on_dialogue_with_context=lambda text, context: self._show_perception_dialogue(text, log_context=context),
        )
        self.dialogue_system.tts.speaking_changed.connect(self.perception_controller.set_speech_suppressed)
        self.dialogue_system.user_input_received.connect(lambda text, source: self._mark_character_interaction())
        self.perception_receiver = QtPerceptionReceiver(parent=self)
        # TCP 콜백은 백그라운드 스레드에서 실행되므로 UI 처리는 Qt 메인 스레드에 예약한다.
        self.perception_receiver.event_received.connect(
            self._handle_perception_payload,
            Qt.ConnectionType.QueuedConnection,
        )
        self.perception_receiver.status_changed.connect(self._on_perception_status)
        self.perception_receiver.error_occurred.connect(self._on_perception_error)
        if not self.perception_receiver.start():
            print(
                "[외부 인식 수신기 비활성화] "
                f"{self.perception_receiver.startup_error or '알 수 없는 오류'}"
            )
    
    def _initialize_character_renderer(self):
        """Keep the host window and its events; replace only character drawing."""
        if os.environ.get("CLOUDY_RENDERER", "rig").lower() != "sprite":
            view = None
            try:
                from .cloudy_rig_view import CloudyRigView
                view = CloudyRigView(parent=self)
                view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                view.setGeometry(self.rect())
                view.set_external_physics(True)
                view.set_debug_painter(self._paint_debug if self.show_debug else None)
                self.rig_view = view
                self.sprite_animator = RigAnimator(view, parent=self)
                self.sprite_animator.animation_finished.connect(self.on_animation_finished)
                view.failed.connect(self._queue_sprite_fallback)
                view.pose_bounds_changed.connect(self._align_grounded_pose, Qt.ConnectionType.DirectConnection)
                view.show()
                return
            except Exception as exc:
                log_event('renderer.initialization_failed', '캐릭터 렌더러 초기화 실패', category='오류', level='ERROR', error=str(exc), fallback='PNG')
                print(f"[Cloudy renderer] PNG fallback: {exc}")
                if view is not None:
                    view.hide()
                    view.deleteLater()
                self.rig_view = None
        self._install_sprite_animator()

    def _install_sprite_animator(self):
        self.sprite_animator = SpriteAnimator(self.assets_path)
        self.sprite_animator.frame_changed.connect(self.on_sprite_frame_changed)
        self.sprite_animator.animation_finished.connect(self.on_animation_finished)

    def _queue_sprite_fallback(self, reason):
        if (self.rig_view is not None and not self._rig_fallback_pending
                and not self._character_closing):
            self._rig_fallback_pending = True
            QTimer.singleShot(0, lambda: self._use_sprite_renderer(reason))

    def _use_sprite_renderer(self, reason):
        """A failed GL context must leave dragging/dialogue and old assets usable."""
        if self.rig_view is None or self._character_closing:
            return
        print(f"[Cloudy renderer] PNG fallback: {reason}")
        log_event('renderer.fallback', 'PNG 렌더러로 전환', category='캐릭터 상태', level='WARNING', reason=str(reason),
                  action=getattr(self, 'current_action', None), emotion=getattr(self, 'current_emotion', None))
        old_view = self.rig_view
        self.sprite_animator.release()
        self.sprite_animator.deleteLater()
        self.rig_view = None
        old_view.hide()
        old_view.deleteLater()
        self._rig_manual_action = None
        self._rig_fallback_pending = False
        self._install_sprite_animator()
        mood = self.mood_system.decide_emotion()
        if self.is_dragging:
            self.current_action = "hovering"
        elif self.is_moving or getattr(self, "_ball_chasing", False):
            self.current_action = self._get_walk_animation(mood["emotion"])
        else:
            self.current_action = self._get_emotion_animation(mood["emotion"])
        self.update_render(self.current_action)

    def _on_speaking_changed(self, speaking):
        if self.rig_view is not None:
            self.sprite_animator.set_speaking(speaking)

    def _refresh_rig_overlay(self):
        if self.rig_view is not None:
            key = (tuple(self.held_items), self.is_flipped)
            if key == self._rig_overlay_key:
                return
            self._rig_overlay_key = key
            if not self.held_items:
                self.rig_view.set_overlay_pixmap(QPixmap())
                return
            overlay = QPixmap(self.CHARACTER_WIDTH, self.CHARACTER_HEIGHT)
            overlay.fill(Qt.GlobalColor.transparent)
            if self.held_items:
                overlay = self._overlay_icons_on_character(overlay)
            self.rig_view.set_overlay_pixmap(overlay)

    def _play_rig_action(self, action):
        if self.rig_view is None or self.is_dragging or not self.on_ground:
            return
        self._move_timer.stop()
        self.is_moving = False
        self._ball_chasing = False
        self.animation_controller.idle.stop()
        self._rig_manual_action = None if action == "idle" else action
        self.current_action = action
        self.sprite_animator.set_yaw(self._idle_rig_yaw())
        self.sprite_animator.set_emotion(self.mood_system.decide_emotion()["emotion"])
        self.sprite_animator.play(action, loop=action != "wave")
        if action == "idle":
            self.update_action(self.mood_system.decide_emotion())

    def _set_rig_direction(self, yaw):
        if self.rig_view is None:
            return
        self._rig_preferred_yaw = yaw
        self._rig_direction_explicit = True
        self.is_flipped = yaw > 0
        self.sprite_animator.set_yaw(yaw)
        self._refresh_rig_overlay()

    def _idle_rig_yaw(self):
        """Keep the last facing direction unless the user chose an idle yaw."""
        preferred = self._rig_preferred_yaw
        if (getattr(self, '_rig_direction_explicit', False)
                or preferred != 0 or self._manual_control_active()):
            return preferred
        return self.sprite_animator.yaw

    def _rig_landed(self):
        if self.rig_view is not None:
            self.rig_view.set_jump_active(False)
            phase_setter = getattr(self.rig_view, 'set_physics_jump_phase', None)
            if phase_setter is not None:
                phase_setter(None, landing=getattr(self, '_authored_jump_landing', False))
            self._rig_manual_action = None
            self.current_action = "land"
            self.sprite_animator.play("land", loop=False)
        else:
            self.update_action(self.mood_system.decide_emotion())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "rig_view", None) is not None:
            self.rig_view.setGeometry(self.rect())

    def _get_screen_dimensions(self):
        """Use logical Qt dimensions, refreshing resolution and scaling changes."""
        geometry = self._get_screen_geometry()
        return geometry.width(), geometry.height()

    def _get_screen_geometry(self):
        """Full desktop surface (including taskbar), with its real screen origin."""
        # Windowless callers can supply dimensions without needing a QApplication.
        if not hasattr(self, '_screen_origin'):
            return QRect(0, 0, *self._get_screen_dimensions())
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self._screen_origin = geometry.topLeft()
            width = (geometry.width() if self._screen_auto_width else
                     min(self.custom_screen_width, geometry.width()))
            height = (geometry.height() if self._screen_auto_height else
                      min(self.custom_screen_height, geometry.height()))
        else:
            width, height = self.custom_screen_width, self.custom_screen_height
        geometry = QRect(self._screen_origin.x(), self._screen_origin.y(), width, height)
        for surface in getattr(self, 'surfaces', ()):
            if surface.name == 'ground':
                surface.y_level = geometry.y() + geometry.height()
                surface.x_min = geometry.x()
                surface.x_max = geometry.x() + geometry.width()
        return geometry

    @pyqtSlot(object)
    def _handle_perception_payload(self, payload):
        if self.rps_game is not None and self.rps_game.isVisible():
            self.rps_game.handle_payload(payload)
        try:
            self.perception_controller.handle_payload(payload)
        except ValueError as exc:
            print(f"[외부 인식 이벤트 무시] {exc}")

    @pyqtSlot(str)
    def _on_perception_status(self, status):
        print(f"[외부 인식 수신기] {status}")

    @pyqtSlot(str)
    def _on_perception_error(self, message):
        print(f"[외부 인식 수신기 오류] {message}")

    def _show_perception_dialogue(self, text, *, log_context=None):
        context = log_context or {'trace_id': getattr(getattr(self, 'perception_controller', None), 'current_trace_id', None), 'source': 'perception'}
        if CharacterWidget._dialogue_is_busy(self):
            log_event('perception.dialogue_blocked', '인식 반응 대화 대기 중', category='사용자 인식', trace_id=context.get('trace_id'), text=text, reason='conversation_busy')
            return False
        _with_log_context(self.dialogue_system.show_dialogue, text, duration=3000, use_narration=False, log_context=context)
        log_event('perception.dialogue_shown', '인식 반응 말풍선 표시', category='사용자 인식', trace_id=context.get('trace_id'), text=text)
        return True

    def _dialogue_is_busy(self):
        dialogue = getattr(self, 'dialogue_system', None)
        if dialogue is None:
            return False
        checker = getattr(dialogue, 'is_conversation_busy', None)
        if checker is not None:
            return bool(checker())
        return bool(getattr(dialogue, 'is_ai_responding', False)
                    or getattr(dialogue, 'pending_inputs', ())
                    or getattr(dialogue, '_tts_busy', False)
                    or getattr(dialogue, '_speaking', False)
                    or time.monotonic() < getattr(dialogue, '_response_hold_until', 0))

    @pyqtSlot(str)
    def _show_automatic_ai_response(self, text):
        if not getattr(self, '_character_closing', False) and not CharacterWidget._dialogue_is_busy(self):
            self.dialogue_system.show_automatic_response(text)
        else:
            log_event('dialogue.automatic_signal_discarded', '자동 대사 표시 생략', category='대화·AI', text=text,
                      reason='closing' if getattr(self, '_character_closing', False) else 'conversation_busy')

    def _request_user_greeting(self):
        self._greeting_log_context = {'trace_id': getattr(getattr(self, 'perception_controller', None), 'current_trace_id', None), 'source': 'greeting'}
        if self._character_closing or self._manual_control_active():
            return
        self._pending_user_greeting_until = time.monotonic() + 10.0
        if not self._try_user_greeting():
            print('[사용자 인사] 캐릭터 동작이 끝난 뒤 인사하도록 보류함')
            log_event('perception.greeting_deferred', '인사 동작 보류', category='사용자 인식', trace_id=self._greeting_log_context.get('trace_id'), deadline=self._pending_user_greeting_until)
            self._greeting_retry_timer.start()

    def _try_user_greeting(self):
        deadline = self._pending_user_greeting_until
        if deadline is None:
            return False
        if self._character_closing or time.monotonic() > deadline:
            self._pending_user_greeting_until = None
            self._greeting_retry_timer.stop()
            if not self._character_closing:
                print('[사용자 인사] 보류 시간 초과: 인사를 취소함')
                log_event('perception.greeting_cancelled', '보류 시간 초과', category='사용자 인식', trace_id=getattr(self, '_greeting_log_context', {}).get('trace_id'))
            return False
        if (self.is_dragging or self.is_jumping or not self.on_ground
                or getattr(self, '_ball_session_active', False)
                or (self.rps_game is not None and self.rps_game.isVisible())
                or (self.rig_view is not None and self.sprite_animator.is_playing
                    and self.sprite_animator.current_action in {'land', 'wave'})):
            return False
        self._pending_user_greeting_until = None
        self._greeting_retry_timer.stop()
        self._mark_character_interaction()
        if self.rig_view is not None:
            self._play_rig_action('wave')
        else:
            self._move_timer.stop()
            self.is_moving = False
            self._ball_chasing = False
            self.animation_controller.idle.stop()
            # Legacy PNG packs may not contain a wave animation.
            if (self.assets_path / 'wave').is_dir():
                self.current_action = 'wave'
                self.sprite_animator.play('wave', fps=24, loop=False)
        _with_log_context(self._show_perception_dialogue, '안녕! 👋', log_context=getattr(self, '_greeting_log_context', None))
        print('[사용자 인사] 캐릭터 인사 재생')
        return True

    def _shutdown_character_renderer(self):
        """Stop host callbacks before releasing the drawing backend."""
        if not getattr(self, '_character_closing', False):
            log_event('character.shutdown', '캐릭터 종료 시작', category='캐릭터 상태',
                      action=getattr(self, 'current_action', None), moving=getattr(self, 'is_moving', False))
            CharacterWidget._finish_pet_log(self, 'shutdown')
            for context in getattr(self, '_automatic_log_contexts', {}).values():
                log_event('dialogue.automatic_cancelled', '앱 종료로 자동 응답 무효화', category='대화·AI', trace_id=context.get('trace_id'))
            getattr(self, '_automatic_log_contexts', {}).clear()
        self._character_closing = True
        self._automatic_request_generation = getattr(self, '_automatic_request_generation', 0) + 1
        self._automatic_request_active = False
        if hasattr(self, 'manual_control'):
            self.manual_control.shutdown()
        if hasattr(getattr(self, 'dialogue_system', None), 'shutdown'):
            self.dialogue_system.shutdown()
        self._pending_user_greeting_until = None
        for name in ("timer", "emotion_timer", "move_timer", "drag_timer", "_move_timer",
                     "_gravity_timer", "_window_scan_timer", "_activity_monitor_timer",
                     "_release_timer", "_greeting_retry_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        self.animation_controller.stop()
        if self.rig_view is not None:
            self.sprite_animator.release()
        else:
            self.sprite_animator.stop()

    def closeEvent(self, event):
        hand_overlay = getattr(self, 'hand_overlay', None)
        if hand_overlay is not None:
            hand_overlay.stop()
        self._shutdown_character_renderer()
        self.dialogue_system.tts.close()
        if self.rps_game is not None:
            self.rps_game.close()
        # 수신 스레드와 8765 포트를 먼저 정리해야 앱을 바로 다시 실행할 수 있다.
        if hasattr(self, "perception_receiver"):
            self.perception_receiver.stop()
        if self._close_log_window_callback is not None:
            self._close_log_window_callback()
        super().closeEvent(event)

    # 애니메이션 신호 처리
    def on_animation_position_changed(self, new_pos):
        """애니메이션이 위치 변경을 요청 (이동 중에는 멈춤)"""
        # 중력이 적용되도록, X좌표만 갱신하고 Y는 현재 유지
        if not self._manual_control_active() and not self.is_moving and not self.is_dragging and not getattr(self, '_ball_chasing', False):
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
            "Windows 입력 환경",
            "XBOX"
        ]
        for exact_name in system_exact_names:
            if window.title.strip() == exact_name or exact_name in window.title and len(window.title) < 50:
                if debug:
                    print(f"  ✗ {window.title}: 시스템 창 ('{exact_name}')")
                return False

        # 유해한 서브스트링만 필터링
        harmful_substrings = [
            "Program Manager", "Magnifier", "OnScreen Keyboard", "NVIDIA",
            "Windows 입력", "Narrator", "Peek", "Widgets", "Cortana", "Action Center",
            "Xbox Game Bar", "Game Bar"
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
    
    def _physics_body_rect(self):
        """Use the painted body, excluding transparent host padding and effects."""
        measure = getattr(self, '_character_visual_rect', None)
        body = measure() if measure is not None else QRect(0, 0, self.width(), self.height())
        return body if not body.isEmpty() else QRect(0, 0, self.width(), self.height())

    def _align_grounded_pose(self):
        """Keep rendered feet on their existing support in the same paint frame.

        Only an established, unmoved surface may compensate for pose changes.
        New windows, lost support and flight remain entirely under gravity.
        """
        if (not getattr(self, 'on_ground', False) or getattr(self, 'is_dragging', False)
                or getattr(self, 'is_jumping', False) or getattr(self, '_character_closing', False)
                or getattr(self, 'velocity_y', 0) != 0):
            return
        standing = getattr(self, 'current_surface', None)
        if standing is None or standing not in getattr(self, 'surfaces', ()):
            return
        previous_level = getattr(self, '_grounded_surface_level', None)
        previous_bottom = getattr(self, '_grounded_body_bottom', None)
        if (standing.y_level != previous_level or previous_bottom is None
                or abs(self.y() + previous_bottom - standing.y_level) > 1):
            return
        body = self._physics_body_rect()
        if (self.x() + body.x() + body.width() <= standing.x_min
                or self.x() + body.x() >= standing.x_max):
            return
        body_bottom = body.y() + body.height()
        aligned_y = standing.y_level - body_bottom
        self._grounded_body_bottom = body_bottom
        self._physics_position_y = float(aligned_y)
        if aligned_y != self.y():
            self.move(self.x(), aligned_y)
            dialogue = getattr(self, 'dialogue_system', None)
            if dialogue is not None:
                dialogue.update_dialogue_position()

    def get_landing_surface(self, y_pos: int, x_pos: int = None) -> Surface | None:
        """Find the nearest surface at or below the feet, without snapping to it."""
        if x_pos is None:
            x_pos = self.x()
        body = self._physics_body_rect()
        foot_y = y_pos + body.y() + body.height()
        left = x_pos + body.x()
        right = left + body.width()
        valid_surfaces = [
            surface for surface in self.surfaces
            if surface.y_level >= foot_y
            and right > surface.x_min and left < surface.x_max
        ]
        return min(valid_surfaces, key=lambda surface: surface.y_level, default=None)

    # ====== 자동 대사 생성 시스템 ======
    def _load_gemini_config(self):
        """Gemini 설정 파일 로드"""
        from .ai_settings import load_ai_settings
        try:
            self.gemini_config = load_ai_settings()
            print(f"[Gemini 설정 로드] API 키: {'설정됨' if self.gemini_config.get('api_key') else '미설정'}")
        except Exception as e:
            print(f"[오류] Gemini 설정 로드 실패: {e}")
    
    def _on_activity_monitor(self):
        """Start ambient work only when the user conversation has released the UI."""
        reason = ('context_unavailable' if not HAS_CONTEXT else 'api_key_missing' if not self.gemini_config.get('api_key')
                  else 'closing' if getattr(self, '_character_closing', False)
                  else 'conversation_busy' if CharacterWidget._dialogue_is_busy(self)
                  else 'request_in_flight' if getattr(self, '_automatic_request_active', False) else None)
        if reason:
            log_throttled('dialogue.automatic_skipped', '자동 대화 요청 대기', category='대화·AI', key=reason, reason=reason)
            return
        if time.time() - self.last_auto_dialogue_time < self.auto_dialogue_cooldown:
            log_throttled('dialogue.automatic_skipped', '자동 대화 재요청 대기', category='대화·AI', key='cooldown', reason='cooldown', remaining=self.auto_dialogue_cooldown - (time.time() - self.last_auto_dialogue_time))
            return

        # Capture character/config state on the Qt thread. A new user input epoch
        # invalidates this result even if its conversation has already finished.
        self._automatic_request_generation += 1
        generation = self._automatic_request_generation
        epoch = self.dialogue_system.user_input_epoch
        emotion = self.mood_system.get_emotion_description_for_prompt()
        tone = self.mood_system.get_emotion_tone_instructions()
        self._automatic_request_active = True
        context = {'trace_id': new_trace_id('ambient'), 'source': 'activity', 'generation': generation, 'input_epoch': epoch}
        if not hasattr(self, '_automatic_log_contexts'):
            self._automatic_log_contexts = {}
        self._automatic_log_contexts[generation] = context
        log_event('dialogue.automatic_started', '자동 대화 관측 시작', category='대화·AI', trace_id=context['trace_id'], generation=generation, input_epoch=epoch)
        thread = threading.Thread(
            target=self._check_active_window_async,
            args=(generation, epoch, dict(self.gemini_config), emotion, tone, context),
            daemon=True, name=f'character-activity-{generation}')
        thread.start()
    
    def _check_active_window_async(self, generation, input_epoch, config,
                                   emotion_description, tone_instruction, log_context=None):
        """A worker collects activity; all UI/result state is handled by a Qt slot."""
        info = None
        dialogue_text = None
        request_time = None
        context = log_context or {'trace_id': new_trace_id('ambient'), 'source': 'activity'}
        try:
            # 활성 창 정보 수집
            info = get_active_window_info()
            if not info:
                log_event('dialogue.automatic_no_window', '활성 창 정보 없음', category='대화·AI', trace_id=context['trace_id'])
                return
            
            # 프로세스 이름으로 활동 분류
            process = info.get('process', '').lower()
            title = info.get('title', '')
            
            # 활동 카테고리 결정
            category = "unknown"
            if 'chrome' in process or 'firefox' in process or 'edge' in process:
                category = "web"
            elif 'vscode' in process or 'code' in process:
                category = "development"
            elif 'game' in process or 'steam' in process or 'unity' in process:
                category = "game"
            elif 'discord' in process or 'slack' in process or 'telegram' in process:
                category = "communication"
            else:
                category = "work"
            
            # 감정 정보가 포함된 향상된 프롬프트 생성
            prompt = (
                f"입력 정보:\n"
                f"- 활동 분류: {category}\n"
                f"- 프로세스: {process}\n"
                f"- 창 제목: {title}\n"
                f"\n【 캐릭터 감정 상태 】\n"
                f"{emotion_description}\n"
                f"\n【 말투 지침 】\n"
                f"{tone_instruction}\n"
                f"\n위의 감정 상태와 말투 지침을 고려하여 활동에 대한 자연스러운 한두 문장의 반응을 생성하세요."
            )
            log_event('dialogue.automatic_prompt', '활동 기반 Gemini 요청', category='대화·AI', trace_id=context['trace_id'], activity=info, activity_category=category, prompt=prompt, generation=generation, input_epoch=input_epoch)
            
            request_time = time.time()
            response = _with_log_context(call_gemini, prompt, config, log_context=context)
            log_event('dialogue.automatic_response', '활동 기반 응답 수신', category='대화·AI', trace_id=context['trace_id'], response=response,
                      outcome='failed' if not response or DialogueSystem._is_error_response(response) else 'received')
            
            if response:
                # The same decoder handles plain, JSON and fenced JSON output.
                dialogue_text = _with_log_context(self.dialogue_system._process_gemini_response, response, log_context=context)
        
        except Exception as e:
            log_event('dialogue.automatic_failed', '활동 모니터링 실패', category='오류', level='ERROR', trace_id=context['trace_id'], error=str(e))
            print(f"[오류] 활동 모니터링 실패: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if not getattr(self, '_character_closing', False):
                self.automatic_response_ready.emit(
                    (generation, input_epoch, dialogue_text, info, request_time))
            else:
                log_event('dialogue.automatic_discarded', '종료 후 자동 응답 폐기', category='대화·AI', trace_id=context['trace_id'], reason='closing')

    @pyqtSlot(object)
    def _finish_automatic_response(self, result):
        generation, epoch, text, info, request_time = result
        context = getattr(self, '_automatic_log_contexts', {}).pop(generation, {'trace_id': None, 'source': 'activity'})
        if (getattr(self, '_character_closing', False)
                or generation != self._automatic_request_generation):
            log_event('dialogue.automatic_discarded', '이전 자동 응답 폐기', category='대화·AI', trace_id=context.get('trace_id'), generation=generation, reason='closing_or_generation_changed')
            return
        self._automatic_request_active = False
        if request_time is not None:
            self.last_auto_dialogue_time = request_time
        if info:
            self.last_detected_activity = info
        if text:
            shown = _with_log_context(self.dialogue_system.show_automatic_response, text, expected_input_epoch=epoch, log_context=context)
            log_event('dialogue.automatic_finished', '자동 대화 처리 완료', category='대화·AI', trace_id=context.get('trace_id'), shown=bool(shown), input_epoch=epoch, current_input_epoch=self.dialogue_system.user_input_epoch)
        else:
            log_event('dialogue.automatic_finished', '표시할 자동 대화 없음', category='대화·AI', trace_id=context.get('trace_id'), shown=False, reason='empty_response_or_no_window')
    
    def _convert_error_to_dialogue(self, error_response: str) -> str:
        """Gemini 에러를 캐릭터 대사로 변환"""
        if "429" in error_response or "Too Many Requests" in error_response:
            return "너무 많은 요청이 들어왔어요... 잠시 쉬고 있을게요! 😅"
        elif "401" in error_response or "Unauthorized" in error_response:
            return "API 키가 잘못된 것 같아요... 설정을 확인해주시겠어요?"
        elif "403" in error_response or "Forbidden" in error_response:
            return "접근 권한이 없네요... 설정을 다시 확인해주세요."
        elif "500" in error_response or "Internal" in error_response:
            return "AI 서버에 문제가 생겼어요... 잠시 후에 다시 시도해주세요."
        else:
            return f"음... 뭔가 문제가 생겼어요. 😔 ({error_response[:30]}...)"

    def get_system_idle_time(self):
        """시스템 전체 유휴 시간(초)을 반환합니다. Windows only."""
        if not HAS_WINDOWS_API:
            return 0
        
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
            
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            windll.user32.GetLastInputInfo(ctypes.byref(lii))
            
            # 마지막 입력 이후의 시간(ms) 계산
            idle_ms = windll.kernel32.GetTickCount() - lii.dwTime
            return idle_ms / 1000.0  # 초 단위로 반환
        except Exception as e:
            print(f"[경고] 시스템 유휴 시간 감지 실패: {e}")
            return 0

    def get_character_idle_time(self) -> float:
        """캐릭터 자체와 마지막으로 상호작용한 뒤의 시간을 반환한다."""
        return max(0.0, time.monotonic() - self._last_character_interaction_time)

    def _mark_character_interaction(self) -> None:
        """캐릭터 상호작용 시 전용 방치 시간을 초기화한다."""
        self._last_character_interaction_time = time.monotonic()
        self.idle_counter = 0

    def update_mood(self):
        if self.is_dragging or self.is_moving:
            if self.rig_view is not None:
                self.update_action(self.mood_system.decide_emotion())
            return

        character_idle_time = self.get_character_idle_time()
        self.mood_system.update_idle_pressure(character_idle_time)
        self.idle_counter += 1
        self.mood_system.decay()
        self._maybe_run_autonomous_event(character_idle_time)
        mood = self.mood_system.decide_emotion()
        
        # 감정 상태 변경 감지 및 로깅
        has_changed, old_emotion, new_emotion = self.mood_system.has_emotion_changed()
        if has_changed:
            print(f"\n✨ [감정 변화] {old_emotion} → {new_emotion}")
            log_event('mood.snapshot', '감정 변화 후 상태', category='캐릭터 상태',
                      reason='emotion_changed', old_emotion=old_emotion, new_emotion=new_emotion,
                      state=getattr(self.mood_system, 'get_russell_state', lambda: {})(), final_emotion=self.mood_system.decide_emotion(),
                      formatted_state=self.mood_system.get_formatted_mood_log())
            print()
        
        self.update_action(mood)

    def _maybe_run_autonomous_event(self, idle_seconds: float) -> None:
        """상호작용이 없을 때 낮은 빈도로 캐릭터 혼자 이벤트를 발생시킨다."""
        if self._manual_control_active():
            return
        now = time.monotonic()
        if idle_seconds < 15.0:
            return
        if now - self._last_autonomous_event_time < self._autonomous_event_cooldown:
            return
        if self._cursor_over_character or self.is_dragging or self.is_moving:
            return
        if CharacterWidget._dialogue_is_busy(self):
            return
        if random.random() > 0.06:
            return

        emotion = self.mood_system.decide_emotion()["emotion"]
        if emotion in {"anger", "disgust", "fear", "anxiety", "sadness", "despair"}:
            event_name = "self_rest"
            self.mood_system.on_self_rest()
        elif emotion in {"joy", "delight", "excitement", "interest", "contentment"}:
            event_name = "self_play"
            self.mood_system.on_self_play()
        else:
            event_name = "self_curiosity"
            self.mood_system.on_self_curiosity()

        self._last_autonomous_event_time = now
        self._autonomous_event_cooldown = random.uniform(10.0, 60.0)
        print(
            f"[자율 이벤트] {event_name} | 방치시간={idle_seconds:.1f}초 | "
            f"다음 쿨다운={self._autonomous_event_cooldown:.1f}초"
        )

    def advance_emotion(self):
        """감정 좌표를 짧은 간격으로 목표값에 부드럽게 접근시킨다."""
        if self.is_dragging or self.is_moving:
            if self.rig_view is not None:
                self.update_action(self.mood_system.decide_emotion())
            return
        self.mood_system.advance_emotion(0.1)
        self.update_action(self.mood_system.decide_emotion())


    # 행동 결정
    @classmethod
    def _get_emotion_response_profile(cls, emotion):
        return cls.EMOTION_RESPONSE_PROFILES.get(
            emotion,
            cls.EMOTION_RESPONSE_PROFILES["neutral"],
        )

    def _get_emotion_animation(self, emotion):
        """논리 감정을 실제로 존재하는 표정 애니메이션으로 변환한다."""
        return self._get_emotion_response_profile(self._get_sprite_display_emotion(emotion))["animation"]

    def _get_sprite_display_emotion(self, emotion):
        override = getattr(getattr(self, 'manual_control', None), 'display_emotion', None)
        return SPRITE_DISPLAY_EMOTIONS[override] if override else emotion

    def update_action(self, mood):
        """Russell 기반 17개 감정을 애니메이션에 매핑"""
        if self.rig_view is not None:
            self.sprite_animator.set_emotion(mood["emotion"])
            self._refresh_rig_overlay()
            busy = (getattr(self, "is_dragging", False)
                    or getattr(self, "is_moving", False)
                    or getattr(self, "_ball_chasing", False)
                    or getattr(self, "is_jumping", False)
                    or not getattr(self, "on_ground", True)
                    or self._rig_manual_action is not None
                    or (self.sprite_animator.current_action == "land"
                        and self.sprite_animator.is_playing))
            if not busy:
                self.current_action = "idle"
                self.sprite_animator.set_yaw(self._idle_rig_yaw())
                self.sprite_animator.play("idle")
            return
        action = self._animation_for_emotion(self._get_sprite_display_emotion(mood["emotion"]))
        if self._manual_control_active() and (self.is_moving or self.is_jumping or not self.on_ground
                or self.current_action in {'wave', 'thinking', 'sleep'}):
            return
        if action == self.current_action:
            return
        self.current_action = action
        self.render()

    @staticmethod
    def _animation_for_emotion(emotion):
        """Russell/OCC 감정명을 실제 에셋 폴더명으로 변환한다."""
        profile = CharacterWidget._get_emotion_response_profile(emotion)
        animation = profile["animation"]
        return "fear" if animation == "scared" else animation

    # 출력
    def render(self):
        self.update_render(self.current_action)

    def update_render(self, action):
        """애니메이션 폴더 또는 기존 PNG 파일 로드"""
        # develop의 scared 이름과 기존 fear 에셋을 모두 지원한다.
        if self.rig_view is not None:
            self.rig_view.set_jump_active(bool(getattr(self, 'is_jumping', False)))
            if action in {"hovering", "fall", "jump"}:
                self._rig_manual_action = None
            if action.startswith("walk"):
                self._rig_manual_action = None
                self.sprite_animator.set_direction(self.is_flipped)
            self.sprite_animator.play(action, fps=24, loop=action not in {"wave", "land"})
            self._refresh_rig_overlay()
            return
        action = resolve_animation_asset(self.assets_path, action)
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
                if pixmap.isNull():
                    log_event('sprite.image_invalid', '캐릭터 PNG 읽기 실패', category='오류', level='ERROR', path=str(path), action=action)
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
        log_event('character.animation_finished', '캐릭터 동작 종료', category='캐릭터 상태', action=getattr(self.sprite_animator, 'current_action', None))
        # walk 애니메이션 끝나면 다시 idle로
        if self.rig_view is not None:
            if self.sprite_animator.current_action in {"wave", "land"}:
                self._rig_manual_action = None
                mood = self.mood_system.decide_emotion()
                if self.on_ground and (self.is_moving or getattr(self, "_ball_chasing", False)):
                    self.current_action = self._get_walk_animation(mood["emotion"])
                    self.update_render(self.current_action)
                else:
                    self.update_action(mood)
            return
        if self.current_action == 'wave':
            self.current_action = 'idle'
            self.update_action(self.mood_system.decide_emotion())
        elif self.current_action.startswith("walk"):
            self.current_action = "idle"
            self.update_render("idle")
    
    def stop_animation(self):
        """현재 실행 중인 스프라이트 애니메이션 중지"""
        self.sprite_animator.stop()

    #좌우 반전 
    def set_pixmap_with_flip(self, pixmap):
        """좌우반전 상태에 따라 이미지 설정"""
        if self.rig_view is not None:
            if self.sprite_animator.current_action == "walk":
                self.sprite_animator.set_direction(self.is_flipped)
            self._refresh_rig_overlay()
            return
        if pixmap is None:
            print("pixmap: NONE!")
            return
        
        # Compose in the original host canvas, then scale the complete frame.
        target_width = self.CHARACTER_WIDTH
        target_height = self.CHARACTER_HEIGHT
        scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
        # 높이도 맞춰서 조정
        if scaled_pixmap.height() != target_height:
            scaled_pixmap = scaled_pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        
        if self.is_flipped:
            # 좌우반전
            transform = QTransform()
            transform.scale(-1, 1)  # 가로 반전
            flipped_pixmap = scaled_pixmap.transformed(transform)
            final_pixmap = flipped_pixmap
        else:
            final_pixmap = scaled_pixmap
        
        # 아이콘 오버레이 (들고있는 아이템이 있을 때)
        if self.held_items:
            final_pixmap = self._overlay_icons_on_character(final_pixmap)
        
        canvas = QPixmap(target_width, target_height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, final_pixmap)
        painter.end()
        self.setPixmap(canvas.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        self.repaint()

    def _get_item_icon(self, file_path):
        """파일/폴더의 아이콘을 QPixmap으로 반환"""
        try:
            icon_provider = QFileIconProvider()
            file_info = QFileInfo(file_path)
            icon = icon_provider.icon(file_info)
            
            # QIcon을 QPixmap으로 변환 (64x64 크기)
            icon_pixmap = icon.pixmap(64, 64)
            
            # 아이콘이 없으면 기본 파일 아이콘 사용
            if icon_pixmap.isNull():
                icon = icon_provider.icon(QFileIconProvider.IconType.File)
                icon_pixmap = icon.pixmap(64, 64)
            
            return icon_pixmap
        except Exception as e:
            print(f"[오류] 아이콘 가져오기 실패: {e}")
            return None

    def _decorate_icon_with_ownership(self, icon_pixmap):
        """아이콘에 캐릭터 소유권 표현 추가 (금색 테두리 + 광환)"""
        if icon_pixmap is None or icon_pixmap.isNull():
            return icon_pixmap
        
        try:
            # 투명 배경으로 더 큰 캔버스 생성 (테두리/광환용)
            decorated = QPixmap(80, 80)
            decorated.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(decorated)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # 광환 (흐린 노란색 원형)
            glow_color = QColor(255, 215, 0, 80)  # 금색, 반투명
            painter.setBrush(QBrush(glow_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(8, 8, 64, 64)
            
            # 아이콘 중앙에 배치
            painter.drawPixmap(8, 8, icon_pixmap)
            
            # 금색 테두리 (소유권 표시)
            painter.setPen(QPen(QColor(255, 215, 0), 3))  # 금색 3px 테두리
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(8, 8, 64, 64)
            
            # 코너에 별 모양 배지 (캐릭터 소유 표시)
            star_color = QColor(255, 255, 0)  # 노란색 별
            painter.setBrush(QBrush(star_color))
            painter.setPen(Qt.PenStyle.NoPen)
            
            # 우상단 별 (작은 원으로 표현)
            painter.drawEllipse(66, 6, 12, 12)
            
            painter.end()
            
            return decorated
        except Exception as e:
            print(f"[오류] 아이콘 소유권 표현 추가 실패: {e}")
            return icon_pixmap

    def _overlay_icons_on_character(self, character_pixmap):
        """캐릭터 이미지 위에 여러 아이콘을 오버레이 (소유권 표현)"""
        if not self.held_items:
            return character_pixmap
        
        try:
            # 원본 pixmap 복사 (투명 배경이 아닌 원래 이미지 유지)
            result = character_pixmap.copy()
            
            # 기존 캐릭터 이미지 위에 아이콘 추가
            painter = QPainter(result)
            
            # 여러 아이콘을 순차적으로 표시 (최대 3개, 겹쳐서 배치)
            base_icon_x = 90 if not self.is_flipped else 10  # 우측 또는 좌측
            base_icon_y = 50  # 위쪽
            
            for idx, item_path in enumerate(self.held_items[:3]):  # 최대 3개만 표시
                if idx >= 3:
                    break
                
                # 각 아이콘 위치 설정 (약간 겹쳐서 배치)
                offset_x = idx * 10
                offset_y = idx * 8
                icon_x = base_icon_x + offset_x
                icon_y = base_icon_y + offset_y
                
                try:
                    icon_pixmap = self._get_item_icon(item_path)
                    if icon_pixmap is not None and not icon_pixmap.isNull():
                        decorated_icon = self._decorate_icon_with_ownership(icon_pixmap)
                        painter.drawPixmap(icon_x, icon_y, decorated_icon)
                except Exception as e:
                    print(f"[경고] 아이콘 표시 실패: {e}")
            
            # 아이템이 3개 이상이면 숫자 표시
            if len(self.held_items) > 3:
                painter.setPen(QPen(QColor(255, 255, 0), 2))
                font = QFont()
                font.setPointSize(12)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(base_icon_x + 30, base_icon_y + 30,
                                f"+{len(self.held_items) - 3}")
            
            painter.end()
            
            return result
        except Exception as e:
            print(f"[오류] 아이콘 오버레이 실패: {e}")
            return character_pixmap

    def contextMenuEvent(self, event):
        # The mouse path opens on press; do not open it again on release.
        menu = getattr(self, "_context_menu", None)
        if menu is None or not menu.isVisible():
            global_pos = event.globalPos()
            if event.reason() == QContextMenuEvent.Reason.Keyboard or global_pos.x() < 0:
                global_pos = self.mapToGlobal(self.rect().center())
            self._show_context_menu(global_pos, include_dialogue=True)
        event.accept()

    # 클릭 이벤트
    def mousePressEvent(self, event):
        print(f"[mousePressEvent] button={event.button()} pos={event.globalPosition().toPoint()}")
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint(), include_dialogue=True)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            sandbox_response = self.sandbox_manager.use_selected_item()
            if sandbox_response:
                self.dialogue_system.show_dialogue(sandbox_response, duration=2500)
                event.accept()
                return

            self.mood_system.on_click()
            self._mark_character_interaction()
            self.drag_pos = event.globalPosition().toPoint()
            print(f"[클릭 이벤트 발생]")
            log_event('mood.snapshot', '클릭 후 감정 상태', category='캐릭터 상태', reason='click',
                      state=getattr(self.mood_system, 'get_russell_state', lambda: {})(), final_emotion=self.mood_system.decide_emotion(),
                      formatted_state=self.mood_system.get_formatted_mood_log())
            

            self.is_dragging = True
            self.drag_time = 0
            self._drag_trace_id = new_trace_id('drag')
            self._drag_start_position = (self.x(), self.y())
            log_event('character.drag_started', '드래그 시작', category='캐릭터 상태', trace_id=self._drag_trace_id, position=self._drag_start_position)
            
            # 진행 중인 이동 로직 완전히 중지
            if self.is_moving:
                print(f"[드래그 시작] 이동 중단")
                self._move_timer.stop()
                self.is_moving = False
                log_event('character.movement_stopped', '드래그로 이동 중단', category='캐릭터 상태', reason='drag_started', position=(self.x(), self.y()))
                self.sprite_animator.stop()
            
            # 드래그 시작 시 hovering 애니메이션 로드 (한 번만)
            self.current_action = "hovering"
            self.update_render("hovering")

    def mouseMoveEvent(self, event):
        if self.is_dragging and self.drag_pos:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self.drag_pos
            
            # 드래그 속도 계산 (픽셀 거리)
            drag_distance = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
            self.drag_speed = drag_distance
            
            # X, Y 속도 분리 저장 (나중에 던질 때 사용)
            self._drag_velocity_x = delta.x()
            self._drag_velocity_y = delta.y()
            
            # 빠른 드래그 감지 (100px 이상) → on_drag_hard 트리거
            if drag_distance > 100:
                self.mood_system.on_drag_hard()
                print(f"[on_drag_hard 트리거] 속도={drag_distance:.1f}px, vx={delta.x():.1f}, vy={delta.y():.1f}")
            
            # 캐릭터를 이동하되, 화면 범위 내로 제한
            new_pos = self.pos() + delta
            self.move(new_pos)
            self._clamp_position_to_screen()
            self.drag_pos = current_pos
            self.animation_controller.update_base_pos(self.pos())
            
            # 말풍선 위치 업데이트 (캐릭터를 따라가게 함)
            self.dialogue_system.update_dialogue_position()
            return

        current_pos = event.globalPosition().toPoint()
        current_time = time.monotonic()
        if self._pet_last_position is None:
            self._pet_last_position = current_pos
            self._pet_last_time = current_time
            return

        elapsed = current_time - self._pet_last_time
        if elapsed < self.PET_MIN_SAMPLE_INTERVAL:
            # 너무 빠른 이벤트는 기준점을 갱신하지 않아 이동량을 합산한다.
            return
        if elapsed > 0.5:
            CharacterWidget._finish_pet_log(self, 'input_gap')
            # 오래 끊긴 뒤의 이동은 새로운 쓰다듬기 시작점으로 취급한다.
            self._pet_last_position = current_pos
            self._pet_last_time = current_time
            self._pet_session_logged = False
            self._pet_refusal_session_logged = False
            return

        distance = (current_pos - self._pet_last_position).manhattanLength()
        movement_speed = distance / elapsed
        self._pet_last_position = current_pos
        self._pet_last_time = current_time
        if distance < self.PET_MIN_DISTANCE:
            return

        if self.mood_system.should_refuse_pet():
            if not self._pet_refusal_session_logged:
                print("[쓰다듬기 거부] 감정이 너무 나빠 접촉을 거부함")
                self._pet_refusal_session_logged = True
            return

        reward = self.mood_system.on_pet(movement_speed, elapsed)
        if not getattr(self, '_pet_trace_id', None):
            self._pet_trace_id = new_trace_id('pet')
            self._pet_log_start_count = self._pet_log_count
            self._pet_log_start_reward = self._pet_log_reward
            log_event('character.pet_started', '쓰다듬기 시작', category='캐릭터 상태', trace_id=self._pet_trace_id, speed=movement_speed)
        self._last_pet_time = current_time
        self._mark_character_interaction()
        self._pet_log_count += 1
        self._pet_total_count += 1
        self._pet_log_reward += reward
        if not self._pet_session_logged:
            state = self.mood_system.get_russell_state()
            emotion = self.mood_system.decide_emotion()
            print(
                f"[쓰다듬기] 감지 중 | 구간횟수={self._pet_log_count}, "
                f"총횟수={self._pet_total_count}, "
                f"속도={movement_speed:.1f}px/s, "
                f"보상={self._pet_log_reward:.4f}, "
                f"현재 V={state['valence']:+.3f}, "
                f"현재 A={state['arousal']:+.3f}, "
                f"목표 V={self.mood_system._target_valence:+.3f}, "
                f"목표 A={self.mood_system._target_arousal:+.3f}, "
                f"감정={emotion['emotion']}"
            )
            self._pet_session_logged = True

    def _finish_pet_log(self, reason):
        trace_id = getattr(self, '_pet_trace_id', None)
        if trace_id:
            log_event('character.pet_finished', '쓰다듬기 구간 종료', category='캐릭터 상태', trace_id=trace_id,
                      reason=reason, count=getattr(self, '_pet_log_count', 0) - getattr(self, '_pet_log_start_count', 0),
                      reward=getattr(self, '_pet_log_reward', 0) - getattr(self, '_pet_log_start_reward', 0),
                      total_count=getattr(self, '_pet_total_count', 0), mood=CharacterWidget._log_mood_snapshot(self))
            self._pet_trace_id = None

    def _log_mood_snapshot(self):
        mood = getattr(self, 'mood_system', None)
        if mood is None:
            return None
        try:
            return {'state': mood.get_russell_state(), 'emotion': mood.decide_emotion(),
                    'target': {'valence': getattr(mood, '_target_valence', None), 'arousal': getattr(mood, '_target_arousal', None)},
                    'occ': {str(getattr(key, 'value', key)): value for key, value in getattr(mood, 'occ_intensities', {}).items()}}
        except Exception as exc:
            return {'unavailable': str(exc)}

    def enterEvent(self, event):
        self._cursor_over_character = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        CharacterWidget._finish_pet_log(self, 'cursor_left')
        self._cursor_over_character = False
        self._pet_last_position = None
        self._pet_session_logged = False
        self._pet_refusal_session_logged = False
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        drag_duration = getattr(self, 'drag_time', 0)
        was_dragging = getattr(self, 'is_dragging', False)
        self.is_dragging = False
        self.is_jumping = False
        self._jump_physics_y = None
        self._physics_position_y = None
        self._physics_position_x = None
        if hasattr(self, '_gravity_last_time'):
            self._gravity_last_time = time.monotonic()
        phase_setter = getattr(self.rig_view, 'set_physics_jump_phase', None)
        if phase_setter is not None:
            phase_setter(None)
        self._chase_last_time = None
        self.drag_time = 0
        self.drag_pos = None
        self._mark_character_interaction()
        
        # 드래그 속도를 velocity로 변환 (관성 적용)
        # 저장된 드래그 속도가 있으면 그것을 사용, 없으면 0
        self.velocity_x = getattr(self, '_drag_velocity_x', 0) * 0.5  # 0.5배 감쇠
        self.velocity_y = getattr(self, '_drag_velocity_y', 0) * 0.5
        if was_dragging:
            log_event('character.drag_finished', '드래그 종료', category='캐릭터 상태', trace_id=getattr(self, '_drag_trace_id', None), duration=drag_duration,
                      start_position=getattr(self, '_drag_start_position', None), release_position=(self.x(), self.y()), velocity_x=self.velocity_x, velocity_y=self.velocity_y, mood=CharacterWidget._log_mood_snapshot(self))
        
        # 드래그 속도 저장 변수 초기화
        self._drag_velocity_x = 0
        self._drag_velocity_y = 0
        
        # 캐릭터가 화면 범위 내에 있는지 확인 (드래그 후 강제 조정)
        self._clamp_position_to_screen()
        
        # 중력 즉시 활성화 (첫 프레임 바로 적용)
        self.on_ground = False
        self._apply_gravity()  # ← 즉시 호출로 지연 제거
        
        # 현재 감정 상태 유지 (walk 애니메이션 아님)
        mood = self.mood_system.decide_emotion()
        emotion = mood["emotion"]
        
        # 떨어지는 동안 현재 감정 애니메이션 표시
        # (나중에 fall 애니메이션으로 교체)
        falling_action = self._get_falling_action(emotion)
        if self.rig_view is None or not self.on_ground:
            self.current_action = falling_action
            self.update_render(falling_action)
        
        # 호흡 애니메이션 비활성화 (떨어지는 중이므로)
        self.animation_controller.update_base_pos(self.pos())
        self.animation_controller.idle.stop()
    
    # 작업 브랜치의 메뉴 기능은 develop의 공 기능 메서드와 분리해 둔다.
    def show_rps_game(self):
        if self.rps_game is None:
            self.rps_game = RpsGameOverlay(self._rps_command_callback, self)
        self._mark_character_interaction()
        self.rps_game.start_game()
        self.dialogue_system.update_dialogue_position()
        self.rps_game.raise_()

    def end_rps_game(self):
        if self.rps_game is not None:
            self.rps_game.close()
        self.dialogue_system.update_dialogue_position()

    def show_perception_console(self):
        """백그라운드에서 실행 중인 사용자 인식 창의 표시를 요청한다."""
        if self._show_perception_console_callback is None:
            print("[사용자 인식 콘솔] 실행 관리자가 연결되지 않았습니다.")
            return
        try:
            if not self._show_perception_console_callback():
                print("[사용자 인식 콘솔] 창을 표시하지 못했습니다.")
        except Exception as exc:
            # 메뉴 콜백 오류가 캐릭터의 Qt 이벤트 루프까지 종료시키지 않게 한다.
            print(f"[사용자 인식 콘솔 오류] {exc}")

    def show_log_window(self):
        """별도 로그창을 표시하고 앞으로 가져온다."""
        if self._show_log_window_callback is None:
            print("[로그창] 로그창 관리자가 연결되지 않았습니다.")
            return
        self._show_log_window_callback()
    
    #컨텍스트 메뉴 캐릭터 우클릭시 동작
    def _show_context_menu(self, global_pos, include_dialogue: bool = False):
        print(f"[컨텍스트 메뉴] 위치: {global_pos.x()}, {global_pos.y()}")
        menu = QMenu(self)
        log_action = menu.addAction("로그창 보기")
        log_action.triggered.connect(self.show_log_window)
        settings_action = menu.addAction("설정")
        settings_action.triggered.connect(self.show_settings)
        console_action = menu.addAction("사용자인식 콘솔")
        console_action.triggered.connect(self.show_perception_console)
        show_action = menu.addAction("감정 판단 근거 보기")
        show_action.triggered.connect(self.show_russell_dialog)
        menu.addSeparator()
        ball_action = menu.addAction("공 꺼내기")
        ball_action.triggered.connect(self.select_ball)
        if include_dialogue:
            talk_action = menu.addAction("대화하기")
            talk_action.triggered.connect(self.dialogue_system.open_input_dialog)
        if getattr(self.dialogue_system, '_last_failed_input', None) is not None:
            retry_action = menu.addAction("실패한 대화 다시 보내기")
            retry_action.triggered.connect(self.dialogue_system.retry_last_input)
        rps_action = menu.addAction("가위바위보 하기")
        rps_action.triggered.connect(self.show_rps_game)
        if self.rps_game is not None and self.rps_game.isVisible():
            restart_action = menu.addAction("가위바위보 다시 하기")
            restart_action.triggered.connect(self.show_rps_game)
            end_action = menu.addAction("가위바위보 종료")
            end_action.triggered.connect(self.end_rps_game)
        self._context_menu = menu
        menu.popup(global_pos)

    def show_settings(self):
        if self._show_settings_callback is not None:
            self._show_settings_callback()

    def _scaled_character_size(self):
        scale = self.size_percent / 100
        return round(self.CHARACTER_WIDTH * scale), round(self.CHARACTER_HEIGHT * scale)

    def set_show_hitboxes(self, enabled):
        self.show_debug = bool(enabled)
        if self.rig_view is not None:
            self.rig_view.set_debug_painter(self._paint_debug if self.show_debug else None)
        self.update()

    def apply_character_settings(self, width, height, personality, size_percent=None, movement_speed=None, jump_height=None, show_hitboxes=None, movement_range_extra_percent=None, *, trace_id=None):
        """Update bounds and personality without resetting the current mood."""
        requested_width, requested_height = width, height
        same_width = self.custom_screen_width == requested_width
        same_height = self.custom_screen_height == requested_height
        screen = QApplication.primaryScreen()
        if screen is not None:
            bounds = screen.geometry()
            width, height = min(width, bounds.width()), min(height, bounds.height())
        self.personality_system.load_preset(personality)
        options = normalize_character_options({
            'size_percent': self.size_percent if size_percent is None else size_percent,
            'movement_speed': self.movement_speed if movement_speed is None else movement_speed,
            'jump_height': self.jump_height if jump_height is None else jump_height,
            'show_hitboxes': self.show_debug if show_hitboxes is None else show_hitboxes,
            'movement_range_extra_percent': (self.movement_range_extra_percent
                                            if movement_range_extra_percent is None else movement_range_extra_percent),
        }, strict=True)
        old_width, old_height = self.width(), self.height()
        was_grounded, standing_surface = self.on_ground, self.current_surface
        old_body = self._physics_body_rect()
        center_x = self.x() + old_width / 2
        foot_y = self.y() + old_body.y() + old_body.height()
        self.size_percent = options['size_percent']
        self.movement_speed = options['movement_speed']
        self.jump_height = options['jump_height']
        self.movement_range_extra_percent = options['movement_range_extra_percent']
        self.set_show_hitboxes(options['show_hitboxes'])
        self.jump_force = math.sqrt(2 * self.gravity * self.jump_height)
        bounds_changed = not (same_width and same_height)
        self.custom_screen_width, self.custom_screen_height = requested_width, requested_height
        if screen is not None:
            self._screen_origin = bounds.topLeft()
            # Applying other character settings while a display is temporarily
            # smaller must preserve the user's existing activity-range intent.
            if not same_width:
                self._screen_auto_width = requested_width >= bounds.width()
            if not same_height:
                self._screen_auto_height = requested_height >= bounds.height()
        size_changed = self._scaled_character_size() != (old_width, old_height)
        log_event('settings.character.runtime_applied', '캐릭터 설정 실행 적용', category='시스템', trace_id=trace_id,
                  requested_bounds=(requested_width, requested_height), effective_bounds=(width, height),
                  personality=personality, options=options, resize_required=size_changed or bounds_changed)
        if not size_changed and not bounds_changed:
            return
        self._move_timer.stop()
        self.is_moving = False
        self.setFixedSize(*self._scaled_character_size())
        if self.rig_view is None and self.current_pixmap is not None:
            self.set_pixmap_with_flip(self.current_pixmap)
        if self.current_surface is not None and self.on_ground:
            foot_y = self.current_surface.y_level
        for surface in self.surfaces:
            if surface.name == 'ground':
                surface.y_level = self._screen_origin.y() + height
                surface.x_min = self._screen_origin.x()
                surface.x_max = self._screen_origin.x() + width
        body = self._physics_body_rect()
        body_bottom = body.y() + body.height()
        self.move(round(center_x - self.width() / 2), round(foot_y - body_bottom))
        self._clamp_position_to_screen()
        self.velocity_x = self.velocity_y = 0
        self.on_ground = bool(was_grounded and standing_surface is not None
                              and self.y() + body_bottom == standing_surface.y_level)
        self.is_jumping = False
        self._jump_physics_y = None
        self._physics_position_y = self._physics_position_x = None
        self.current_surface = standing_surface if self.on_ground else None
        if self.on_ground:
            self._grounded_body_bottom = body_bottom
            self._grounded_surface_level = standing_surface.y_level
        self.animation_controller.update_base_pos(self.pos())
        self.dialogue_system.update_dialogue_position()

        log_event('settings.character.geometry_applied', '캐릭터 크기·위치 적용', category='시스템', trace_id=trace_id,
                  size=(self.width(), self.height()), position=(self.x(), self.y()), grounded=self.on_ground)


    def select_ball(self):
        """Select the sandbox ball for the next character click."""
        message = self.sandbox_manager.select_ball()
        if message:
            self.dialogue_system.show_dialogue(message, duration=3000)



    
    #  <캐릭터 감정 확인 버튼 누를 시 >
    def show_russell_dialog(self):
        """Russell 감정 상태 다이얼로그 표시"""
        print("[show_russell_dialog] called")
        if self.russell_dialog is None:
            self.russell_dialog = RussellEmotionDialog(self)
            if hasattr(self.mood_system, "clear_manual_russell_state"):
                self.russell_dialog.closed.connect(
                    self.mood_system.clear_manual_russell_state
                )

        def state_provider():
            if hasattr(self.mood_system, "get_russell_state"):
                state = self.mood_system.get_russell_state()
            elif hasattr(self.mood_system, "russell"):
                state = {
                    "valence": float(getattr(self.mood_system.russell, "valence", 0.0)),
                    "arousal": float(getattr(self.mood_system.russell, "arousal", 0.0)),
                }
            else:
                state = {"valence": 0.0, "arousal": 0.0}

            if hasattr(self.mood_system, "get_dominant_emotion"):
                dominant = self.mood_system.get_dominant_emotion()
            else:
                dominant = "idle"

            return state["valence"], state["arousal"], dominant

        def apply_manual_state(valence: float, arousal: float, dominant: str):
            if hasattr(self.mood_system, "set_russell_state"):
                self.mood_system.set_russell_state(valence, arousal, dominant)
            elif hasattr(self.mood_system, "russell"):
                self.mood_system.russell.valence = max(-1.0, min(1.0, float(valence)))
                self.mood_system.russell.arousal = max(-1.0, min(1.0, float(arousal)))

            mood = self.mood_system.decide_emotion()
            self.update_action(mood)

            print(
                f"[Russell 수동 조작] Valence={valence:+.2f}, Arousal={arousal:+.2f}, Emotion={dominant}"
            )

        self.russell_dialog.set_state_provider(state_provider)
        self.russell_dialog.set_state_change_callback(apply_manual_state)
        if hasattr(self.mood_system, "get_emotion_explanation"):
            self.russell_dialog.set_explanation_provider(
                self.mood_system.get_emotion_explanation
            )
        self.russell_dialog.set_live_mode()
        valence, arousal, dominant = state_provider()
        self.russell_dialog.update_state(valence, arousal, dominant)
        self.russell_dialog.start_auto_refresh()

        if not self.russell_dialog.isVisible():
            screen = QApplication.primaryScreen()
            if screen is not None:
                geom = screen.availableGeometry()
                cursor_pos = QCursor.pos()
                dialog_width = self.russell_dialog.width()
                dialog_height = self.russell_dialog.height()
                max_x = geom.left() + max(0, geom.width() - dialog_width)
                max_y = geom.top() + max(0, geom.height() - dialog_height)
                x = min(max(cursor_pos.x() - dialog_width // 2, geom.left()), max_x)
                y = min(max(cursor_pos.y() - dialog_height // 2, geom.top()), max_y)
                self.russell_dialog.move(x, y)

        self.russell_dialog.showNormal()
        self.russell_dialog.show()
        self.russell_dialog.raise_()
        self.russell_dialog.activateWindow()

    # ====== 드래그 앤 드롭 시스템 ======
    def dragEnterEvent(self, event):
        """드래그가 위젯으로 진입했을 때"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            print(f"[드래그 진입] 파일/폴더 감지")

    def dragMoveEvent(self, event):
        """드래그하는 중"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        """드래그가 위젯을 벗어났을 때"""
        print(f"[드래그 이탈]")

    def dropEvent(self, event):
        """파일/폴더를 드롭했을 때 - 여러 개 파일 수용"""
        mime_data = event.mimeData()
        
        if mime_data.hasUrls():
            urls = mime_data.urls()
            for url in urls:
                file_path = url.toLocalFile()
                self.acquire_item(file_path)
            event.acceptProposedAction()

    def acquire_item(self, file_path):
        """파일/폴더를 획득했을 때 - 캐릭터 폴더로 이동 (여러 개 가능)"""
        try:
            file_path = Path(file_path)
            
            # 파일 이름 추출
            item_name = file_path.name
            
            # 캐릭터 폴더로 파일/폴더 이동
            dest_path = self.character_items_path / item_name
            
            # 이미 존재하면 번호 추가
            if dest_path.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                counter = 1
                while (self.character_items_path / f"{stem}_{counter}{suffix}").exists():
                    counter += 1
                dest_path = self.character_items_path / f"{stem}_{counter}{suffix}"
            
            # 파일/폴더 이동
            shutil.move(str(file_path), str(dest_path))
            
            # 리스트에 추가
            self.held_items.append(str(dest_path))
            
            # 첫 번째 아이템이면 감정 변화
            if len(self.held_items) == 1:
                self.mood_system.on_item_acquired()
                print(f"\n✨ [아이템 획득 시작]")
            
            print(f"   - {item_name} (총 {len(self.held_items)}개)")
            print(f"   위치: {dest_path}")
            
            # 마지막 아이템이면 감정 로그 출력
            if len(self.held_items) >= 1:
                log_event('mood.snapshot', '아이템 획득 후 감정 상태', category='캐릭터 상태', reason='item_acquired',
                          item=item_name, held_item_count=len(self.held_items),
                          state=getattr(self.mood_system, 'get_russell_state', lambda: {})(), final_emotion=self.mood_system.decide_emotion(),
                          formatted_state=self.mood_system.get_formatted_mood_log())
                print()
            
            # 현재 감정 애니메이션 갱신 + 아이콘 표시
            mood = self.mood_system.decide_emotion()
            self.update_action(mood)
        except Exception as e:
            print(f"[오류] 아이템 획득 실패: {e}")

    def release_items_to_desktop(self):
        """들고있던 아이템을 바탕화면으로 순차적 반환 (1초 간격)"""
        if not self.held_items:
            return
        if self._release_timer is not None and self._release_timer.isActive():
            return
        
        # 반환 대기 리스트 설정
        self._remaining_items_to_release = list(self.held_items)
        
        print(f"\n[아이템 반환 시작] {len(self._remaining_items_to_release)}개 아이템")
        print(f"   캐릭터 위치: ({self.x()}, {self.y()})")
        
        # 즉시 반환 뒤에도 마지막 항목까지 타이머로 처리한다.
        if len(self._remaining_items_to_release) > 1:
            self._release_timer = QTimer()
            self._release_timer.timeout.connect(self._release_single_item)
            self._release_timer.start(1000)  # 1초 간격

        # 첫 번째 아이템 즉시 반환 (한 개라면 완료 처리까지 실행)
        self._release_single_item()

    def _release_single_item(self):
        """단일 아이템을 바탕화면으로 반환"""
        if not self._remaining_items_to_release:
            if self._release_timer:
                self._release_timer.stop()
                self._release_timer = None
            
            # 반환 도중 새로 받은 아이템은 보관 목록에 남겨 둔다.
            if not self.held_items:
                self.held_items_icons = {}
                self.mood_system.on_item_dropped()
            
            print(f"\n[모든 아이템 반환 완료]")
            log_event('mood.snapshot', '아이템 반환 후 감정 상태', category='캐릭터 상태', reason='items_released',
                      held_item_count=len(self.held_items),
                      state=getattr(self.mood_system, 'get_russell_state', lambda: {})(), final_emotion=self.mood_system.decide_emotion(),
                      formatted_state=self.mood_system.get_formatted_mood_log())
            print()
            
            mood = self.mood_system.decide_emotion()
            self.update_action(mood)
            return
        
        try:
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.exists():
                desktop_path = Path.home() / "바탕화면"  # 한글 시스템
            
            if not desktop_path.exists():
                print("[오류] 바탕화면 경로를 찾을 수 없습니다")
                return
            
            # 반환할 아이템 선택
            item_path = self._remaining_items_to_release[0]
            held_item_path = Path(item_path)
            item_name = held_item_path.name
            
            # 대상 경로 설정
            dest_path = desktop_path / item_name
            
            # 이미 존재하면 번호 추가
            if dest_path.exists():
                stem = held_item_path.stem
                suffix = held_item_path.suffix
                counter = 1
                while (desktop_path / f"{stem}_{counter}{suffix}").exists():
                    counter += 1
                dest_path = desktop_path / f"{stem}_{counter}{suffix}"
            
            # 바탕화면으로 이동
            shutil.move(str(held_item_path), str(dest_path))
            self._remaining_items_to_release.pop(0)
            
            # held_items에서도 제거
            self.held_items.remove(item_path)
            if item_path in self.held_items_icons:
                del self.held_items_icons[item_path]
            
            print(f"[아이템 반환] {item_name}")
            print(f"   -> {dest_path}")
            print(f"   캐릭터 위치: ({self.x()}, {self.y()})")
            print(f"   남은 아이템: {len(self.held_items)}개")
            
            # 아이콘 업데이트 (제거된 아이템을 반영)
            self.render()
            if not self._remaining_items_to_release:
                self._release_single_item()
            
        except Exception as e:
            if self._release_timer is not None:
                self._release_timer.stop()
                self._release_timer = None
            print(f"[오류] 아이템 반환 실패: {e}")

    # ====== 점프 시스템 ======
    def _manual_control_active(self):
        return getattr(getattr(self, 'manual_control', None), 'active', False)

    def jump(self, force=False):
        """캐릭터 점프 실행 (지면에 있을 때만)"""
        if self._manual_control_active() and not force:
            return
        if self._cursor_over_character and not force:
            print("[점프 억제] 커서가 캐릭터 위에 있어 점프하지 않음")
            return
        if time.monotonic() - self._last_pet_time <= 2.0 and not force:
            print("[점프 억제] 쓰다듬기 중이므로 점프하지 않음")
            return
        if not self.on_ground:
            print(f"[점프 불가] on_ground={self.on_ground}")
            return
        
        jump_height = getattr(self, 'jump_height', DEFAULT_CHARACTER_OPTIONS['jump_height'])
        geometry = CharacterWidget._get_screen_geometry(self)
        body = self._physics_body_rect()
        jump_height = min(jump_height, max(0, self.y() + body.y() - geometry.y()))
        self.jump_force = math.sqrt(2 * self.gravity * jump_height)
        self._jump_apex_y = self.y() - jump_height
        self._jump_physics_y = float(self.y())
        self._physics_position_y = float(self.y())
        self._physics_position_x = float(self.x())
        self._jump_initial_velocity = self.jump_force
        self._authored_jump_landing = False
        if hasattr(self, '_gravity_last_time'):
            self._gravity_last_time = time.monotonic()
        print(f"[점프!] 목표 높이: {jump_height}px")
        self.is_jumping = True
        self.on_ground = False
        self.velocity_y = -self.jump_force  # 음수 = 위로
        self.can_jump = False
        
        # The authored rig pose follows flight progress; physics owns translation.
        mood = self.mood_system.decide_emotion()
        emotion = mood["emotion"]
        self.current_action = "jump" if self.rig_view is not None else self._get_emotion_animation(emotion)
        if self.rig_view is not None:
            self.sprite_animator.set_emotion(emotion)
            phase_setter = getattr(self.rig_view, 'set_physics_jump_phase', None)
            if phase_setter is not None:
                phase_setter(.15)
        self.update_render(self.current_action)
        
        # 점프 직후 화면 업데이트 (다음 _apply_gravity 호출까지 기다리지 않음)
        self.repaint()
    
    # ====== 디버그 렌더링 ======
    def paintEvent(self, event):
        """Sprite diagnostics; the native view draws these after its GL frame."""
        super().paintEvent(event)
        if self.rig_view is not None or not self.show_debug:
            return
        painter = QPainter(self)
        self._paint_debug(painter)
        painter.end()

    def _paint_debug(self, painter):
        """Use host screen coordinates, including on the native GL child."""
        if not self.show_debug:
            return
        painter.save()
        origin = self.mapToGlobal(QPoint(0, 0))
        host_rect = QRect(origin, self.size())
        windows = [s for s in self.surfaces if s.name.startswith('window_')]
        overlapping = []
        painter.setPen(QPen(QColor(255, 220, 0), 2))
        painter.setBrush(QBrush(QColor(255, 230, 0, 35)))
        for surface in windows:
            if surface.height is None:
                continue
            window_rect = QRect(int(surface.x_min), int(surface.y_level),
                                int(surface.x_max - surface.x_min), int(surface.height))
            if window_rect.intersects(host_rect):
                overlapping.append(surface.window_title or surface.name.removeprefix('window_'))
                painter.drawRect(window_rect.translated(-origin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 90, 90), 2))
        painter.drawRect(self._character_visual_rect().adjusted(0, 0, -1, -1))
        painter.setPen(QPen(QColor(255, 165, 0), 3))
        for surface in self.surfaces:
            if surface.name == 'ground':
                y = int(surface.y_level - origin.y())
                if 0 <= y <= self.height():
                    painter.drawLine(int(surface.x_min - origin.x()), min(y, self.height() - 1),
                                     int(surface.x_max - origin.x()), min(y, self.height() - 1))
        current = self.current_surface
        surface_name = (current.window_title or current.name) if current else '공중'
        lines = [f'위치: {origin.x()}, {origin.y()} | 바닥: {self.on_ground}',
                 f'표면: {surface_name}', f'감지한 창: {len(windows)}개']
        if overlapping:
            lines.append('겹치는 창: ' + ', '.join(dict.fromkeys(overlapping)))
        if not HAS_PYGETWINDOW:
            lines.append('창 감지 기능을 사용할 수 없습니다.')
        painter.setFont(QFont('Malgun Gothic', 7))
        flags = Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap
        text = '\n'.join(lines)
        available = QRect(0, 0, self.width() - 16, self.height())
        text_height = painter.fontMetrics().boundingRect(available, flags, text).height() + 4
        text_rect = QRect(5, 5, self.width() - 10, min(self.height() - 10, 110, text_height))
        painter.fillRect(text_rect, QColor(20, 26, 35, 190))
        painter.setPen(QColor(255, 245, 210))
        painter.drawText(text_rect.adjusted(3, 2, -3, -2), flags, text)
        painter.restore()

    def _character_visual_rect(self):
        """Character bounds exclude transparent host padding and effect icons."""
        if self.rig_view is not None:
            return self.rig_view.character_rect().toAlignedRect()
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            mask = pixmap.mask()
            if not mask.isNull():
                return QRegion(mask).boundingRect()
        return self.rect()

    def update_dragging(self):
        if self.is_dragging:
            self.drag_time += 0.1
            
            # 3초 이상 드래그하면 아이템 반환 시작
            if self.drag_time >= 3.0 and self.held_items and not self._remaining_items_to_release:
                print(f"[드래그 중 3초 도달] drag_time={self.drag_time:.1f}초 - 아이템 반환 시작")
                self.release_items_to_desktop()
            
            self.mood_system.apply_drag_displeasure(self.drag_time)
            # hovering 애니메이션은 draq 시작 시에만 로드됨
    
    # 캐릭터 랜덤 이동
    def random_move(self):
        if self._manual_control_active() or CharacterWidget._dialogue_is_busy(self):
            return
        if self.rig_view is not None and (self._rig_manual_action is not None
                or (self.sprite_animator.current_action == "land"
                    and self.sprite_animator.is_playing)):
            return
        if getattr(self, "_ball_session_active", False):
            return

        if self._cursor_over_character:
            return

        if time.monotonic() - self._last_pet_time <= 2.0:
            return
        
        # 떨어지는 중이면 이동 방지
        if not self.on_ground:
            print(f"[아직 공중] 떨어지는 중이므로 이동 스킵")
            return
        
        if self.is_dragging or self.is_moving:
            print(f"[early return] 드래그 중 또는 이동 중 스킵")
            return
        
        # ====== 랜덤 점프 (8% 확률) ======
        if random.random() < 0.08:
            # print(f"[랜덤 점프] 점프 실행!")
            self.jump()
            return  # 점프 시 이동하지 않음
        
        if random.random() > 0.8:  # 20% 확률로 이동 스킵
            print(f"[random skip] 확률로 스킵")
            return
        
        mood = self.mood_system.decide_emotion()
        emotion = mood['emotion']
        base_range = self._get_emotion_response_profile(emotion)["move_range"]
        scale = random_movement_scale(
            getattr(self, 'size_percent', DEFAULT_CHARACTER_OPTIONS['size_percent']),
            getattr(self, 'movement_range_extra_percent', DEFAULT_CHARACTER_OPTIONS['movement_range_extra_percent']),
        )
        move_range = round(base_range * scale)

        # 감정에 따라 움직이는 범위 결정 (X축만: 왼쪽/오른쪽)
        # Y축은 중력에 의해서만 제어됨
        dx = random.randint(-move_range, move_range)

        # 화면 경계 내로 이동 위치 제한 (커스텀 해상도 사용)
        target_x = self.x() + dx
        left, right = CharacterWidget._horizontal_limits(self)
        target_x = max(left, min(target_x, right))
        
        # 실제 이동 거리 재계산
        actual_dx = target_x - self.x()
        if actual_dx == 0:
            return
        
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
        
        self._target_x = target_x
        self._movement_x = float(self.x())
        self._walk_last_time = time.monotonic()
        
        # 이동 시작
        self.is_moving = True
        self.animation_controller.idle.stop()
        self._move_timer.start(16)
        log_event('character.movement_started', '랜덤 이동 시작', category='캐릭터 상태', source='random', position=(self.x(), self.y()), target_x=target_x, emotion=emotion, move_range=move_range)

    def move_toward_ball(self, ball_x: int) -> None:
        """Scale configured pixels/second by PJS02's emotion and intensity."""
        if self._manual_control_active() or self.is_dragging or self.is_jumping:
            self._chase_last_time = None
            return
        if self.rig_view is not None and (self._rig_manual_action is not None
                or not self.on_ground
                or (self.sprite_animator.current_action == "land"
                    and self.sprite_animator.is_playing)):
            self._chase_last_time = None
            return

        was_chasing = getattr(self, '_ball_chasing', False)
        self._ball_chasing = True
        target_x = ball_x - self.width() // 2
        left, right = CharacterWidget._horizontal_limits(self)
        target_x = max(left, min(target_x, right))
        delta_x = target_x - self.x()
        if not was_chasing:
            log_event('character.ball_chase_started', '공 추적 이동 시작', category='캐릭터 상태', target_x=target_x, position=(self.x(), self.y()))
            self._ball_arrival_logged = False
        if delta_x == 0:
            if not getattr(self, '_ball_arrival_logged', False):
                log_event('character.ball_chase_arrived', '공 이동 목표 도착', category='캐릭터 상태', target_x=target_x, position=(self.x(), self.y()))
                self._ball_arrival_logged = True
            self._chase_last_time = None
            return
        self._ball_arrival_logged = False

        emotion_info = self.mood_system.decide_emotion()
        emotion = emotion_info.get("emotion", "neutral")
        intensity = max(0.0, min(1.0, emotion_info.get("intensity", 0.0)))
        emotion_speed = {
            "neutral": 4.0,
            "calm": 3.0,
            "peaceful": 2.5,
            "contentment": 3.5,
            "sadness": 2.5,
            "melancholy": 2.0,
            "despair": 1.5,
            "anxiety": 6.0,
            "fear": 7.0,
            "interest": 8.0,
            "joy": 10.0,
            "delight": 9.0,
            "excitement": 12.0,
            "anger": 10.0,
            "disgust": 8.0,
        }.get(emotion, 4.0)
        speed_scale = emotion_speed / 4.0 * (0.7 + intensity * 0.3)
        now = time.monotonic()
        previous = getattr(self, '_chase_last_time', None) if was_chasing else None
        elapsed = min(0.1, max(0, now - previous)) if previous is not None else 0.016
        self._chase_last_time = now
        if not was_chasing:
            self._movement_x = float(self.x())
        self.is_flipped = delta_x > 0
        self._advance_horizontal(target_x, elapsed, speed_scale=speed_scale)
        self.animation_controller.update_base_pos(self.pos())

        walk_animation = self._get_walk_animation(emotion)
        if self.current_action != walk_animation:
            self.current_action = walk_animation
            self.sprite_animator.play(walk_animation, fps=24, loop=True)
    
    def _get_walk_animation(self, emotion):
        """
        기분에 맞는 walk 애니메이션 폴더명 반환
        현재 17개 감정은 기존 4개 감정별 걷기 에셋으로 매핑한다.
        """
        if self.rig_view is not None:
            self._rig_manual_action = None
            self.sprite_animator.set_emotion(emotion)
            self.sprite_animator.set_direction(self.is_flipped)
            self._refresh_rig_overlay()
            return "walk"
        action = self._animation_for_emotion(self._get_sprite_display_emotion(emotion))
        emotion_walk = f"walk_{action}"

        emotion_walk_path = self.assets_path / emotion_walk
        
        if emotion_walk_path.exists() and emotion_walk_path.is_dir():
            # print(f"[walk 애니메이션] {emotion_walk}/ 사용")
            return emotion_walk
        else:
            # print(f"[walk 애니메이션] walk/ 사용 (기본)")
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
        if self.rig_view is not None:
            self.sprite_animator.set_emotion(emotion)
            return "fall"
        # TODO: fall 애니메이션 구현
        # emotion_fall = f"fall_{emotion}"
        # emotion_fall_path = self.assets_path / emotion_fall
        # if emotion_fall_path.exists():
        #     return emotion_fall
        # else:
        #     fall_path = self.assets_path / "fall"
        #     if fall_path.exists():
        #         return "fall"
        

        # 임시: 현재 감정 상태에 대응하는 대표 애니메이션 유지
        return self._animation_for_emotion(self._get_sprite_display_emotion(emotion))

    
    def _horizontal_limits(self):
        bounds = CharacterWidget._get_screen_geometry(self)
        body = CharacterWidget._physics_body_rect(self)
        return (bounds.x() - body.x(),
                bounds.x() + bounds.width() - body.x() - body.width())

    def _advance_horizontal(self, target_x, elapsed, *, speed_scale=1.0):
        """Keep fractional positions so short/left/right routes have equal speed."""
        current = getattr(self, '_movement_x', float(self.x()))
        if round(current) != self.x():
            current = float(self.x())
        distance = target_x - current
        step = (getattr(self, 'movement_speed', DEFAULT_CHARACTER_OPTIONS['movement_speed'])
                * speed_scale * elapsed)
        reached = abs(distance) <= step
        self._movement_x = float(target_x) if reached else current + math.copysign(step, distance)
        self.move(round(self._movement_x), self.y())
        return reached

    def _smooth_moving(self):
        """슬라이딩 이동 애니메이션"""
        if not self.is_moving or self.is_dragging:
            return
        now = time.monotonic()
        previous = getattr(self, '_walk_last_time', None)
        elapsed = min(0.1, max(0, now - previous)) if previous is not None else 0.016
        self._walk_last_time = now
        target = getattr(self, '_target_x', self.x())
        left, right = CharacterWidget._horizontal_limits(self)
        target = max(left, min(target, right))
        if self._advance_horizontal(target, elapsed):
            log_event('character.movement_arrived', '이동 목표 도착', category='캐릭터 상태', target_x=target, position=(self.x(), self.y()))
            self._move_timer.stop()
            self.is_moving = False
            
            # walk 애니메이션 중지 후 현재 감정 상태로 복귀 (idle 깜빡임 방지)
            if self.rig_view is None or self.sprite_animator.current_action == "walk":
                self.sprite_animator.stop()
            
            mood = self.mood_system.decide_emotion()

            self.update_action(mood)
            
            self.animation_controller.update_base_pos(self.pos())
            self.animation_controller.start_idle()
            return

        self.update()  
    
    def _apply_gravity(self, dt=None):
        """Integrate elapsed time, with small steps for downward-only landings.

        Legacy velocities are pixels per 1/60 second and gravity is pixels per
        reference frame squared. Fractional positions survive between callbacks.
        """
        if dt is None:
            if hasattr(self, '_gravity_last_time'):
                now = time.monotonic()
                dt = max(0.0, now - self._gravity_last_time)
                self._gravity_last_time = now
            else:
                dt = 1 / 60  # Deterministic windowless callers.
        if self.is_dragging:
            self.on_ground = False
            self.velocity_y = 0
            self.velocity_x = 0
            self._physics_position_y = self._physics_position_x = None
            return
        dt = max(0.0, min(float(dt), 1.0))
        if not dt:
            return
        steps = max(1, math.ceil(dt * 120))
        for _ in range(steps):
            CharacterWidget._gravity_step(self, dt * 60 / steps)
        self.dialogue_system.update_dialogue_position()
        self.repaint()

    def _gravity_step(self, frames):
        geometry = CharacterWidget._get_screen_geometry(self)
        screen_left, screen_top = geometry.x(), geometry.y()
        screen_right = geometry.x() + geometry.width()
        current_y = getattr(self, '_physics_position_y', None)
        if current_y is None or round(current_y) != self.y():
            current_y = float(self.y())
        current_x = getattr(self, '_physics_position_x', None)
        if current_x is None or round(current_x) != self.x():
            current_x = float(self.x())
        body = self._physics_body_rect()
        body_bottom = body.y() + body.height()

        if abs(self.velocity_x) > 0.1:
            # Exponential damping has the same total effect at any callback rate.
            friction = max(.001, min(1.0, self.friction))
            distance = (frames if friction == 1 else
                        (friction ** frames - 1) / math.log(friction))
            new_x = current_x + self.velocity_x * distance
            if new_x + body.x() < screen_left:
                new_x = screen_left - body.x()
                self.velocity_x = abs(self.velocity_x) * self.bounce_damping
            elif new_x + body.x() + body.width() > screen_right:
                new_x = screen_right - body.x() - body.width()
                self.velocity_x = -abs(self.velocity_x) * self.bounce_damping
            self.velocity_x *= friction ** frames
            current_x = new_x
        else:
            self.velocity_x = 0

        # Continue standing only on the same unmoved surface. A newly detected
        # window above the feet, or a window moved upwards, cannot lift the pet.
        standing = self.current_surface
        previous_bottom = getattr(self, '_grounded_body_bottom', body_bottom)
        previous_level = getattr(self, '_grounded_surface_level',
                                 standing.y_level if standing is not None else None)
        if (self.on_ground and not self.is_jumping and self.velocity_y >= 0
                and standing is not None
                and standing in getattr(self, 'surfaces', [standing])
                and standing.y_level == previous_level
                and abs(current_y + previous_bottom - standing.y_level) <= 1
                and current_x + body.x() + body.width() > standing.x_min
                and current_x + body.x() < standing.x_max):
            self.velocity_y = 0
            self.velocity_x *= 0.95 ** frames
            self._grounded_body_bottom = body_bottom
            self._grounded_surface_level = standing.y_level
            self._physics_position_x = current_x
            self._physics_position_y = standing.y_level - body_bottom
            self.move(round(current_x), round(self._physics_position_y))
            return

        self.on_ground = False
        self.current_surface = None
        velocity = self.velocity_y
        # Exact constant acceleration, including time spent at terminal speed.
        terminal = 20.0
        until_terminal = max(0.0, (terminal - velocity) / self.gravity)
        accelerated = min(frames, until_terminal)
        new_y = (current_y + velocity * accelerated + .5 * self.gravity * accelerated ** 2
                 + terminal * (frames - accelerated))
        self.velocity_y = min(velocity + self.gravity * frames, terminal)
        if (self.rig_view is not None and self.velocity_y > 0
                and self.sprite_animator.current_action != "fall"):
            self.current_action = "fall"
            self.update_render("fall")
        if self.is_jumping:
            if new_y + body.y() < screen_top:
                new_y = screen_top - body.y()
                self.velocity_y = max(0, self.velocity_y)
            self._jump_physics_y = new_y
            phase_setter = getattr(self.rig_view, 'set_physics_jump_phase', None)
            initial = getattr(self, '_jump_initial_velocity', self.jump_force)
            if phase_setter is not None:
                progress = (1 + self.velocity_y / max(initial, .001)) / 2
                phase_setter(.15 + .55 * max(0, min(1, progress)))

        # Select from the previous feet position, then test the downward crossing.
        # This also catches fast falls through thin window tops without accepting
        # side entry below their top or an upward jump through them.
        landing_surface = self.get_landing_surface(current_y, current_x)
        if (landing_surface is not None and self.velocity_y >= 0
                and current_y + body_bottom <= landing_surface.y_level
                and new_y + body_bottom >= landing_surface.y_level):
            new_y = landing_surface.y_level - body_bottom
            self.on_ground = True
            self.velocity_y = 0
            self.velocity_x *= 0.8
            self.current_surface = landing_surface
            self._authored_jump_landing = self.is_jumping
            self.is_jumping = False
            self._jump_physics_y = None
            self.can_jump = True
            self._grounded_body_bottom = body_bottom
            self._grounded_surface_level = landing_surface.y_level
            self._last_surface_name = landing_surface.name
            print(f"[착지!] 표면: {landing_surface.name}, surface_y={landing_surface.y_level}px -> char_y={new_y}px")
            if self.rig_view is not None or not self.is_moving:
                self._rig_landed()

        self._physics_position_x, self._physics_position_y = current_x, new_y
        self.move(round(current_x), round(new_y))
        self._clamp_position_to_screen()
    
    def _clamp_position_to_screen(self):
        """Keep the painted body inside the full screen, including the taskbar."""
        geometry = CharacterWidget._get_screen_geometry(self)
        body = self._physics_body_rect()
        current_x = max(geometry.x() - body.x(), min(self.x(), geometry.x() + geometry.width() - body.x() - body.width()))
        current_y = max(geometry.y() - body.y(), min(self.y(), geometry.y() + geometry.height() - body.y() - body.height()))
        if self.x() != current_x or self.y() != current_y:
            self.move(int(current_x), int(current_y))
    
    # ====== 윈도우 감지 시스템 ======
    def _scan_windows(self):
        """활성 창들을 스캔해서 Surface 자동 추가/제거 및 좌표 업데이트"""
        if not HAS_PYGETWINDOW:
            return
        
        try:
            # 현재 활성 창 목록
            from .desktop_geometry import logical_window
            windows = [logical_window(window) for window in gw.getAllWindows()]
            current_window_keys = set()
            screen_width, screen_height = self._get_screen_dimensions()
            # QRect 객체 생성 (0,0부터 screen_width, screen_height까지)
            from PyQt6.QtCore import QRect
            screen_geometry = CharacterWidget._get_screen_geometry(self)
            self_hwnd = self._get_self_window_handle()
            hand_overlay = getattr(self, 'hand_overlay', None)
            hand_handles = hand_overlay.window_handles if hand_overlay is not None else set()

            # 첫 스캔 여부 확인
            first_scan = not hasattr(self, '_first_scan_done')
            
            # 디버그: 첫 스캔만 요약 출력
            if first_scan:
                print("[윈도우 감지] 화면에 보이는 창만 Surface로 등록 (실시간 좌표 업데이트)")
                print(f"  화면 범위: (0, 0) ~ ({screen_width}, {screen_height})")
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
                if window_handle in hand_handles:
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
                        window_title=window.title,
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
                    surface.window_title = window.title
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
            
            # 여러 창이 열려있으면 on_high_activity 트리거
            # ground를 제외한 창 개수
            active_windows = len([s for s in self.surfaces if s.name.startswith("window_")])
            
            # 창 개수가 급격히 변했으면 on_sudden_move 트리거
            if abs(active_windows - self.last_window_count) > 1:
                self.mood_system.on_sudden_move()
                print(f"[on_sudden_move 트리거] 창 개수 변화: {self.last_window_count} -> {active_windows}")
                self.window_change_count += 1
            
            # 복잡한 작업 감지 (창이 많고 자주 변함)
            if active_windows > 2 and self.window_change_count > 2:
                self.mood_system.on_task_complex()
                print(f"[on_task_complex 트리거] 활성 창={active_windows}개, 변화 횟수={self.window_change_count}")
            
            # # 고활동 감지 - 굳이 필요없을 듯?
            # if active_windows > 2:
            #     self.mood_system.on_high_activity()
            #     print(f"[on_high_activity 트리거] 활성 창={active_windows}개")
            
            # 창 변화 카운트 리셋 (매 스캔마다 리셋하지 말고 누적)
            self.last_window_count = active_windows
            if self.window_change_count > 5:
                self.window_change_count = 0
            
        except Exception as e:
            print(f"[윈도우 감지 오류] {e}")
    
    # ====== 대화 시스템 테스트 메서드 ======
    def test_dialogue_bubble(self, text: str = "안녕하세요!"):
        """말풍선 대화 테스트"""
        self.dialogue_system.show_dialogue(text, duration=5000, use_narration=False)
    
    def test_dialogue_narration(self, text: str = "이것은 나레이션 박스입니다!"):
        """나레이션 박스 대화 테스트"""
        self.dialogue_system.show_dialogue(text, duration=5000, use_narration=True, character_name="AI 어시스턴트")
    
    def test_dialogue_sequence(self):
        """여러 대화를 순차적으로 표시하는 테스트"""
        self.dialogue_system.queue_dialogue("안녕하세요!", duration=3000, delay_ms=0)
        self.dialogue_system.queue_dialogue("저는 AI 어시스턴트입니다.", duration=3000, delay_ms=1000)
        self.dialogue_system.queue_dialogue("문제가 있으신가요?", duration=3000, delay_ms=1000, use_narration=True)
