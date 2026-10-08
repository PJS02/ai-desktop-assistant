"""Immediate character commands, independent of persisted settings."""
import time
from app_logging import log_event, new_trace_id

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtCore import QRect


COMMAND_ROWS = (
    (('look_left', '왼쪽 보기'), ('look_front', '정면 보기'), ('look_right', '오른쪽 보기')),
    (('walk_left', '왼쪽 이동'), ('stop', '가만히 있기'), ('walk_right', '오른쪽 이동')),
    (('jump_left', '왼쪽 점프'), ('jump', '점프'), ('jump_right', '오른쪽 점프')),
    (('wave', '인사하기'), ('thinking', '생각하기'), ('sleep', '잠자기')),
    (('home', '기본 위치로 돌아가기'), ('resume', '자동 행동 재개')),
)
COMMAND_LABELS = dict(item for row in COMMAND_ROWS for item in row)
DISPLAY_EMOTIONS = (
    ('neutral', '중립'), ('happy', '기쁨'), ('excited', '신남'), ('proud', '자부심'),
    ('relieved', '안도'), ('calm', '차분함'), ('anxious', '불안'), ('hurt', '상처받음'),
    ('displeased', '불쾌'), ('distressed', '괴로움'), ('angry', '분노'), ('sad', '슬픔'),
    ('scared', '두려움'), ('depressed', '우울'), ('tired', '피곤함'),
)
DISPLAY_EMOTION_NAMES = dict(DISPLAY_EMOTIONS)
SPRITE_DISPLAY_EMOTIONS = {
    'neutral': 'neutral', 'happy': 'happy', 'excited': 'happy', 'proud': 'happy',
    'relieved': 'happy', 'calm': 'neutral', 'anxious': 'fear', 'hurt': 'sad',
    'displeased': 'angry', 'distressed': 'sad', 'angry': 'angry', 'sad': 'sad',
    'scared': 'fear', 'depressed': 'sad', 'tired': 'neutral',
}


class ManualControl(QObject):
    status_changed = pyqtSignal(str)
    display_emotion_changed = pyqtSignal(str)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.active = False
        self.display_emotion = None
        self.status = '자동 행동 중'
        self.direction = 0
        self.motion = None
        self.pending_pose = None
        self.home_x = host.x()
        self.last_tick = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def set_display_emotion(self, emotion):
        """Change the visible face without touching mood state or manual motion."""
        if emotion and emotion not in DISPLAY_EMOTION_NAMES:
            raise ValueError(f'Unknown display emotion: {emotion}')
        host = self.host
        if host._character_closing:
            return
        self.display_emotion = emotion or None
        mood = host.mood_system.decide_emotion()
        if host.rig_view is not None:
            host.sprite_animator.set_emotion_override(self.display_emotion)
            host.sprite_animator.set_emotion(mood['emotion'])
        elif host.is_moving and host.on_ground and not host.is_dragging:
            host.current_action = host._get_walk_animation(mood['emotion'])
            host.update_render(host.current_action)
        elif not host.is_dragging and host.current_action not in {'wave', 'thinking', 'sleep', 'hovering', 'land'}:
            host.update_action(mood)
        self.display_emotion_changed.emit(emotion or '')
        label = DISPLAY_EMOTION_NAMES[emotion] if emotion else '실제 감정 따르기'
        log_event('character.expression.changed', '표정 표시 설정을 바꿨습니다.',
                  category='캐릭터 상태', emotion=self.display_emotion, label=label,
                  actual_mood=mood)
        print(f'[표정 설정] {label}')

    def _status(self, text):
        if text == self.status:
            return
        self.status = text
        self.status_changed.emit(text)
        log_event('character.manual.status', text, category='캐릭터 상태',
                  trace_id=getattr(self, 'log_trace_id', None), active=self.active,
                  motion=self.motion, direction=self.direction)
        print(f'[직접 조작] {text}')

    def _stop_horizontal(self):
        host = self.host
        self.direction = 0
        self.motion = self.pending_pose = None
        self.timer.stop()
        host._move_timer.stop()
        host.is_moving = False
        host._ball_chasing = False
        host._chase_last_time = None
        host.velocity_x = 0
        host._rig_manual_action = None
        host.animation_controller.idle.stop()

    def _ground_ready(self):
        host = self.host
        return (host.on_ground and not host.is_jumping
                and not (host.rig_view is not None and host.sprite_animator.is_playing
                         and host.sprite_animator.current_action == 'land'))

    def _screen_body(self):
        host = self.host
        bounds = (host._get_screen_geometry() if hasattr(host, '_get_screen_geometry')
                  else QRect(0, 0, *host._get_screen_dimensions()))
        body = (host._physics_body_rect() if hasattr(host, '_physics_body_rect')
                else QRect(0, 0, host.width(), host.height()))
        return bounds, body

    def _idle(self):
        if self._ground_ready():
            self.host.current_action = 'idle'
            self.host.update_action(self.host.mood_system.decide_emotion())

    def _look(self, yaw):
        host = self.host
        host._rig_preferred_yaw = yaw
        host._rig_direction_explicit = True
        host.is_flipped = yaw > 0
        if host.rig_view is not None:
            host.sprite_animator.set_yaw(yaw)
        elif host.current_pixmap is not None:
            host.set_pixmap_with_flip(host.current_pixmap)

    def execute(self, command):
        host = self.host
        self.log_trace_id = new_trace_id('manual')
        log_event('character.manual.requested', '캐릭터 직접 조작을 요청했습니다.',
                  category='캐릭터 상태', trace_id=self.log_trace_id, command=command,
                  dragging=host.is_dragging, on_ground=host.on_ground)
        if command not in COMMAND_LABELS:
            log_event('character.manual.rejected', '알 수 없는 직접 조작 명령입니다.',
                      category='오류', level='ERROR', trace_id=self.log_trace_id,
                      command=command, reason='unknown_command')
            raise ValueError(f'Unknown character command: {command}')
        if host._character_closing:
            log_event('character.manual.rejected', '종료 중인 캐릭터 조작 요청을 보류합니다.',
                      category='캐릭터 상태', trace_id=self.log_trace_id, command=command, reason='closing')
            return
        if host.is_dragging:
            log_event('character.manual.rejected', '드래그 중인 캐릭터 조작 요청을 보류합니다.',
                      category='캐릭터 상태', trace_id=self.log_trace_id, command=command, reason='dragging')
            self._status('캐릭터를 놓은 뒤 다시 눌러 주세요.')
            return
        if command.startswith('jump') and not host.on_ground:
            log_event('character.manual.rejected', '착지 전 점프 요청을 보류합니다.',
                      category='캐릭터 상태', trace_id=self.log_trace_id, command=command, reason='not_grounded')
            self._status('착지한 뒤 점프할 수 있습니다.')
            return
        if command in {'wave', 'thinking', 'sleep'} and host.rig_view is None:
            if not list((host.assets_path / command).glob('frame_*.png')):
                log_event('character.manual.rejected', '요청한 동작의 PNG 프레임이 없습니다.',
                          category='캐릭터 상태', level='WARNING', trace_id=self.log_trace_id,
                          command=command, reason='missing_asset', assets_path=str(host.assets_path))
                self._status('현재 PNG 캐릭터에는 이 동작 이미지가 없습니다.')
                return
        if command == 'resume':
            self._stop_horizontal()
            self.active = False
            self._idle()
            host.animation_controller.update_base_pos(host.pos())
            if host.on_ground:
                host.animation_controller.start_idle()
            self._status('자동 행동 중')
            return
        was_active = self.active
        self.active = True
        host._mark_character_interaction()
        host.animation_controller.idle.stop()
        # A previously queued camera greeting cannot replace a manual command.
        host._pending_user_greeting_until = None
        host._greeting_retry_timer.stop()
        if command.startswith('look_'):
            if not was_active and host.is_moving:
                self._stop_horizontal()
                self._idle()
            self._look({'look_left': -65, 'look_front': 0, 'look_right': 65}[command])
            self._status(f'직접 조작 중 · {COMMAND_LABELS[command]}')
            return
        self._stop_horizontal()
        self._status(f'직접 조작 중 · {COMMAND_LABELS[command]}')
        if command == 'home':
            bounds, body = self._screen_body()
            left, right = bounds.x() - body.x(), bounds.x() + bounds.width() - body.x() - body.width()
            body_bottom = body.y() + body.height()
            host.move(round(max(left, min(self.home_x, right))), bounds.y() + bounds.height() - body_bottom)
            ground = next(surface for surface in host.surfaces if surface.name == 'ground')
            host.current_surface = ground
            host.on_ground, host.is_jumping, host.can_jump = True, False, True
            host.velocity_y = 0
            host._jump_physics_y = None
            host._grounded_body_bottom = body_bottom
            host._grounded_surface_level = ground.y_level
            host._gravity_last_time = time.monotonic()
            host._physics_position_y = float(host.y())
            if host.rig_view is not None:
                host.rig_view.set_jump_active(False)
            host.current_action = 'idle'
            host.update_render('idle' if host.rig_view is not None else host._get_emotion_animation(host.mood_system.decide_emotion()['emotion']))
        elif command == 'stop':
            self._idle()
        elif command in {'wave', 'thinking', 'sleep'}:
            self.pending_pose = command
            if not self._ground_ready():
                self._status(f'직접 조작 중 · {COMMAND_LABELS[command]} · 착지 후 실행')
            self.last_tick = time.monotonic()
            self.timer.start()
            self.tick()
        elif command.startswith('jump'):
            if command != 'jump':
                self.direction = -1 if command.endswith('left') else 1
                self._look(self.direction * 65)
            host.jump(force=True)
            if self.direction:
                self.motion = 'jump'
                host.is_moving = True
                host._movement_x = float(host.x())
                self.last_tick = time.monotonic()
                self.timer.start()
        else:
            self.direction = -1 if command.endswith('left') else 1
            self.motion = 'walk'
            self._look(self.direction * 65)
            host.is_moving = True
            host._movement_x = float(host.x())
            self.last_tick = time.monotonic()
            self.timer.start()
            self.tick()
        host.animation_controller.update_base_pos(host.pos())
        host.dialogue_system.update_dialogue_position()

    def tick(self):
        host = self.host
        if not self.active or host._character_closing:
            self.timer.stop()
            return
        if host.is_dragging:
            self._stop_horizontal()
            self._status('직접 조작 중 · 캐릭터 잡기로 동작 중단')
            return
        now = time.monotonic()
        elapsed = min(.1, max(0, now - self.last_tick)) if self.last_tick is not None else .016
        self.last_tick = now
        if self.pending_pose:
            if not self._ground_ready():
                return
            pose = self.pending_pose
            self.pending_pose = None
            self.timer.stop()
            if host.rig_view is not None:
                host._play_rig_action(pose)
            else:
                host.current_action = pose
                host.sprite_animator.play(pose, fps=24, loop=pose != 'wave')
            if pose == 'wave':
                host._show_perception_dialogue('안녕! 👋')
            self._status(f'직접 조작 중 · {COMMAND_LABELS[pose]}')
            return
        if self.motion == 'jump' and host.on_ground:
            self._stop_horizontal()
            self._idle()
            self._status('직접 조작 중 · 점프 완료, 제자리 대기')
            return
        if self.motion == 'walk':
            if not self._ground_ready():
                return
            host.is_moving = True
            if not host.current_action.startswith('walk'):
                host.current_action = host._get_walk_animation(host.mood_system.decide_emotion()['emotion'])
                host.update_render(host.current_action)
        if not self.direction:
            return
        bounds, body = self._screen_body()
        target = (bounds.x() - body.x() if self.direction < 0 else
                  bounds.x() + bounds.width() - body.x() - body.width())
        reached = host._advance_horizontal(target, elapsed)
        host.animation_controller.update_base_pos(host.pos())
        host.dialogue_system.update_dialogue_position()
        if reached:
            self._stop_horizontal()
            self._idle()
            self._status('직접 조작 중 · 화면 경계에서 정지')

    def shutdown(self):
        self.timer.stop()
        self.direction = 0
        self.motion = self.pending_pose = None
