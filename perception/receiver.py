from __future__ import annotations

import json
import math
import socketserver
import threading
import time
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from app_logging import log_event, log_throttled, new_trace_id


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_MESSAGE_BYTES = 1_000_000


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    # 앱을 바로 재실행해도 같은 포트를 사용할 수 있고, 연결별 작업이 종료를 막지 않게 한다.
    allow_reuse_address = True
    daemon_threads = True


class JsonLineTcpReceiver:
    """Qt 이벤트 루프와 독립적으로 동작하는 백그라운드 JSON Lines 수신기."""

    def __init__(
        self,
        on_event: Callable[[dict], None],
        on_status: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.on_event = on_event
        self.on_status = on_status or (lambda _message: None)
        self.on_error = on_error or (lambda _message: None)
        self._server: _ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: str | None = None
        self._bound_port: int | None = None
        self._traffic_logs = {}
        self._traffic_log_lock = threading.Lock()
        self._hand_lock = threading.Lock()
        self._latest_hand_frame: dict | None = None
        self._last_hand_frame: dict | None = None
        self._hand_client: str | None = None
        self._stopping = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._server is not None

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    def start(self, wait_timeout: float = 2.0) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        self._ready.clear()
        self._stopping.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._serve,
            name="perception-json-receiver",
            daemon=True,
        )
        self._thread.start()
        # 포트 바인딩 성공 여부를 호출자에게 동기적으로 알려주기 위해 잠시 기다린다.
        self._ready.wait(wait_timeout)
        return self.is_running

    def stop(self) -> None:
        self._stopping.set()
        server = self._server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._server = None
        self._thread = None
        with self._hand_lock:
            self._latest_hand_frame = self._last_hand_frame = None
            self._hand_client = None
        log_event('transport.receiver.stopped', '인식 수신기 중지', category='사용자 인식',
                  host=self.host, port=self._bound_port)

    def _serve(self) -> None:
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                client = f"{self.client_address[0]}:{self.client_address[1]}"
                log_event('transport.receiver.connected', '인식 송신기 연결', category='사용자 인식', client=client)
                owner.on_status(f"connected:{client}")
                try:
                    while not owner._stopping.is_set():
                        # 제한보다 1바이트 더 읽어 메시지가 실제로 초과했는지 판별한다.
                        raw_line = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
                        if not raw_line:
                            break
                        if len(raw_line) > MAX_MESSAGE_BYTES:
                            log_event('transport.receiver.rejected', '인식 메시지 크기 초과',
                                      category='오류', level='ERROR', client=client,
                                      size=len(raw_line), limit=MAX_MESSAGE_BYTES)
                            owner.on_error(f"message too large from {client}")
                            break
                        owner._handle_line(raw_line, client)
                finally:
                    owner._clear_hand_client(client)
                    with owner._traffic_log_lock:
                        owner._traffic_logs.pop(client, None)
                    log_event('transport.receiver.disconnected', '인식 송신기 연결 종료', category='사용자 인식', client=client)
                    owner.on_status(f"disconnected:{client}")

        try:
            with _ThreadingTcpServer((self.host, self.port), Handler) as server:
                self._server = server
                self._bound_port = int(server.server_address[1])
                self._ready.set()
                log_event('transport.receiver.listening', '인식 수신기 준비', category='사용자 인식',
                          host=self.host, port=self._bound_port)
                self.on_status(f"listening:{self.host}:{self._bound_port}")
                server.serve_forever(poll_interval=0.2)
        except OSError as exc:
            self._startup_error = str(exc)
            log_event('transport.receiver.failed', '인식 수신기 시작 실패', category='오류', level='ERROR',
                      host=self.host, port=self.port, error=str(exc))
            self.on_error(f"receiver start failed: {exc}")
            self._ready.set()
        finally:
            self._server = None

    def _handle_line(self, raw_line: bytes, client: str) -> None:
        if self._stopping.is_set():
            return
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log_event('transport.receiver.invalid', '인식 JSON 해석 실패', category='오류', level='ERROR',
                      client=client, error=str(exc), raw=raw_line.decode('utf-8', errors='replace'))
            self.on_error(f"invalid JSON from {client}: {exc}")
            return
        if not isinstance(payload, dict):
            log_event('transport.receiver.invalid', '인식 메시지 객체 형식 오류', category='오류', level='ERROR',
                      client=client, payload=payload)
            self.on_error(f"JSON message from {client} must be an object")
            return
        if payload.get('type') == 'hand_landmarks':
            if not self._valid_hand_frame(payload):
                log_throttled('transport.receiver.hand_invalid', '손 좌표 메시지 형식 오류',
                              category='오류', level='WARNING', key=f'hand-invalid:{client}',
                              client=client, session_id=payload.get('session_id'),
                              sequence=payload.get('sequence'))
                return
            self._store_hand_frame(payload, client)
            return
        trace_id = payload.get('trace_id') or payload.get('event_id') or new_trace_id('recognition')
        self._log_received(payload, client, trace_id)
        self.on_event(payload)

    @staticmethod
    def _valid_hand_frame(payload: dict) -> bool:
        def integer(value, minimum, maximum=None):
            return type(value) is int and value >= minimum and (maximum is None or value <= maximum)

        def finite_number(value):
            if type(value) not in (int, float):
                return False
            try:
                return math.isfinite(value)
            except OverflowError:
                return False

        session = payload.get('session_id')
        size = payload.get('image_size')
        hands = payload.get('hands')
        if (type(payload.get('version')) is not int or payload['version'] != 1
                or not isinstance(session, str) or not 0 < len(session) <= 128
                or not integer(payload.get('sequence'), 0)
                or not finite_number(payload.get('captured_at')) or payload['captured_at'] <= 0
                or not isinstance(size, dict)
                or not integer(size.get('width'), 1, 16384) or not integer(size.get('height'), 1, 16384)
                or type(payload.get('mirror')) is not bool
                or not isinstance(hands, list) or len(hands) > 2):
            return False
        if any(type(payload.get(flag, False)) is not bool for flag in ('clear', 'disconnected')):
            return False
        if (payload.get('clear') or payload.get('disconnected')) and hands:
            return False
        for hand in hands:
            if not isinstance(hand, dict) or hand.get('label') not in ('Left', 'Right'):
                return False
            points = hand.get('points')
            if not isinstance(points, list) or len(points) != 21:
                return False
            if any(not isinstance(point, list) or len(point) != 3
                   or not all(finite_number(value) for value in point) for point in points):
                return False
        return True

    def _store_hand_frame(self, payload: dict, client: str) -> None:
        frame = dict(payload)
        frame['_received_at'] = time.monotonic()
        with self._hand_lock:
            self._latest_hand_frame = frame
            self._last_hand_frame = dict(frame)
            self._hand_client = client

    def take_latest_hand_frame(self) -> dict | None:
        """Drain one newest display frame without emitting per-frame Qt events."""
        with self._hand_lock:
            frame, self._latest_hand_frame = self._latest_hand_frame, None
        return frame

    def _clear_hand_client(self, client: str) -> None:
        with self._hand_lock:
            # A reconnect can already be publishing while its old connection ends.
            # Disconnecting an unrelated client must not erase that newer stream.
            if client != self._hand_client or self._last_hand_frame is None:
                return
            frame = dict(self._last_hand_frame)
            frame.update(hands=[], clear=True, disconnected=True,
                         sequence=frame['sequence'] + 1, captured_at=time.time(),
                         _received_at=time.monotonic())
            self._latest_hand_frame = frame
            self._last_hand_frame = None
            self._hand_client = None

    def _log_received(self, payload, client, trace_id):
        def object_value(value):
            return value if isinstance(value, dict) else {}
        always = object_value(payload.get('always'))
        speech = object_value(payload.get('speech'))
        mode = object_value(payload.get('mode'))
        game = object_value(payload.get('rps_game'))
        emotion = object_value(payload.get('emotion')) if 'emotion' in payload else object_value(always.get('emotion'))
        # Inspect changing observations, excluding per-frame diagnostics and IDs.
        signature = json.dumps({'type': payload.get('type'),
            'wave': always.get('wave'), 'gesture': always.get('hand_gesture'),
            'head': payload.get('head_motion', always.get('head')),
            'attention': payload.get('attention', always.get('attention')),
            'motions': payload.get('motions', payload.get('motion')),
            'emotion': emotion.get('label'),
            'speech': [speech.get('session'), speech.get('sequence', speech.get('id')), speech.get('text', speech.get('latest_text'))]
                      if isinstance(payload.get('speech'), dict) else payload.get('speech'),
            'mode': mode.get('active'), 'result': mode.get('result') if mode.get('active') != 'air' else None,
            'rps_game': {'session': game.get('session'), 'hands': game.get('hands')} if game else None},
            sort_keys=True, ensure_ascii=False, default=str)
        now = time.monotonic()
        with self._traffic_log_lock:
            previous = self._traffic_logs.get(client)
            should_log = previous is None or previous[0] != signature or now - previous[1] >= 5
            if should_log:
                self._traffic_logs[client] = (signature, now, 0)
            else:
                self._traffic_logs[client] = (signature, previous[1], previous[2] + 1)
        if should_log:
            log_event('transport.receiver.received', '인식 메시지 수신', category='사용자 인식',
                      trace_id=trace_id, client=client, payload=payload,
                      repeated_packets=previous[2] if previous else 0, legacy_missing_id='trace_id' not in payload)


class QtPerceptionReceiver(QObject):
    """백그라운드 수신 결과를 Qt 신호로 전달하는 어댑터."""

    event_received = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        # TCP 스레드에서 UI를 직접 만지지 않고 Qt 신호만 발생시킨다.
        self._receiver = JsonLineTcpReceiver(
            host=host,
            port=port,
            on_event=self.event_received.emit,
            on_status=self.status_changed.emit,
            on_error=self.error_occurred.emit,
        )

    @property
    def startup_error(self) -> str | None:
        return self._receiver.startup_error

    def start(self) -> bool:
        return self._receiver.start()

    def stop(self) -> None:
        self._receiver.stop()

    def take_latest_hand_frame(self) -> dict | None:
        return self._receiver.take_latest_hand_frame()
