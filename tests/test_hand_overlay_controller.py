import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from hand_overlay.controller import HandOverlayController


class Receiver:
    def __init__(self):
        self.latest = None

    def take_latest_hand_frame(self):
        latest, self.latest = self.latest, None
        return latest


class Manager(QObject):
    settings_message = pyqtSignal(dict)
    process_started = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_running = True
        self.commands = []

    def set_hand_overlay_enabled(self, enabled):
        self.commands.append(enabled)
        return True

    def start(self):
        self.is_running = True
        self.process_started.emit()
        return True


class Window:
    def __init__(self):
        self.visible = False
        self.closed = False
        self.hand = None
        self.handles = (id(self),)
        self.calls = []

    def setAttribute(self, *_args):
        pass

    def isVisible(self):
        return self.visible

    def clear_hand(self):
        self.visible, self.hand = False, None

    def show_hand(self, *args):
        self.hand = args[0]
        self.visible = True
        self.calls.append(args)

    def close(self):
        self.closed = True
        self.clear_hand()


@pytest.fixture
def overlay():
    app = QApplication.instance() or QApplication([])
    receiver, manager = Receiver(), Manager()
    clock = [10.0]
    controller = HandOverlayController(receiver, manager, options={'enabled': True},
                                       window_factory=Window, clock=lambda: clock[0],
                                       wall_clock=lambda: 100 + clock[0],
                                       screen_provider=lambda: 'screen')
    controller.timer.stop()
    yield controller, receiver, manager, clock
    controller.stop()
    app.processEvents()


def packet(sequence=1, session='camera-a', captured_at=110., hands=None):
    if hands is None:
        hands = [{'label': 'Left', 'points': [[.4, .5, 0.] for _ in range(21)]}]
    return {'type': 'hand_landmarks', 'version': 1, 'session_id': session,
            'sequence': sequence, 'captured_at': captured_at,
            'image_size': {'width': 1280, 'height': 720}, 'mirror': False,
            'hands': hands}


def feed(overlay, message):
    controller, receiver, _manager, _clock = overlay
    receiver.latest = message
    controller.poll()


def test_range_size_settings_reach_display_and_stop_closes_native_windows(overlay):
    controller, _, manager, _ = overlay
    feed(overlay, packet())
    window = controller._windows[0]
    assert controller.visible_count == 1
    assert window.calls[-1][3:] == (1.0, False, True, 70)
    assert controller.window_handles == {id(window)}
    controller.apply_options({**controller.options, 'size_percent': 150, 'range_percent': 55})
    assert window.calls[-1][3:] == (1.5, False, True, 55)
    controller.stop()
    assert window.closed and not window.visible
    assert not controller.timer.isActive()
    assert manager.commands[-1] is False
    assert controller.window_handles == set()


def test_stale_capture_is_rejected_and_missing_stream_hides_hand(overlay):
    controller, _, _, clock = overlay
    feed(overlay, packet(captured_at=109.))
    assert controller.visible_count == 0
    feed(overlay, packet())
    assert controller.visible_count == 1
    clock[0] += .36
    controller.poll()
    assert controller.visible_count == 0


def test_old_sequences_sessions_and_other_clients_clear_cannot_replace_new_pose(overlay):
    controller, _, _, clock = overlay
    feed(overlay, packet(sequence=10))
    feed(overlay, packet(sequence=9, hands=[]))
    assert controller._sequence == 10
    feed(overlay, packet(sequence=1, session='camera-b'))
    assert controller._session == 'camera-b'
    feed(overlay, packet(sequence=11, session='camera-a'))
    assert controller._session == 'camera-b'
    feed(overlay, {**packet(session='camera-a'), 'clear': True})
    assert controller.visible_count == 1
    feed(overlay, {**packet(sequence=0, session='camera-b'), 'clear': True})
    assert controller.visible_count == 1
    feed(overlay, {**packet(sequence=2, session='camera-b'), 'clear': True})
    assert controller.visible_count == 0
    feed(overlay, packet(sequence=1, session='camera-b'))
    assert controller.visible_count == 0


def test_disable_discards_mailbox_and_process_restart_restores_subscription(overlay):
    controller, receiver, manager, _ = overlay
    feed(overlay, packet())
    controller.apply_options({**controller.options, 'enabled': False})
    assert manager.commands[-1] is False
    receiver.latest = packet(sequence=2)
    controller.apply_options({**controller.options, 'enabled': True})
    controller.timer.stop()
    assert receiver.latest is None
    assert controller.visible_count == 0
    assert manager.commands[-1] is True
    feed(overlay, packet(sequence=3))
    manager.settings_message.emit({'kind': 'unavailable'})
    assert controller.visible_count == 0
    manager.process_started.emit()
    assert manager.commands[-1] is True


def test_one_hand_selection_stays_stable_with_two_raw_hands_and_pool_is_bounded(overlay):
    controller, _, _, clock = overlay
    first = packet()['hands'][0]
    other = {'label': 'Right', 'points': [[.8, .5, 0.] for _ in range(21)]}
    feed(overlay, packet())
    selected = controller._windows[0].hand.track_id
    for index in range(2, 8):
        clock[0] += .03
        feed(overlay, packet(sequence=index, captured_at=100 + clock[0], hands=[other, first]))
    assert controller.visible_count == 1
    assert controller._windows[0].hand.track_id == selected
    controller.apply_options({**controller.options, 'max_hands': 2})
    assert controller.visible_count == 2
    assert len(controller._windows) == 2
    controller.apply_options({**controller.options, 'max_hands': 1})
    assert controller.visible_count == 1


def test_mirror_change_resets_pose_and_invalid_numeric_input_preserves_display(overlay):
    controller, _, _, _ = overlay
    feed(overlay, packet())
    old_id = controller._windows[0].hand.track_id
    feed(overlay, {**packet(sequence=2), 'mirror': True})
    assert controller._metadata[-1] is True
    assert controller._windows[0].hand.track_id != old_id
    broken = packet(sequence=3)
    broken['hands'][0]['points'][4][0] = float('nan')
    feed(overlay, broken)
    assert controller._sequence == 2
    assert controller.visible_count == 1


def test_delayed_received_frame_does_not_extend_visible_lifetime(overlay):
    controller, _, _, clock = overlay
    feed(overlay, packet())
    clock[0] += .36
    feed(overlay, {**packet(sequence=2, captured_at=100 + clock[0]), '_received_at': 10.})
    assert controller.visible_count == 0
