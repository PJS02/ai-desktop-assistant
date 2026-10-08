#모션, 감정, 음성 인식 후 json파일로 보내는 거

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from app_logging import log_event, log_throttled, new_trace_id


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class InteractionEventClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.events: queue.Queue[dict] = queue.Queue(maxsize=200)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.socket: socket.socket | None = None
        self._logged_signatures = {}

    def _log_packet(self, phase, payload, **data):
        # Detailed first/changed observations plus periodic traffic summaries;
        # fluctuating model scores and air path point counts are not UI events.
        def object_value(value):
            return value if isinstance(value, dict) else {}
        always = object_value(payload.get('always'))
        speech = object_value(payload.get('speech'))
        mode = object_value(payload.get('mode'))
        game = object_value(payload.get('rps_game'))
        signature = json.dumps({'type': payload.get('type'),
            'wave': always.get('wave'), 'gesture': always.get('hand_gesture'),
            'head': always.get('head'), 'attention': always.get('attention'),
            'emotion': object_value(always.get('emotion')).get('label'),
            'speech': [speech.get('session'), speech.get('sequence')],
            'mode': mode.get('active'),
            'result': mode.get('result') if mode.get('active') != 'air' else None,
            'rps_game': {'session': game.get('session'), 'hands': game.get('hands')} if game else None},
            sort_keys=True, ensure_ascii=False, default=str)
        arguments = dict(category='사용자 인식', trace_id=payload.get('trace_id'),
                         queue_size=self.events.qsize(), payload=payload, **data)
        previous = self._logged_signatures.get(phase)
        now = time.monotonic()
        if previous is None or previous[0] != signature or now - previous[1] >= 5:
            self._logged_signatures[phase] = (signature, now, 0)
            log_event('transport.sender.' + phase, '인식 메시지 ' + phase,
                      repeated_packets=previous[2] if previous else 0, **arguments)
        else:
            self._logged_signatures[phase] = (signature, previous[1], previous[2] + 1)

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._close_socket()
        log_event('transport.sender.stopped', '인식 송신기 중지', category='사용자 인식',
                  remaining_queue=self.events.qsize())

    def send(self, event: dict) -> None:
        payload = dict(event)
        payload.setdefault("timestamp", time.time())
        payload.setdefault('event_id', new_trace_id('recognition'))
        payload.setdefault('trace_id', payload['event_id'])
        try:
            self.events.put_nowait(payload)
            self._log_packet('queued', payload)
        except queue.Full:
            log_throttled('transport.sender.dropped', '인식 전송 대기열 초과로 메시지 폐기',
                          category='오류', level='WARNING', trace_id=payload['trace_id'],
                          key=f'sender-full:{id(self)}', reason='queue_full',
                          queue_size=self.events.qsize(), payload=payload,
                          retry_scheduled=False)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                event = self.events.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._ensure_socket()
                message = json.dumps(event, ensure_ascii=False) + "\n"
                self.socket.sendall(message.encode("utf-8"))
                self._log_packet('sent', event, bytes=len(message.encode('utf-8')))
            except OSError as exc:
                log_throttled('transport.sender.failed', '인식 메시지 전송 실패 및 폐기',
                              category='오류', level='ERROR', trace_id=event.get('trace_id'),
                              key=f'sender-failed:{id(self)}', error=str(exc), payload=event,
                              retry_scheduled=False)
                self._close_socket()
                time.sleep(0.5)
            except Exception as exc:
                log_event('transport.sender.failed', '인식 메시지 직렬화/전송 작업 오류',
                          category='오류', level='ERROR', trace_id=event.get('trace_id'),
                          error=str(exc), payload=event, retry_scheduled=False)
                raise

    def _ensure_socket(self) -> None:
        if self.socket is not None:
            return
        self.socket = socket.create_connection((self.host, self.port), timeout=1.0)
        log_event('transport.sender.connected', '인식 수신기에 연결', category='사용자 인식',
                  host=self.host, port=self.port)

    def _close_socket(self) -> None:
        if self.socket is None:
            return
        try:
            self.socket.close()
        finally:
            self.socket = None
            log_event('transport.sender.disconnected', '인식 전송 연결 종료', category='사용자 인식',
                      host=self.host, port=self.port)
