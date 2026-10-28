"""Five-round face-direction game using the existing character overlay card."""
import math
import secrets
import time
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app_logging import log_event
from .rps_game import RpsGameOverlay


DIRECTIONS = {"LEFT": "← 왼쪽", "RIGHT": "오른쪽 →"}


class DirectionTracker:
    """Only fresh, distinct camera frames from this game can establish a pose."""

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
        if label != self.label or stamp - self.last_time > 0.6:
            self.first_time, self.count = stamp, 0
        self.label, self.last_time = label, stamp
        self.count += 1
        return True

    def stable_direction(self, now):
        if (self.label and self.count >= 2 and self.last_time - self.first_time >= 0.12
                and 0 <= now - self.last_time <= 0.6):
            return self.label
        return None


class ChamGameOverlay(RpsGameOverlay):
    """Reuse card layout/placement; keep recognition, timing and scoring separate."""

    ROUNDS = 5
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
        self.round_number = 1
        self.player_score = self.character_score = 0
        self._yaw = self._turn_from = self._turn_to = 0.0
        self._turn_at = 0.0
        self._setup_game_card()

    def _setup_game_card(self):
        self.card.setObjectName('chamCard')
        self.card.setStyleSheet("""
            QFrame#chamCard {
                background: rgba(255, 253, 248, 248);
                border: 1px solid rgba(63, 55, 46, 32);
                border-radius: 12px;
            }
            QLabel { background: transparent; border: none;
                font-family: 'Malgun Gothic'; color: #37342f; }
        """)
        layout = self.card.layout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.removeWidget(self.title)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title.setStyleSheet('font-size: 11px; color: #8a8277;')
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setWordWrap(False)
        self.score = QLabel(self.card)
        self.score.setStyleSheet('font-size: 11px; color: #6d665c;')
        self.score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.score)
        layout.insertLayout(0, header)
        self.opponent_image.setFixedHeight(44)
        self.opponent_image.setStyleSheet('font-size: 27px; font-weight: 600; color: #37342f;')
        self.hint.setStyleSheet('font-size: 12px; color: #81786c;')
        self.hint.setFixedHeight(34)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def _show_message(self, main, hint):
        self.title.setText(f'참참참  {self.round_number}/{self.ROUNDS}')
        self.score.setText(f'나 {self.player_score} : {self.character_score} 캐릭터')
        self.opponent_image.setText(main)
        self.hint.setText(hint)

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
        self._pose(self._turn_from + (self._turn_to - self._turn_from) * smooth,
                   self._reaction)

    def start_game(self):
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
            self._error("카메라에 연결하지 못했어.\n우클릭 메뉴에서 다시 시작해줘.")
        else:
            self.start_round()
            log_event('game.cham.started', '참참참 게임 시작', category='캐릭터 상태',
                      trace_id=self.session, rounds=self.ROUNDS)
        self.timer.start()
        self.update_position()

    def start_round(self):
        now = time.time()
        self.state = "ready"
        self.deadline = now + self.READY_SECONDS
        self.tracker = DirectionTracker(self.session, now)
        self.player = self.opponent = self.result = None
        self._reaction = None
        self._turn(0, now)
        self._show_message('정면 봐줘', '마지막 ‘참!’에 고개를 돌려봐')

    def _begin_countdown(self, now):
        # Commit before reading any of the player's response frames.
        self.opponent = secrets.choice(tuple(DIRECTIONS))
        self.state = "countdown"
        self.deadline = now + 2 * self.BEAT_SECONDS
        self._show_message('참', '준비…')

    def _begin_capture(self, now):
        # Use actual reveal time, even when Qt's timer ran late.
        self.state = "waiting"
        self.deadline = now + self.CAPTURE_SECONDS
        self.tracker = DirectionTracker(self.session, now)
        self._turn(-65 if self.opponent == "LEFT" else 65, now)
        self._show_message('참!', '')
        log_event('game.cham.revealed', '참참참 방향 공개', category='캐릭터 상태',
                  trace_id=self.session, round=self.round_number, opponent=self.opponent)

    def handle_payload(self, payload):
        now = time.time()
        self.tick()
        if self.state not in {"ready", "countdown", "waiting"}:
            return
        if not self.tracker.feed(payload, now):
            return
        direction = self.tracker.stable_direction(now)
        if self.state == "ready" and direction == "CENTER":
            self._begin_countdown(now)
        elif self.state == "waiting" and direction in DIRECTIONS:
            self._finish_round(direction, now)

    def _finish_round(self, direction, now):
        self.player = direction
        caught = direction == self.opponent
        self.character_score += int(caught)
        self.player_score += int(not caught)
        self.result = "caught" if caught else "escaped"
        self._reaction = "happy" if caught else "sad"
        self.state = "result"
        self.deadline = now + self.RESULT_SECONDS
        self._show_message('잡혔다!' if caught else '피했다!',
                           '이번엔 같은 쪽이네' if caught else '이번엔 네가 이겼네')
        log_event('game.cham.result', '참참참 판정 완료', category='캐릭터 상태',
                  trace_id=self.session, round=self.round_number, player=direction,
                  opponent=self.opponent, result=self.result,
                  player_score=self.player_score, character_score=self.character_score)

    def _error(self, message):
        self.state = "error"
        self.deadline = time.time() + self.ERROR_SECONDS
        self._reaction = None
        self._turn(0, time.time())
        self._show_message('잠깐만', message)
        self._end_recognition()

    def tick(self):
        if self.state == "idle":
            return
        now = time.time()
        self._animate_turn(now)
        if self.state == "ready" and now >= self.deadline:
            self._error("얼굴이 잘 안 보여.\n카메라를 확인하고 다시 시작해줘.")
        elif self.state == "countdown":
            if now >= self.deadline:
                self._begin_capture(now)
            elif self.deadline - now <= self.BEAT_SECONDS:
                self.opponent_image.setText("참 · 참")
        elif self.state == "waiting" and now >= self.deadline:
            self.state = "retry"
            self.deadline = now + self.RESULT_SECONDS
            self._show_message('한 번 더', '잘 못 봤어. 점수는 그대로야')
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
                                   else '내가 이겼어!', '다시 하기는 우클릭 메뉴에서')
                self._end_recognition()
        elif self.state in {"finished", "error"} and now >= self.deadline:
            self.close()
        if self.isVisible():
            self.update_position()

    def closeEvent(self, event):
        if self.session:
            log_event('game.cham.ended', '참참참 게임 종료', category='캐릭터 상태',
                      trace_id=self.session, player_score=self.player_score,
                      character_score=self.character_score, state=self.state)
        self.timer.stop()
        self._end_recognition()
        self.state, self.session = "idle", None
        if self.pose_callback:
            self.pose_callback(None, None)
        QWidget.closeEvent(self, event)
