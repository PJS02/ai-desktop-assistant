"""MediaPipe 가위바위보를 캐릭터 위에 표시하는 작은 오버레이."""
import math
from pathlib import Path
import secrets
import time
import uuid
from app_logging import log_event

from PyQt6.QtCore import QEvent, QRect, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from .overlay_geometry import place_above_character


HANDS = {"ROCK": "바위", "PAPER": "보", "SCISSORS": "가위"}
ASSETS = Path(__file__).resolve().parents[1] / "assets" / "rps"


def judge(player, opponent):
    """기존 판정 API. player는 항상 사용자다."""
    if player not in HANDS or opponent not in HANDS:
        raise ValueError("가위·바위·보가 아닌 손은 판정할 수 없습니다.")
    if player == opponent:
        return "무승부!"
    return "당신의 승리!" if (player, opponent) in {
        ("ROCK", "SCISSORS"), ("SCISSORS", "PAPER"), ("PAPER", "ROCK")
    } else "캐릭터의 승리!"


class HandTracker:
    """동일 세션의 최신 프레임으로 안정적인 한 손만 확정한다."""

    def __init__(self, session, since):
        self.session = session
        self.since = since
        self.last_time = 0.0
        self.first_time = 0.0
        self.label = None
        self.count = 0

    def feed(self, payload, now):
        if not isinstance(payload, dict):
            return False
        sample = payload.get("rps_game")
        if not isinstance(sample, dict) or sample.get("session") != self.session:
            return False
        stamp = sample.get("captured_at")
        if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp)):
            return False
        if stamp < self.since or stamp <= self.last_time or not 0 <= now - stamp <= 1.5:
            return False
        hands = sample.get("hands")
        hands = hands if isinstance(hands, dict) else {}
        valid = {str(hands.get(side)).upper() for side in ("left", "right")} & HANDS.keys()
        # 서로 다른 손을 동시에 내면 어느 손인지 임의로 고르지 않는다.
        label = next(iter(valid)) if len(valid) == 1 else None
        if label != self.label or stamp - self.last_time > 0.8:
            self.first_time, self.count = stamp, 0
        self.last_time, self.label = stamp, label
        self.count += 1
        return True

    def stable_hand(self, now):
        if (self.label and self.count >= 2 and self.last_time - self.first_time >= 0.15
                and 0 <= now - self.last_time <= 0.8):
            return self.label
        return None


class RpsGameOverlay(QWidget):
    """카운트다운 → 캐릭터 선택 → 사용자 기준 결과. 조작은 캐릭터 메뉴에서 한다."""

    COUNTDOWN_SECONDS = 3.0
    CAPTURE_SECONDS = 5.0
    REVEAL_SECONDS = 0.65
    RESULT_SECONDS = 4.0
    ERROR_SECONDS = 6.0

    def __init__(self, send_command, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("캐릭터 가위바위보")
        self.send_command = send_command
        self.session = None
        self._recognition_session = None
        self.state = "idle"
        self.tracker = None
        self.player = None
        self.opponent = None
        self.result = None
        self.deadline = 0.0
        self._anchor = parent
        self.images = {hand: QPixmap(str(ASSETS / f"{hand.lower()}.png")) for hand in HANDS}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame(self)
        self.card.setObjectName("rpsCard")
        self.card.setStyleSheet("""
            QFrame#rpsCard { background: rgba(25, 35, 47, 244); border: 2px solid #8ddbc5;
                border-radius: 18px; }
            QLabel { color: #f4f8fc; background: transparent; border: none;
                font-family: 'Malgun Gothic'; }
        """)
        outer.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        self.title = QLabel("가위바위보", self.card)
        self.title.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.title.setWordWrap(True)
        self.opponent_image = QLabel(self.card)
        self.opponent_image.setFixedHeight(80)
        self.opponent_image.setStyleSheet("font-size: 48px; font-weight: bold; color: #8ddbc5;")
        self.hint = QLabel(self.card)
        self.hint.setStyleSheet("font-size: 12px;")
        self.hint.setWordWrap(True)
        for label in (self.title, self.opponent_image, self.hint):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        if parent is not None:
            parent.installEventFilter(self)

    @property
    def is_active(self):
        return self.state != "idle"

    def _command(self, command):
        try:
            sent = bool(self.send_command is not None and self.send_command(command))
            log_event('game.rps.command', '가위바위보 인식 명령을 전송했습니다.' if sent else
                      '가위바위보 인식 명령을 전송하지 못했습니다.', trace_id=self.session,
                      category='캐릭터 상태' if sent else '오류', level='INFO' if sent else 'ERROR',
                      command=command, sent=sent)
            return sent
        except Exception as exc:
            log_event('game.rps.command_failed', '가위바위보 인식 명령 전송 중 오류가 발생했습니다.',
                      trace_id=self.session, category='오류', level='ERROR', command=command, error=str(exc))
            print(f"[가위바위보 연결 오류] {exc}")
            return False

    def _end_recognition(self):
        session, self._recognition_session = self._recognition_session, None
        if session:
            self._command(f"rps_end {session}")

    def start_game(self):
        self.start_round()

    def start_round(self):
        if self.session:
            log_event('game.rps.ended', '이전 가위바위보 판을 재시작합니다.',
                      category='캐릭터 상태', trace_id=self.session, reason='restarted', state=self.state)
        self.timer.stop()
        self._end_recognition()
        # 매 판 새 세션을 사용해 재시작 전의 프레임을 받지 않는다.
        self.session = uuid.uuid4().hex
        now = time.time()
        self.tracker = HandTracker(self.session, now)
        # 사용자의 손을 받기 전에 선택을 확정한다.
        self.opponent = secrets.choice(tuple(HANDS))
        log_event('game.rps.started', '가위바위보 판을 시작하고 캐릭터 손을 선택했습니다.',
                  category='캐릭터 상태', trace_id=self.session, opponent=self.opponent,
                  countdown_seconds=self.COUNTDOWN_SECONDS, capture_seconds=self.CAPTURE_SECONDS)
        self.player = self.result = None
        self.state = "countdown"
        self.deadline = now + self.COUNTDOWN_SECONDS
        self.title.setText("가위바위보")
        self.opponent_image.clear()
        self.opponent_image.setText("3")
        self.hint.setText("카메라에 한 손을 보여주세요.\n카운트다운이 끝나면 낼 손을 잠시 유지해주세요.")
        self.show()
        self.update_position()
        # 실패 응답이 늦게 도착해도 종료 명령으로 임시 인식 모드를 정리한다.
        self._recognition_session = self.session
        if not self._command(f"rps_begin {self.session}"):
            self.finish_without_result("사용자 인식 프로그램을 연결하지 못했어요.\n캐릭터 메뉴에서 다시 시작해주세요.")
            return
        self.timer.start()

    def _begin_capture(self):
        capture_at = self.deadline
        self.state = "waiting"
        self.deadline = capture_at + self.CAPTURE_SECONDS
        # 준비 중 보여준 손이 아니라 카운트다운 종료 후의 손으로 판정한다.
        self.tracker = HandTracker(self.session, capture_at)
        log_event('game.rps.waiting', '사용자의 손 판정을 기다립니다.', category='캐릭터 상태',
                  trace_id=self.session, capture_at=capture_at, deadline=self.deadline)
        self.title.setText("보!")
        self.opponent_image.clear()
        self.opponent_image.setText("?")
        self.hint.setText("한 손의 모양을 잠시 유지해주세요.")

    def handle_payload(self, payload):
        if self.state not in {"countdown", "waiting"}:
            return
        now = time.time()
        # Qt 타이머보다 프레임이 먼저 도착해도 올바른 판정 구간으로 넘긴다.
        if self.state == "countdown" and now >= self.deadline:
            self._begin_capture()
        if self.state == "waiting" and now >= self.deadline:
            self.finish_without_result("손을 확실하게 인식하지 못했어요.\n캐릭터 메뉴에서 다시 시작해주세요.", reason='timeout')
            return
        previous_label = self.tracker.label
        if self.tracker.feed(payload, now) and self.state == "waiting":
            label = self.tracker.label
            if label != previous_label:
                log_event('game.rps.hand_observed', '사용자의 손 후보가 바뀌었습니다.',
                          category='사용자 인식', trace_id=self.session,
                          hand=label, previous_hand=previous_label, sample=payload.get('rps_game'))
            self.hint.setText(f"{HANDS[label]} · 잠시 유지해주세요." if label else
                              "한 손으로 가위·바위·보를 보여주세요.")

    def tick(self):
        now = time.time()
        if self.state == "countdown":
            remaining = self.deadline - now
            if remaining <= 0:
                self._begin_capture()
            else:
                self.opponent_image.setText(str(max(1, math.ceil(remaining))))
        if self.state == "waiting":
            if now >= self.deadline:
                self.finish_without_result("손을 확실하게 인식하지 못했어요.\n캐릭터 메뉴에서 다시 시작해주세요.", reason='timeout')
            else:
                hand = self.tracker.stable_hand(now)
                if hand:
                    self.finish_round(hand)
                elif now - self.tracker.last_time > 0.8:
                    self.hint.setText("카메라에 한 손을 보여주세요.\n다른 손은 화면 밖으로 빼주세요.")
        elif self.state == "reveal" and now >= self.deadline:
            self.state = "result"
            self.deadline = now + self.RESULT_SECONDS
            self.title.setText({"당신의 승리!": "승리!", "캐릭터의 승리!": "패배!",
                                "무승부!": "무승부!"}[self.result])
            self.hint.setText(f"사용자 기준 · 나 {HANDS[self.player]} / 캐릭터 {HANDS[self.opponent]}\n"
                              "다시 하기·종료는 캐릭터 메뉴에서")
        elif self.state in {"result", "error"} and now >= self.deadline:
            self.close()
            return
        if self.isVisible():
            self.update_position()

    def show_hand(self, picture, hand):
        picture.clear()
        pixmap = self.images[hand]
        if pixmap.isNull():
            picture.setText(HANDS[hand])
        else:
            picture.setPixmap(pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def finish_round(self, hand):
        self.player = hand
        self.result = judge(hand, self.opponent)
        log_event('game.rps.result', '가위바위보 결과를 확정했습니다.', category='캐릭터 상태',
                  trace_id=self.session, player=hand, opponent=self.opponent, result=self.result,
                  stable_samples=self.tracker.count if self.tracker else None)
        self.state = "reveal"
        self.deadline = time.time() + self.REVEAL_SECONDS
        self.title.setText(f"캐릭터 · {HANDS[self.opponent]}")
        self.show_hand(self.opponent_image, self.opponent)
        self.hint.setText(f"나 · {HANDS[hand]}")
        self._end_recognition()
        self.timer.start()
        self.update_position()

    def finish_without_result(self, message, *, reason='connection_failed'):
        log_event('game.rps.no_result', '가위바위보 판정을 완료하지 못했습니다.',
                  category='캐릭터 상태', level='WARNING', trace_id=self.session,
                  reason=reason, detail=message, last_hand=self.tracker.label if self.tracker else None)
        self.state = "error"
        self.player = self.result = None
        self.deadline = time.time() + self.ERROR_SECONDS
        self.title.setText("다시 해볼까요?")
        self.opponent_image.clear()
        self.opponent_image.setText("?")
        self.hint.setText(message)
        self._end_recognition()
        self.timer.start()
        self.update_position()

    def update_position(self):
        parent = self._anchor
        if parent is None:
            screen = QApplication.primaryScreen()
            anchor = QRect(screen.geometry().center(), self.size()) if screen else QRect(0, 0, 1, 1)
        else:
            body_method = getattr(parent, "_physics_body_rect", None)
            local = body_method() if body_method else parent.rect()
            anchor = QRect(parent.mapToGlobal(local.topLeft()), local.size())
            screen = QApplication.screenAt(anchor.center()) or parent.screen()
        if screen is None:
            return
        bounds = screen.geometry()
        self.setFixedWidth(max(1, min(300, bounds.width() - 16)))
        self.adjustSize()
        self.move(place_above_character(anchor, self.size(), bounds, gap=12))

    def eventFilter(self, watched, event):
        if watched is self._anchor and self.isVisible() and event.type() in {
            QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
        }:
            self.update_position()
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent):
        if self.session:
            log_event('game.rps.ended', '가위바위보 판을 종료합니다.', category='캐릭터 상태',
                      trace_id=self.session, state=self.state, result=self.result,
                      player=self.player, opponent=self.opponent)
        self.timer.stop()
        self._end_recognition()
        self.state = "idle"
        self.session = None
        super().closeEvent(event)


# 이전 import를 유지해도 별도 대화상자 대신 캐릭터 오버레이를 사용한다.
RpsGameDialog = RpsGameOverlay
