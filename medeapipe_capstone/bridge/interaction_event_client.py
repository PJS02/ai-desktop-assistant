#모션, 감정, 음성 인식 후 json파일로 보내는 거

from __future__ import annotations

import json
import queue
import socket
import threading
import time


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

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._close_socket()

    def send(self, event: dict) -> None:
        payload = dict(event)
        payload.setdefault("timestamp", time.time())
        try:
            self.events.put_nowait(payload)
        except queue.Full:
            pass

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
            except OSError:
                self._close_socket()
                time.sleep(0.5)

    def _ensure_socket(self) -> None:
        if self.socket is not None:
            return
        self.socket = socket.create_connection((self.host, self.port), timeout=1.0)

    def _close_socket(self) -> None:
        if self.socket is None:
            return
        try:
            self.socket.close()
        finally:
            self.socket = None
