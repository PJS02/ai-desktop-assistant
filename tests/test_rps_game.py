import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QWidget
from character.rps_game import HandTracker, RpsGameDialog, RpsGameOverlay, judge


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


@pytest.fixture
def game(monkeypatch):
    app = QApplication.instance() or QApplication([])
    clock = [100.0]
    monkeypatch.setattr("character.rps_game.time.time", lambda: clock[0])
    monkeypatch.setattr("character.rps_game.secrets.choice", lambda _: "SCISSORS")
    commands = Mock(return_value=True)
    overlay = RpsGameOverlay(commands)
    yield overlay, clock, commands, app
    overlay.close()


def advance(overlay, clock, stamp):
    clock[0] = stamp
    overlay.tick()


def feed(overlay, clock, stamp, hand="ROCK", **kwargs):
    clock[0] = stamp
    overlay.handle_payload(sample(stamp, left=hand, session=overlay.session, **kwargs))


def test_start_has_no_dialog_or_focus_and_countdown_is_visible_immediately(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    assert RpsGameDialog is RpsGameOverlay
    assert not isinstance(overlay, QDialog)
    assert overlay.isVisible() and overlay.is_active
    assert overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not overlay.findChildren(QDialog)
    assert overlay.state == "countdown"
    assert overlay.opponent_image.text() == "3"
    for stamp, number in ((101.0, "2"), (102.0, "1")):
        advance(overlay, clock, stamp)
        assert overlay.opponent_image.text() == number
    assert all(not image.isNull() for image in overlay.images.values())
    commands.assert_called_once_with(f"rps_begin {overlay.session}")


@pytest.mark.parametrize("hand,expected", [("ROCK", "승리!"), ("PAPER", "패배!"),
                                           ("SCISSORS", "무승부!")])
def test_fresh_hand_reveals_character_then_user_result_and_auto_hides(game, hand, expected):
    overlay, clock, commands, app = game
    overlay.start_game()
    session = overlay.session
    feed(overlay, clock, 103.1, hand)
    feed(overlay, clock, 103.3, hand)
    overlay.tick()
    assert overlay.state == "reveal"
    assert overlay.title.text() == "캐릭터 · 가위"
    assert not overlay.opponent_image.pixmap().isNull()
    commands.assert_called_with(f"rps_end {session}")
    advance(overlay, clock, 104.0)
    assert overlay.state == "result"
    assert overlay.title.text() == expected
    assert "사용자 기준" in overlay.hint.text()
    advance(overlay, clock, 108.1)
    assert overlay.state == "idle"
    assert not overlay.isVisible() and not overlay.timer.isActive()
    assert commands.call_count == 2  # 결과 이후 종료 명령을 다시 보내지 않는다.


def test_countdown_frames_cannot_be_reused_at_capture(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    feed(overlay, clock, 102.5)
    feed(overlay, clock, 102.8)
    assert overlay.tracker.stable_hand(102.8) == "ROCK"
    advance(overlay, clock, 103.0)
    assert overlay.state == "waiting"
    assert overlay.tracker.stable_hand(103.0) is None
    clock[0] = 103.1
    overlay.handle_payload(sample(102.9, session=overlay.session))
    assert overlay.tracker.count == 0
    feed(overlay, clock, 103.2, "PAPER")
    feed(overlay, clock, 103.4, "PAPER")
    overlay.tick()
    assert overlay.player == "PAPER"


def test_payload_can_open_capture_before_timer_and_invalid_samples_are_ignored(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    clock[0] = 103.1
    overlay.handle_payload(None)
    assert overlay.state == "waiting"
    overlay.handle_payload(sample(103.1, session="wrong"))
    assert overlay.tracker.count == 0
    feed(overlay, clock, 103.2)
    assert overlay.tracker.count == 1


def test_no_camera_times_out_without_a_loss_and_restores_recognition(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    session = overlay.session
    advance(overlay, clock, 108.0)
    assert overlay.state == "error"
    assert overlay.result is None and overlay.player is None
    assert "다시" in overlay.title.text()
    assert "다시 시작" in overlay.hint.text()
    commands.assert_called_with(f"rps_end {session}")
    advance(overlay, clock, 114.1)
    assert not overlay.isVisible() and not overlay.timer.isActive()


def test_hand_arriving_after_deadline_is_not_scored(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    feed(overlay, clock, 107.8)
    feed(overlay, clock, 108.1)
    overlay.tick()
    assert overlay.state == "error" and overlay.result is None


def test_restart_uses_new_session_and_clears_old_choice_and_result(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    old_session = overlay.session
    feed(overlay, clock, 103.1)
    feed(overlay, clock, 103.3)
    overlay.tick()
    overlay.start_round()
    assert overlay.session != old_session
    assert overlay.state == "countdown"
    assert overlay.player is None and overlay.result is None
    assert overlay.opponent_image.text() == "3"
    clock[0] = 106.4
    overlay.handle_payload(sample(106.4, session=old_session))
    assert overlay.tracker.count == 0
    assert commands.call_args_list[1].args == (f"rps_end {old_session}",)
    commands.assert_called_with(f"rps_begin {overlay.session}")


def test_menu_end_stops_timer_and_reopen_starts_new_session(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    old_session = overlay.session
    overlay.close()
    commands.assert_called_with(f"rps_end {old_session}")
    assert not overlay.timer.isActive() and overlay.state == "idle"
    overlay.start_game()
    assert overlay.isVisible() and overlay.session != old_session


def test_restart_during_countdown_restores_previous_mode_and_starts_new_session(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    old_session = overlay.session
    overlay.start_round()
    new_session = overlay.session
    assert new_session != old_session
    assert [call.args[0] for call in commands.call_args_list] == [
        f"rps_begin {old_session}", f"rps_end {old_session}", f"rps_begin {new_session}",
    ]
    overlay.close()
    overlay.close()
    assert commands.call_count == 4
    commands.assert_called_with(f"rps_end {new_session}")


@pytest.mark.parametrize("callback", [None, Mock(return_value=False), Mock(side_effect=RuntimeError("offline"))])
def test_connection_failure_is_retryable_without_throwing(game, callback):
    overlay, clock, commands, app = game
    overlay.send_command = callback
    overlay.start_game()
    assert overlay.state == "error" and overlay.result is None
    assert "연결하지 못" in overlay.hint.text()
    assert overlay.timer.isActive()


def test_ambiguous_or_disappeared_hands_are_never_scored(game):
    overlay, clock, commands, app = game
    overlay.start_game()
    feed(overlay, clock, 103.1, right="PAPER")
    feed(overlay, clock, 103.3, right="PAPER")
    overlay.tick()
    assert overlay.state == "waiting"
    feed(overlay, clock, 103.5)
    feed(overlay, clock, 103.7)
    feed(overlay, clock, 103.8, "NONE")
    overlay.tick()
    assert overlay.state == "waiting" and overlay.player is None


def test_overlay_tracks_painted_body_on_parent_move_and_clamps_edges(game):
    overlay, clock, commands, app = game

    class Character(QWidget):
        def _physics_body_rect(self):
            return QRect(50, 60, 100, 150)

    character = Character()
    character.resize(240, 280)
    screen = app.primaryScreen().geometry()
    character.move(screen.center())
    character.show()
    anchored = RpsGameOverlay(commands, character)
    try:
        anchored.start_game()
        app.processEvents()
        initial = anchored.pos()
        character.move(character.x() - 50, character.y())
        app.processEvents()
        assert anchored.x() == initial.x() - 50
        character.move(screen.topLeft())
        app.processEvents()
        assert screen.contains(anchored.geometry())
    finally:
        anchored.close()
        character.close()
