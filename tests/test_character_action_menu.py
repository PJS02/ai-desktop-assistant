"""Production mouse dispatch, four action states, and desktop menu geometry."""
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QSettings, QSize, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ai import gemini_client
from character import character_widget, config_manager, dialogue_system
from character.action_menu import action_menu_position
from character.character_widget import CharacterWidget
from character.tts_service import SupertonicTTS
from hand_overlay.interaction_host import CharacterHandActions


@pytest.fixture
def character(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('CLOUDY_RENDERER', 'sprite')
    monkeypatch.setattr(character_widget, 'HAS_PYGETWINDOW', False)
    monkeypatch.setattr(character_widget, 'CHARACTER_ITEMS_DIRECTORY', tmp_path / 'held-items')
    monkeypatch.setattr(character_widget.QtPerceptionReceiver, 'start', lambda self: False)
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', tmp_path / 'config.json')
    ai_path = tmp_path / 'ai.json'
    ai_path.write_text('{"api_key":"","model":"test"}', encoding='utf-8')
    monkeypatch.setattr(gemini_client, 'CONFIG_PATH', ai_path)
    monkeypatch.setattr(gemini_client, 'LEGACY_CONFIG_PATHS', ())
    voice = QSettings(str(tmp_path / 'voice.ini'), QSettings.Format.IniFormat)
    voice.setValue('tts/enabled', False)
    monkeypatch.setattr(dialogue_system, 'SupertonicTTS', lambda: SupertonicTTS(settings=voice))
    host = CharacterWidget(screen_width=1920, screen_height=1080,
                           dialogue_options={'auto_program_detection': False})
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    host.show_debug = False
    for name in ('timer', 'emotion_timer', 'move_timer', 'drag_timer', '_move_timer',
                 '_gravity_timer', '_activity_monitor_timer'):
        getattr(host, name).stop()
    host.animation_controller.stop()
    host.automatic_actions.timer.stop()
    host.on_ground = True
    host.move(500, 350)
    host.show()
    host._taskbar_visibility_timer.stop()
    app.processEvents()
    yield host, app
    if host.action_menu is not None:
        host.action_menu.dismiss('test_end')
    if host.sandbox_manager.ball is not None:
        host.sandbox_manager.ball.close()
    host.close()


def double_click(host):
    point = host._physics_body_rect().center()
    QTest.mouseClick(host, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(host, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, pos=point)


def test_double_click_opens_after_second_release_without_click_mood_or_drag(character):
    host, app = character
    before = dict(host.mood_system.occ_intensities)
    host.mood_system.on_click = Mock(wraps=host.mood_system.on_click)
    host.sandbox_manager.use_selected_item = Mock()
    point = host._physics_body_rect().center()
    QTest.mouseClick(host, Qt.MouseButton.LeftButton, pos=point)
    assert host._pending_tap and not host.is_dragging
    QTest.mouseDClick(host, Qt.MouseButton.LeftButton, pos=point)
    assert host.action_menu is None
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert host.action_menu.isVisible() and len(host.action_menu.buttons) == 4
    assert not host.is_dragging and not host._single_click_timer.isActive()
    host.mood_system.on_click.assert_not_called()
    host.sandbox_manager.use_selected_item.assert_not_called()
    assert host.mood_system.occ_intensities == before


def test_single_click_keeps_one_delayed_reaction_and_does_not_start_drag(character):
    host, _ = character
    host._single_click_timer.setInterval(1)
    host.mood_system.on_click = Mock(wraps=host.mood_system.on_click)
    point = host._physics_body_rect().center()
    QTest.mouseClick(host, Qt.MouseButton.LeftButton, pos=point)
    host.mood_system.on_click.assert_not_called()
    assert not host.is_dragging
    host._single_click_timer.start(1)
    QTest.qWait(30)
    host.mood_system.on_click.assert_called_once()
    assert not host._pending_tap and host.action_menu is None


def test_drag_starts_at_movement_threshold_without_waiting_for_click_timer(character):
    host, app = character
    host.mood_system.on_click = Mock(wraps=host.mood_system.on_click)
    point = host._physics_body_rect().center()
    QTest.mousePress(host, Qt.MouseButton.LeftButton, pos=point)
    assert not host.is_dragging
    start = host.pos()
    local = point + QPoint(32, -20)
    app.sendEvent(host, QMouseEvent(QEvent.Type.MouseMove, QPointF(local),
        QPointF(host.mapToGlobal(local)), Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert host.is_dragging and host.pos() == start + QPoint(32, -20)
    host.mood_system.on_click.assert_called_once()
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, pos=point)
    assert not host.is_dragging and not host._pending_tap
    assert host.action_menu is None


def test_moving_after_second_press_drags_instead_of_opening_menu(character):
    host, app = character
    point = host._physics_body_rect().center()
    QTest.mouseClick(host, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(host, Qt.MouseButton.LeftButton, pos=point)
    local = point + QPoint(25, 0)
    app.sendEvent(host, QMouseEvent(QEvent.Type.MouseMove, QPointF(local),
        QPointF(host.mapToGlobal(local)), Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert host.is_dragging and not host._double_click_pending
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, pos=point)
    assert host.action_menu is None and not host.is_dragging


def test_menu_remains_open_until_escape_and_keyboard_selects_one_action(character):
    host, app = character
    host.select_ball = Mock()
    double_click(host)
    menu = host.action_menu
    QTest.qWait(200)
    assert menu.isVisible()
    QTest.keyClick(menu.buttons['talk'], Qt.Key.Key_Escape)
    assert not menu.isVisible()
    host.toggle_action_menu()
    menu.buttons['ball'].setFocus()
    QTest.keyClick(menu.buttons['ball'], Qt.Key.Key_Return)
    app.processEvents()
    host.select_ball.assert_called_once()
    assert not menu.isVisible()


def test_double_click_again_closes_and_does_not_reopen(character):
    host, app = character
    double_click(host)
    assert host.action_menu.isVisible()
    double_click(host)
    app.processEvents()
    assert not host.action_menu.isVisible() and not host._pending_tap


def test_talk_selection_reuses_existing_input_and_preserves_the_draft(character):
    host, app = character
    host.toggle_action_menu()
    QTest.mouseClick(host.action_menu.buttons['talk'], Qt.MouseButton.LeftButton)
    app.processEvents()
    input_widget = host.dialogue_system.current_input_widget
    assert input_widget.isVisible()
    input_widget.input_field.setText('작성 중인 문장')
    host.toggle_action_menu()
    QTest.mouseClick(host.action_menu.buttons['talk'], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert host.dialogue_system.current_input_widget is input_widget
    assert input_widget.input_field.text() == '작성 중인 문장'


def test_ball_selection_spawns_once_then_becomes_remove_and_clears_the_session(character):
    host, app = character
    host.toggle_action_menu()
    menu = host.action_menu
    QTest.mouseClick(menu.buttons['ball'], Qt.MouseButton.LeftButton)
    menu.select_action('ball')  # A second click before the queued action runs is ignored.
    app.processEvents()
    ball = host.sandbox_manager.ball
    assert ball is not None and ball.isVisible()
    ball.physics_timer.stop()
    host.sandbox_manager._warmup_timer.stop()
    host.toggle_action_menu()
    assert menu.buttons['ball'].text() == '공\n치우기'
    QTest.mouseClick(menu.buttons['ball'], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert host.sandbox_manager.ball is None and not ball.isVisible()
    assert not host._ball_session_active


@pytest.mark.parametrize('kind,initial,completed', [('rps', 'countdown', 'result'),
                                                 ('cham', 'ready', 'finished')])
def test_game_icon_starts_stops_and_restarts_the_existing_game(character, kind, initial, completed):
    host, app = character
    host._rps_command_callback = Mock(return_value=True)
    host._play_game_cue = Mock()
    host.toggle_action_menu()
    menu = host.action_menu
    QTest.mouseClick(menu.buttons[kind], Qt.MouseButton.LeftButton)
    app.processEvents()
    game = getattr(host, kind + '_game')
    game.timer.stop()
    assert game.isVisible() and game.state == initial
    first_session = game.session
    host.toggle_action_menu()
    assert '끝내기' in menu.buttons[kind].text()
    QTest.mouseClick(menu.buttons[kind], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not game.isVisible() and game.state == 'idle'
    host.toggle_action_menu()
    QTest.mouseClick(menu.buttons[kind], Qt.MouseButton.LeftButton)
    app.processEvents()
    game.timer.stop()
    assert game.session != first_session and game.state == initial
    game.state = completed
    host.toggle_action_menu()
    assert '다시 하기' in menu.buttons[kind].text()
    previous = game.session
    QTest.mouseClick(menu.buttons[kind], Qt.MouseButton.LeftButton)
    app.processEvents()
    game.timer.stop()
    assert game.session != previous and game.state == initial


def test_airborne_cham_is_disabled_then_reenabled_on_landing(character):
    host, _ = character
    host.on_ground = False
    host.toggle_action_menu()
    menu = host.action_menu
    assert not menu.buttons['cham'].isEnabled()
    assert '착지' in menu.buttons['cham'].toolTip()
    host.on_ground = True
    menu.refresh()
    assert menu.buttons['cham'].isEnabled()


def test_cham_restart_also_waits_for_landing_while_active_game_can_still_be_ended(character):
    host, app = character
    host._rps_command_callback = Mock(return_value=True)
    host._play_game_cue = Mock()
    host.show_cham_game()
    host.cham_game.timer.stop()
    host.on_ground = False
    host.toggle_action_menu()
    menu = host.action_menu
    assert menu.buttons['cham'].isEnabled() and '끝내기' in menu.buttons['cham'].text()
    host.cham_game.state = 'finished'
    menu.refresh()
    assert not menu.buttons['cham'].isEnabled() and '다시 하기' in menu.buttons['cham'].text()


def test_menu_pauses_autonomous_walk_and_ball_chase_but_keeps_emotion_updates(character):
    host, _ = character
    host.is_moving = True
    host._move_timer.start(16)
    double_click(host)
    assert not host.is_moving and not host._move_timer.isActive()
    start = host.pos()
    host.random_move()
    host.move_toward_ball(1500)
    host.on_animation_position_changed(start + QPoint(15, 0))
    assert host.pos() == start and not host.is_moving and not host._ball_chasing
    host.mood_system.on_interaction('user_heart')
    host.advance_emotion()
    assert any(host.mood_system.occ_intensities.values())


def test_mouse_press_and_click_wait_block_a_new_hand_hold(character):
    host, _ = character
    actions = CharacterHandActions(host)
    assert actions.available()
    point = host._physics_body_rect().center()
    QTest.mousePress(host, Qt.MouseButton.LeftButton, pos=point)
    assert not actions.available()
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, pos=point)
    assert not actions.available()
    host._finish_pending_click()
    assert actions.available()


def test_failed_action_can_be_retried_and_shutdown_discards_queued_action(character):
    host, app = character
    host.select_ball = Mock(side_effect=ValueError('test start failure'))
    host.dialogue_system.show_dialogue = Mock()
    host.toggle_action_menu()
    menu = host.action_menu
    menu.select_action('ball')
    app.processEvents()
    assert not menu._dispatching
    host.select_ball = Mock()
    host.toggle_action_menu()
    menu.select_action('ball')
    host._character_closing = True
    app.processEvents()
    host.select_ball.assert_not_called()


def test_right_click_keeps_management_and_retry_actions_and_hides_the_icons(character):
    host, _ = character
    host.dialogue_system._last_failed_input = {'text': '재시도'}
    host.toggle_action_menu()
    host._show_context_menu(host.mapToGlobal(host.rect().center()), include_dialogue=True)
    assert not host.action_menu.isVisible()
    actions = {action.text() for action in host._context_menu.actions()}
    assert {'설정', '로그창 보기', '사용자인식 콘솔', '감정 판단 근거 보기', '실패한 대화 다시 보내기'} <= actions
    assert not {'대화하기', '가위바위보 하기', '참참참 하기', '공 꺼내기'} & actions
    host._context_menu.close()


@pytest.mark.parametrize('available', [QRect(0, 0, 1280, 720), QRect(-1536, -120, 1536, 864)])
def test_menu_geometry_stays_on_screen_at_corners_and_avoids_visible_bubbles(available):
    size = QSize(306, 100)
    for x in (available.left(), available.right() - 149):
        for y in (available.top(), available.bottom() - 199):
            body = QRect(x, y, 150, 200)
            menu = QRect(action_menu_position(body, size, available), size)
            assert available.contains(menu) and not menu.intersects(body)
    body = QRect(available.left() + 400, available.top() + 400, 150, 200)
    bubble = QRect(body.left() - 40, body.top() - 120, 260, 110)
    menu = QRect(action_menu_position(body, size, available, [bubble]), size)
    assert available.contains(menu) and not menu.intersects(body) and not menu.intersects(bubble)
