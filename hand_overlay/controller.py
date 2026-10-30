"""Display the newest shared-camera hand frame on the desktop's Qt screen."""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from app_logging import log_event, log_throttled
from character.hand_overlay_options import normalize_hand_overlay_options
from .model import Hand, HandSmoother
from .renderer import DesktopHandWindow


class HandOverlayController(QObject):
    STALE_SECONDS = .35

    def __init__(self, receiver, manager, character=None, options=None, *,
                 window_factory=DesktopHandWindow, clock=time.monotonic,
                 wall_clock=time.time, screen_provider=None):
        super().__init__(character if isinstance(character, QObject) else None)
        self.receiver, self.manager = receiver, manager
        self._options = normalize_hand_overlay_options(options)
        self._factory, self._clock, self._wall_clock = window_factory, clock, wall_clock
        self._screen_provider = screen_provider or QApplication.primaryScreen
        self._smoother = HandSmoother()
        self._windows = []
        self._bindings = {}
        self._hands = ()
        self._aspect = 4 / 3
        self._session = None
        self._sequence = -1
        self._retired_sessions = []
        self._metadata = None
        self._received_at = None
        self._closed = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.poll)
        if hasattr(manager, 'process_started'):
            manager.process_started.connect(self.sync_producer)
        manager.settings_message.connect(self._process_status)
        app = QApplication.instance()
        if app is not None:
            app.screenRemoved.connect(self._screen_changed)
            app.primaryScreenChanged.connect(self._screen_changed)
        if self._options['enabled']:
            self.timer.start()

    @property
    def options(self):
        return dict(self._options)

    @property
    def window_handles(self):
        return {handle for window in self._windows for handle in window.handles}

    @property
    def visible_count(self):
        return sum(window.isVisible() for window in self._windows)

    def sync_producer(self):
        if not self._closed:
            self.receiver.take_latest_hand_frame()
            self._reset()
            self.manager.set_hand_overlay_enabled(self._options['enabled'])

    def apply_options(self, options):
        updated = normalize_hand_overlay_options(options, strict=True)
        previous = self._options
        self._options = updated
        if self._closed:
            return
        if previous['enabled'] != updated['enabled']:
            self.receiver.take_latest_hand_frame()
            self._reset()
            if updated['enabled']:
                self.timer.start()
                if not self.manager.is_running:
                    self.manager.start()  # process_started synchronizes the saved choice.
                else:
                    self.manager.set_hand_overlay_enabled(True)
            else:
                self.timer.stop()
                self.manager.set_hand_overlay_enabled(False)
        elif previous['smooth'] != updated['smooth']:
            self._reset()
        elif updated['enabled']:
            self._display(self._hands)
        log_event('hand_overlay.settings.applied', '바탕화면 손 표시 설정 적용', options=updated)

    def _process_status(self, message):
        if message.get('kind') == 'unavailable':
            self._reset()

    def _screen_changed(self, _screen):
        if not self._closed:
            # Stop every window's interpolation before Qt destroys an old QScreen.
            self._clear_display()

    def _reset(self):
        self._clear_display()
        self._session, self._sequence = None, -1
        self._retired_sessions.clear()
        self._metadata = None

    def _clear_display(self):
        self._smoother.reset()
        self._hands = ()
        self._bindings.clear()
        self._received_at = None
        for window in self._windows:
            window.clear_hand()

    def poll(self):
        if self._closed or not self._options['enabled']:
            return
        now = self._clock()
        packet = self.receiver.take_latest_hand_frame()
        if packet is not None:
            try:
                self._accept(packet, now)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                log_throttled('hand_overlay.frame.rejected', '손 좌표 형식 오류',
                              key='hand-overlay-packet', interval=10, level='WARNING', error=str(exc))
            except OSError as exc:
                self._reset()
                log_throttled('hand_overlay.display.failed', '바탕화면 손 표시 실패',
                              key='hand-overlay-display', interval=10, level='ERROR', error=str(exc))
        if self._received_at is not None and now - self._received_at > self.STALE_SECONDS:
            self._clear_display()

    @staticmethod
    def _finite(value):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError('손 좌표에 유효하지 않은 숫자가 있습니다.')
        return float(value)

    def _accept(self, packet, now):
        if packet.get('type') != 'hand_landmarks' or packet.get('version') != 1:
            raise ValueError('지원하지 않는 손 좌표 메시지입니다.')
        session = packet['session_id']
        if not isinstance(session, str) or not session or len(session) > 128:
            raise ValueError('손 인식 세션이 올바르지 않습니다.')
        received_at = self._finite(packet.get('_received_at', now))
        captured_at = self._finite(packet['captured_at'])
        if (now - received_at > self.STALE_SECONDS or received_at > now + .1
                or self._wall_clock() - captured_at > self.STALE_SECONDS
                or captured_at > self._wall_clock() + 1):
            return
        sequence = packet['sequence']
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError('손 프레임 순번이 올바르지 않습니다.')
        if session in self._retired_sessions or (session == self._session and sequence <= self._sequence):
            return
        if packet.get('clear') or packet.get('disconnected'):
            if self._session is None or session == self._session:
                self._clear_display()
                self._session, self._sequence = session, sequence
            return
        size = packet['image_size']
        width, height = self._finite(size['width']), self._finite(size['height'])
        if not (0 < width <= 20000 and 0 < height <= 20000):
            raise ValueError('손 좌표 영상 크기가 올바르지 않습니다.')
        if not isinstance(packet['mirror'], bool):
            raise ValueError('좌우 반전 값이 올바르지 않습니다.')
        entries = packet['hands']
        if not isinstance(entries, list) or len(entries) > 2:
            raise ValueError('손 개수가 올바르지 않습니다.')
        hands = []
        for entry in entries:
            label, points = entry['label'], entry['points']
            if label not in ('Left', 'Right') or not isinstance(points, list) or len(points) != 21:
                raise ValueError('손 랜드마크가 올바르지 않습니다.')
            converted = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 3:
                    raise ValueError('손 관절 좌표가 올바르지 않습니다.')
                coordinate = tuple(self._finite(value) for value in point)
                if any(abs(value) > 10 for value in coordinate):
                    raise ValueError('손 관절 좌표 범위가 올바르지 않습니다.')
                converted.append(coordinate)
            hands.append(Hand(label, tuple(converted)))
        metadata = (width, height, packet['mirror'])
        if session != self._session or metadata != self._metadata:
            retired = self._retired_sessions[:]
            if self._session is not None and session != self._session:
                retired.append(self._session)
            self._reset()
            self._retired_sessions = retired[-16:]
        self._session, self._sequence, self._metadata = session, sequence, metadata
        self._received_at, self._aspect = received_at, width / height
        filtered = self._smoother.apply(tuple(hands), received_at, self._options['smooth'])
        if not self._options['smooth']:
            filtered = tuple(Hand(hand.label, hand.points, 1 if hand.label == 'Left' else 2)
                             for hand in filtered)
        self._hands = filtered
        self._display(filtered)

    def _display(self, hands):
        screen = self._screen_provider()
        if screen is None:
            for window in self._windows:
                window.clear_hand()
            self._bindings.clear()
            return
        # Keep a currently displayed hand when both hands are present.
        ordered = sorted(hands, key=lambda hand: hand.track_id not in self._bindings)
        selected = ordered[:self._options['max_hands']]
        wanted = {hand.track_id for hand in selected}
        for track_id in list(self._bindings):
            if track_id not in wanted:
                self._bindings.pop(track_id).clear_hand()
        for hand in selected:
            window = self._bindings.get(hand.track_id)
            if window is None:
                used = list(self._bindings.values())
                window = next((candidate for candidate in self._windows if candidate not in used), None)
                if window is None:
                    window = self._factory()
                    window.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
                    self._windows.append(window)
                self._bindings[hand.track_id] = window
            window.show_hand(hand, screen, self._aspect, self._options['size_percent'] / 100,
                             False, self._options['smooth'], self._options['range_percent'])

    def stop(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        if self.manager.is_running:
            self.manager.set_hand_overlay_enabled(False)
        self._reset()
        for window in self._windows:
            window.close()
        self._windows.clear()
