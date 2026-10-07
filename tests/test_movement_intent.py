"""Regression coverage for PJS02's facing direction after native walking."""
import pytest
from PyQt6.QtWidgets import QApplication

from character import character_widget
from character.manual_control import ManualControl
from test_character_options import moving_host


def finish_wander(host, distance, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(character_widget.random, 'random', lambda: .5)
    monkeypatch.setattr(character_widget.random, 'randint', lambda low, high: distance)
    host.random_move()
    assert host.is_moving
    assert host.sprite_animator.yaw == (65 if distance > 0 else -65)
    for _ in range(1000):
        clock[0] += .016
        host._smooth_moving()
        if not host.is_moving:
            break
    assert not host.is_moving


def test_native_character_faces_front_before_any_movement():
    host = moving_host()
    host.update_action(host.mood_system.decide_emotion())
    assert host.sprite_animator.yaw == 0


@pytest.mark.parametrize('distance', [-50, 50])
def test_walk_end_and_later_mood_updates_keep_last_direction(distance, monkeypatch):
    host = moving_host()
    origin = host.x()
    finish_wander(host, distance, monkeypatch)
    assert host.x() == origin + distance
    assert host.current_action == 'idle'
    expected_yaw = 65 if distance > 0 else -65
    assert host.sprite_animator.yaw == expected_yaw
    host.mood_system.emotion = 'sadness'
    for _ in range(5):
        host.update_action(host.mood_system.decide_emotion())
    assert host.sprite_animator.yaw == expected_yaw


@pytest.mark.parametrize('preferred_yaw', [-65, 0, 65])
@pytest.mark.parametrize('distance', [-50, 50])
def test_explicit_context_direction_has_priority_after_walking(preferred_yaw, distance, monkeypatch):
    host = moving_host()
    host._set_rig_direction(preferred_yaw)
    finish_wander(host, distance, monkeypatch)
    assert host.sprite_animator.yaw == preferred_yaw


@pytest.mark.parametrize('command,yaw', [('look_left', -65), ('look_front', 0), ('look_right', 65)])
def test_manual_direction_survives_resume_and_later_walk(command, yaw, monkeypatch):
    app = QApplication.instance() or QApplication([])
    host = moving_host()
    host.manual_control = ManualControl(host)
    try:
        host.manual_control.execute(command)
        assert host.sprite_animator.yaw == yaw
        host.manual_control.execute('resume')
        assert not host.manual_control.active
        finish_wander(host, 50, monkeypatch)
        assert host.sprite_animator.yaw == yaw
    finally:
        host.manual_control.shutdown()
        app.processEvents()


def test_ball_chase_keeps_its_facing_direction_when_it_stops(monkeypatch):
    host = moving_host()
    host.move_toward_ball(700)
    assert host.sprite_animator.yaw == 65
    host._ball_chasing = False  # Same transition as the ball cooldown/close.
    host.update_action(host.mood_system.decide_emotion())
    assert host.current_action == 'idle'
    assert host.sprite_animator.yaw == 65
