"""기존 MediaPipe 손 인식을 사용하는 가위바위보 게임 창."""
import math
from pathlib import Path
import secrets
import time
import uuid

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


HANDS = {"ROCK": "바위", "PAPER": "보", "SCISSORS": "가위"}
ASSETS = Path(__file__).resolve().parents[1] / "assets" / "rps"


def judge(player, opponent):
    if player not in HANDS or opponent not in HANDS:
        raise ValueError("가위·바위·보가 아닌 손은 판정할 수 없습니다.")
    if player == opponent:
        return "무승부!"
    return "당신의 승리!" if (player, opponent) in {
        ("ROCK", "SCISSORS"), ("SCISSORS", "PAPER"), ("PAPER", "ROCK")
    } else "캐릭터의 승리!"


class HandTracker:
    """같은 세션의 최신 프레임만 모아 잠깐의 오인식과 중복 전송을 거른다."""

    def __init__(self, session, since):
        self.session = session
        self.since = since
        self.last_time = 0.0
        self.first_time = 0.0
        self.label = None
        self.count = 0

    def feed(self, payload, now):
        sample = payload.get("rps_game")
        if not isinstance(sample, dict) or sample.get("session") != self.session:
            return False
        stamp = sample.get("captured_at")
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            return False
        if stamp < self.since or stamp <= self.last_time or not 0 <= now - stamp <= 1.5:
            return False
        hands = sample.get("hands")
        hands = hands if isinstance(hands, dict) else {}
        valid = {str(hands.get(side)).upper() for side in ("left", "right")} & HANDS.keys()
        # 서로 다른 손을 동시에 내면 어느 쪽을 낸 것인지 임의로 고르지 않는다.
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


class RpsGameDialog(QDialog):
    def __init__(self, send_command, parent=None):
        super().__init__(parent)
        self.send_command = send_command
        self.session = None
        self.state = "idle"
        self.setWindowTitle("캐릭터와 가위바위보")
        self.setMinimumSize(620, 480)
        self.setStyleSheet("""
            QDialog { background: #151c26; }
            QLabel { color: #f3f5fa; font: 12pt 'Malgun Gothic'; }
            QPushButton { background: #80d4bd; color: #15231f; border: none;
                border-radius: 8px; padding: 12px 25px; font: bold 11pt 'Malgun Gothic'; }
            QPushButton:disabled { background: #384452; color: #9ca8b5; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self.title = QLabel("캐릭터와 가위바위보")
        self.title.setStyleSheet("font-size: 22pt; font-weight: bold;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.hint = QLabel("카메라에 한 손을 보여주세요.")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint)
        cards = QHBoxLayout()
        self.player_image, self.opponent_image = QLabel("?"), QLabel("?")
        self.player_text, self.opponent_text = QLabel("나"), QLabel("캐릭터")
        for picture, caption in ((self.player_image, self.player_text),
                                 (self.opponent_image, self.opponent_text)):
            column = QVBoxLayout()
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setMinimumSize(240, 240)
            picture.setStyleSheet("background: #232f3e; border-radius: 12px; font-size: 64pt;")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(picture)
            column.addWidget(caption)
            cards.addLayout(column)
        layout.addLayout(cards)
        self.observation = QLabel("인식 준비 중")
        self.observation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.observation)
        buttons = QHBoxLayout()
        self.retry = QPushButton("다시 하기")
        self.retry.clicked.connect(self.start_round)
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        buttons.addWidget(self.retry)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.images = {hand: QPixmap(str(ASSETS / f"{hand.lower()}.png")) for hand in HANDS}
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)

    def start_game(self):
        self.session = uuid.uuid4().hex
        self.start_round()

    def start_round(self):
        self.timer.stop()
        now = time.time()
        self.tracker = HandTracker(self.session, now)
        # 사용자 손을 관찰하기 전에 선택하며 판정이 끝날 때까지 공개하지 않는다.
        self.opponent = secrets.choice(tuple(HANDS))
        self.state = "ready"
        self.deadline = now + 30
        self.retry.setEnabled(False)
        self.title.setText("손을 보여주세요")
        self.hint.setText("한 손이 인식되면 카운트다운을 시작합니다.")
        self.observation.setText("카메라 연결과 손 인식을 기다리는 중…")
        for picture in (self.player_image, self.opponent_image):
            picture.clear()
            picture.setText("?")
        self.player_text.setText("나")
        self.opponent_text.setText("캐릭터 · 선택 완료")
        if self.send_command is None or not self.send_command(f"rps_begin {self.session}"):
            self.finish_without_result("사용자 인식 프로그램을 연결하지 못했습니다.")
            return
        self.timer.start()

    def handle_payload(self, payload):
        if self.state not in {"ready", "countdown", "waiting"}:
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        if self.tracker.feed(payload, now):
            label = self.tracker.label
            self.observation.setText(
                f"현재 인식: {HANDS[label]}" if label else "한 손으로 가위·바위·보를 보여주세요."
            )

    def tick(self):
        now = time.time()
        hand = self.tracker.stable_hand(now)
        if now - self.tracker.last_time > 0.8:
            self.observation.setText("최신 손 인식을 기다리고 있어요. 카메라에 손을 보여주세요.")
        if self.state == "ready":
            if hand:
                self.state, self.deadline = "countdown", now + 3
            elif now >= self.deadline:
                self.finish_without_result("카메라와 손 위치를 확인하고 다시 시도해주세요.")
                return
        if self.state == "countdown":
            remaining = self.deadline - now
            self.title.setText(["보!", "바위…", "가위…"][min(2, max(0, math.ceil(remaining) - 1))])
            self.hint.setText("카운트다운이 끝날 때 낼 손을 잠시 유지해주세요.")
            if remaining <= 0:
                self.state, self.deadline = "waiting", now + 5
        if self.state == "waiting":
            if now >= self.deadline:
                self.finish_without_result("손을 확실하게 인식하지 못했어요. 다시 해볼까요?")
            elif hand:
                self.finish_round(hand)
            else:
                self.title.setText("손을 보여주세요!")
                self.hint.setText("한 손의 모양을 잠시 유지해주세요. 판정을 기다리고 있어요.")

    def show_hand(self, picture, hand):
        pixmap = self.images[hand]
        if pixmap.isNull():
            picture.setText(HANDS[hand])
        else:
            picture.setPixmap(pixmap.scaled(
                240, 240, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def finish_round(self, hand):
        self.timer.stop()
        self.state = "result"
        result = judge(hand, self.opponent)
        self.title.setText(result)
        self.hint.setText("다시 하기를 누르면 새로운 판을 시작합니다.")
        self.observation.setText("판정 완료")
        self.player_text.setText(f"나 · {HANDS[hand]}")
        self.opponent_text.setText(f"캐릭터 · {HANDS[self.opponent]}")
        self.show_hand(self.player_image, hand)
        self.show_hand(self.opponent_image, self.opponent)
        self.retry.setEnabled(True)
        print(f"[가위바위보] 사용자={HANDS[hand]}, 캐릭터={HANDS[self.opponent]} → {result}")

    def finish_without_result(self, message):
        self.timer.stop()
        self.state = "result"
        self.title.setText("이번 판은 판정하지 않았어요")
        self.hint.setText(message)
        self.observation.setText("승패를 기록하지 않았습니다.")
        self.retry.setEnabled(True)

    def done(self, result):
        # 닫기 버튼, X, Esc 모두 여기에서 타이머 정지와 모드 복원을 처리한다.
        self.timer.stop()
        self.state = "idle"
        if self.session and self.send_command:
            self.send_command(f"rps_end {self.session}")
        self.session = None
        super().done(result)
