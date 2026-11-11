"""Single-round face-direction game using the existing character overlay card."""
import math
import secrets
import time
import uuid

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QWidget

from app_logging import log_event
from .dialogue_widget import UserDialogueBubble
from .rps_game import RpsGameOverlay


DIRECTIONS = {"LEFT": "← 왼쪽", "RIGHT": "오른쪽 →"}
DIRECTION_LABELS = {"CENTER": "정면", **DIRECTIONS}
DIRECTION_PENDING = "방향 확인 중…"
DIRECTION_STATES = {"ready", "countdown", "waiting"}


class DirectionTracker:
    """Only fresh, distinct camera frames from this game can establish a pose."""

    FRESH_SECONDS = 0.6

    def __init__(self, session, since):
        self.session, self.since = session, since
        self.label = None
        self.first_time = self.last_time = 0.0
        self.count = 0

    def feed(self, payload, now):
        sample = payload.get("cham_game") if isinstance(payload, dict) else None
        if not isinstance(sample, dict) or sample.get("session") != self.session:
            return False
        stamp = sample.get("captured_at")
        if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp) or stamp < self.since
                or stamp <= self.last_time or not 0 <= now - stamp <= 0.8):
            return False
        label = sample.get("direction")
        if label not in {"LEFT", "RIGHT", "CENTER"}:
            label = None
        if label != self.label or stamp - self.last_time > self.FRESH_SECONDS:
            self.first_time, self.count = stamp, 0
        self.label, self.last_time = label, stamp
        self.count += 1
        return True

    def stable_direction(self, now):
        if (self.label and self.count >= 2 and self.last_time - self.first_time >= 0.12
                and 0 <= now - self.last_time <= self.FRESH_SECONDS):
            return self.label
        return None


class ChamGameOverlay(RpsGameOverlay):
    """Reuse card layout/placement; keep recognition, timing and scoring separate."""

    ROUNDS = 1
    BEAT_SECONDS = 0.7
    CAPTURE_SECONDS = 1.4
    RESULT_SECONDS = 1.8
    READY_SECONDS = 20.0
    TURN_SECONDS = 0.18
    OVERLAY_WIDTH = 240

    def __init__(self, send_command, parent=None, *, pose_callback=None):
        super().__init__(send_command, parent)
        self.setWindowTitle("캐릭터 참참참")
        self.pose_callback = pose_callback
        self.reaction_face = None
        self._reaction_until = 0.0
        self._best_lead = 0
        self.round_number = 1
        self.player_score = self.character_score = 0
        self._yaw = self._turn_from = self._turn_to = 0.0
        self._turn_at = 0.0
        self.direction_bubble = UserDialogueBubble(DIRECTION_PENDING, duration=0, parent=self)
        self.direction_bubble.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
        self._direction_last_seen = None
        self._direction_anchor = None
        self._setup_game_card()

    def _setup_game_card(self):
        self.card.setObjectName('chamCard')
        layout = self.card.layout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self.title.setStyleSheet('font-size: 11px; font-weight: 600; color: #4e5e6c;')
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setWordWrap(False)
        self.opponent_image.setFixedHeight(44)
        self.opponent_image.setStyleSheet('font-size: 24px; font-weight: bold; color: #2e4f69;')

    def _show_message(self, main):
        self.title.setText(f'참참참  {self.round_number}/{self.ROUNDS}')
        self.opponent_image.setText(main)

    def update_position(self):
        super().update_position()
        parent = self._anchor
        anchor = self.geometry()
        avoid = self.geometry()
        if parent is not None:
            body = getattr(parent, '_physics_body_rect', parent.rect)()
            anchor = QRect(parent.mapToGlobal(body.topLeft()), body.size())
            dialogue = getattr(parent, 'dialogue_system', None)
            for name in ('current_dialogue', 'current_user_dialogue'):
                bubble = getattr(dialogue, name, None)
                if bubble is not None and bubble.isVisible():
                    avoid = avoid.united(bubble.geometry())
        position = (*anchor.getRect(), avoid)
        if position != self._direction_anchor:
            self._direction_anchor = position
            self.direction_bubble.update_position_with_character(*position)

    def _command(self, command):
        try:
            return bool(self.send_command and self.send_command(command))
        except Exception as exc:
            log_event('game.cham.command_failed', '참참참 인식 연결 실패',
                      category='오류', level='ERROR', trace_id=self.session, error=str(exc))
            return False

    def _end_recognition(self):
        session, self._recognition_session = self._recognition_session, None
        if session:
            self._command(f"cham_end {session}")

    def _pose(self, yaw, emotion=None):
        self._yaw = yaw
        if self.pose_callback:
            self.pose_callback(yaw, emotion)

    def _turn(self, yaw, now):
        self._turn_from, self._turn_to, self._turn_at = self._yaw, yaw, now

    def _animate_turn(self, now):
        if self.state == "countdown":
            self._pose(5 * math.sin((self.deadline - now) / self.BEAT_SECONDS * 2 * math.pi))
            return
        progress = max(0.0, min(1.0, (now - self._turn_at) / self.TURN_SECONDS))
        smooth = progress * progress * (3 - 2 * progress)
        face = self._reaction if self.reaction_face is None or now < self._reaction_until else None
        self._pose(self._turn_from + (self._turn_to - self._turn_from) * smooth, face)

    def start_game(self):
        self._best_lead = 0
        self.cue_stopped.emit()
        self.timer.stop()
        self._end_recognition()
        self.session = uuid.uuid4().hex
        self.round_number = 1
        self.player_score = self.character_score = 0
        self._reaction = None
        self._pose(0)
        self._turn(0, time.time())
        self.show()
        self._recognition_session = self.session
        if not self._command(f"cham_begin {self.session}"):
            self._error()
        else:
            self.start_round()
            log_event('game.cham.started', '참참참 게임 시작', category='캐릭터 상태',
                      trace_id=self.session, rounds=self.ROUNDS)
        self.timer.start()
        self.update_position()

    def start_round(self):
        self.cue_stopped.emit()
        self._last_cue = None
        now = time.time()
        self.state = "ready"
        self.deadline = now + self.READY_SECONDS
        self.tracker = DirectionTracker(self.session, now)
        self.player = self.opponent = self.result = None
        self._reaction = None
        self._turn(0, now)
        self._show_message('정면 봐줘')
        self._direction_last_seen = None
        self.direction_bubble.set_text(DIRECTION_PENDING)
        self.update_position()
        self.direction_bubble.show()

    def _begin_countdown(self, now):
        # Commit before reading any of the player's response frames.
        self.opponent = secrets.choice(tuple(DIRECTIONS))
        self.state = "countdown"
        self._report_emotion('game_start', 'expect', round=True)
        self.deadline = now + 2 * self.BEAT_SECONDS
        self._show_message('참')
        self._request_cue('cham_1')

    def _begin_capture(self, now):
        # Use actual reveal time, even when Qt's timer ran late.
        self.state = "waiting"
        self.deadline = now + self.CAPTURE_SECONDS
        self.tracker = DirectionTracker(self.session, now)
        self._turn(-65 if self.opponent == "LEFT" else 65, now)
        self._show_message('참!')
        self._request_cue('cham_final')
        log_event('game.cham.revealed', '참참참 방향 공개', category='캐릭터 상태',
                  trace_id=self.session, round=self.round_number, opponent=self.opponent)

    def handle_payload(self, payload):
        now = time.time()
        self.tick()
        if self.state not in DIRECTION_STATES:
            return
        if not self.tracker.feed(payload, now):
            return
        direction = self.tracker.stable_direction(now)
        if direction is not None:
            self._direction_last_seen = self.tracker.last_time
            self.direction_bubble.set_text(DIRECTION_LABELS[direction])
        if self.state == "ready" and direction == "CENTER":
            self._begin_countdown(now)
        elif self.state == "waiting" and direction in DIRECTIONS:
            self._finish_round(direction, now)

    def _finish_round(self, direction, now):
        if self.state not in {'waiting', 'countdown'}:
            return
        self.player = direction
        caught = direction == self.opponent
        self.character_score += int(caught)
        self.player_score += int(not caught)
        self.result = "caught" if caught else "escaped"
        self._best_lead = max(self._best_lead, self.character_score - self.player_score)
        self._reaction = "happy" if caught else "sad"
        self._report_emotion('game_win' if caught else 'game_loss', 'result', round=True)
        if self.reaction_face is not None:
            event = "game_win" if caught else "game_loss"
            self._reaction = self.reaction_face(event, 1.0)
            self._reaction_until = now + 1.15
        self.state = "result"
        self.deadline = now + self.RESULT_SECONDS
        self._show_message('잡혔다!' if caught else '피했다!')
        log_event('game.cham.result', '참참참 판정 완료', category='캐릭터 상태',
                  trace_id=self.session, round=self.round_number, player=direction,
                  opponent=self.opponent, result=self.result,
                  player_score=self.player_score, character_score=self.character_score)

    def _error(self):
        self._report_emotion('game_cancel', 'cancel')
        self.cue_stopped.emit()
        self.state = "error"
        self.deadline = time.time() + self.ERROR_SECONDS
        self._reaction = None
        self._turn(0, time.time())
        self._show_message('잠깐만')
        self.direction_bubble.hide()
        self._end_recognition()

    def tick(self):
        if self.state == "idle":
            return
        now = time.time()
        if (self.state in DIRECTION_STATES and self._direction_last_seen is not None
                and now - self._direction_last_seen > DirectionTracker.FRESH_SECONDS):
            self._direction_last_seen = None
            self.direction_bubble.set_text(DIRECTION_PENDING)
        self._animate_turn(now)
        if self.state == "ready" and now >= self.deadline:
            self._error()
        elif self.state == "countdown":
            if now >= self.deadline:
                self._begin_capture(now)
            elif self.deadline - now <= self.BEAT_SECONDS:
                self.opponent_image.setText("참 · 참")
                self._request_cue('cham_2')
        elif self.state == "waiting" and now >= self.deadline:
            self.state = "retry"
            self.deadline = now + self.RESULT_SECONDS
            self._show_message('한 번 더')
            self.direction_bubble.set_text(DIRECTION_PENDING)
            log_event('game.cham.no_result', '참참참 판정 없이 재시도', category='캐릭터 상태',
                      trace_id=self.session, round=self.round_number)
        elif self.state == "retry" and now >= self.deadline:
            self.start_round()
        elif self.state == "result" and now >= self.deadline:
            if self.round_number < self.ROUNDS:
                self.round_number += 1
                self.start_round()
            else:
                self.state = "finished"
                self.deadline = now + 6.0
                self._turn(0, now)
                self._show_message('네가 이겼어!' if self.player_score > self.character_score
                                   else '내가 이겼어!')
                self.direction_bubble.hide()
                won = self.character_score > self.player_score
                event = ("game_win" if won else "game_disappointed"
                         if self._best_lead >= 2 else "game_loss")
                self._report_emotion(event, 'final', final=True, expected_win=self._best_lead >= 2)
                if self.reaction_face is not None:
                    self._reaction = self.reaction_face(event, 1.25)
                    self._reaction_until = now + 1.55
                self._end_recognition()
                self.result_revealed.emit(event)
        elif self.state in {"finished", "error"} and now >= self.deadline:
            self.close()
        if self.isVisible():
            self.update_position()

    def closeEvent(self, event):
        self._report_emotion('game_cancel', 'cancel')
        self.cue_stopped.emit()
        if self.session:
            log_event('game.cham.ended', '참참참 게임 종료', category='캐릭터 상태',
                      trace_id=self.session, player_score=self.player_score,
                      character_score=self.character_score, state=self.state)
        self.timer.stop()
        self.direction_bubble.hide()
        self._end_recognition()
        self.state, self.session = "idle", None
        if self.pose_callback:
            self.pose_callback(None, None)
        QWidget.closeEvent(self, event)
