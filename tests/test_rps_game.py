import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from character.rps_game import HandTracker, RpsGameDialog, judge


@pytest.mark.parametrize("player,opponent,expected", [
    ("ROCK", "ROCK", "무승부!"), ("ROCK", "PAPER", "캐릭터의 승리!"),
    ("ROCK", "SCISSORS", "당신의 승리!"), ("PAPER", "ROCK", "당신의 승리!"),
    ("PAPER", "PAPER", "무승부!"), ("PAPER", "SCISSORS", "캐릭터의 승리!"),
    ("SCISSORS", "ROCK", "캐릭터의 승리!"), ("SCISSORS", "PAPER", "당신의 승리!"),
    ("SCISSORS", "SCISSORS", "무승부!"),
])
def test_all_outcomes(player, opponent, expected):
    assert judge(player, opponent) == expected


def sample(stamp, left="ROCK", right="NONE", session="test"):
    return {"rps_game": {"session": session, "captured_at": stamp,
                         "hands": {"left": left, "right": right}}}


def test_requires_stable_recent_frames_and_rejects_replayed_or_ambiguous_hands():
    tracker = HandTracker("test", 100)
    assert not tracker.feed(sample(99), 100)
    assert not tracker.feed(sample(100, session="old"), 100)
    assert tracker.feed(sample(100), 100)
    assert not tracker.stable_hand(100)
    assert not tracker.feed(sample(100), 100.2)
    tracker.feed(sample(100.3), 100.3)
    assert tracker.stable_hand(100.3) == "ROCK"
    assert tracker.stable_hand(102) is None
    tracker.feed(sample(102, right="PAPER"), 102)
    assert tracker.stable_hand(102) is None
    tracker.feed(sample(102.2, left="NONE"), 102.2)
    assert tracker.stable_hand(102.2) is None


def test_dialog_round_images_retry_and_escape_restore_session(monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    clock = [100.0]
    monkeypatch.setattr("character.rps_game.time.time", lambda: clock[0])
    monkeypatch.setattr("character.rps_game.secrets.choice", lambda _: "SCISSORS")
    commands = Mock(return_value=True)
    dialog = RpsGameDialog(commands)
    dialog.show()
    dialog.start_game()
    session = dialog.session
    try:
        assert all(not image.isNull() for image in dialog.images.values())
        for stamp in (100.1, 100.4):
            clock[0] = stamp
            dialog.handle_payload(sample(stamp, session=session))
        dialog.tick()
        assert dialog.state == "countdown"
        assert dialog.opponent_image.text() == "?"
        for stamp in (103.1, 103.4):
            clock[0] = stamp
            dialog.handle_payload(sample(stamp, session=session))
        dialog.tick()
        assert dialog.state == "result"
        assert dialog.title.text() == "당신의 승리!"
        assert not dialog.opponent_image.pixmap().isNull()
        dialog.retry.click()
        assert dialog.state == "ready"
        assert dialog.tracker.stable_hand(clock[0]) is None
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        qt_app.processEvents()
        commands.assert_called_with(f"rps_end {session}")
        assert not dialog.timer.isActive()
    finally:
        dialog.close()


def test_no_camera_times_out_without_loss(monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    clock = [100.0]
    monkeypatch.setattr("character.rps_game.time.time", lambda: clock[0])
    dialog = RpsGameDialog(Mock(return_value=True))
    dialog.start_game()
    clock[0] = 131
    dialog.tick()
    assert dialog.state == "result"
    assert "판정하지" in dialog.title.text()
    assert dialog.retry.isEnabled()
    dialog.close()


def test_hand_arriving_after_deadline_is_not_scored(monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    clock = [100.0]
    monkeypatch.setattr("character.rps_game.time.time", lambda: clock[0])
    dialog = RpsGameDialog(Mock(return_value=True))
    dialog.start_game()
    dialog.state, dialog.deadline = "waiting", 105.0
    for stamp in (104.8, 105.1):
        clock[0] = stamp
        dialog.handle_payload(sample(stamp, session=dialog.session))
    dialog.tick()
    assert "판정하지" in dialog.title.text()
    dialog.close()


def test_x_close_and_reopen_use_new_session():
    qt_app = QApplication.instance() or QApplication([])
    commands = Mock(return_value=True)
    dialog = RpsGameDialog(commands)
    dialog.show()
    dialog.start_game()
    old_session = dialog.session
    dialog.close()
    commands.assert_called_with(f"rps_end {old_session}")
    assert not dialog.timer.isActive()
    dialog.show()
    dialog.start_game()
    assert dialog.session != old_session
    dialog.close()
