from __future__ import annotations

import json
import socketserver
import threading
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_MESSAGE_BYTES = 1_000_000


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class JsonLineTcpReceiver:
    """Background JSON Lines TCP receiver with no Qt event-loop dependency."""

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
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._serve,
            name="perception-json-receiver",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(wait_timeout)
        return self.is_running

    def stop(self) -> None:
        server = self._server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._server = None
        self._thread = None

    def _serve(self) -> None:
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                client = f"{self.client_address[0]}:{self.client_address[1]}"
                owner.on_status(f"connected:{client}")
                try:
                    while True:
                        raw_line = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
                        if not raw_line:
                            break
                        if len(raw_line) > MAX_MESSAGE_BYTES:
                            owner.on_error(f"message too large from {client}")
                            break
                        owner._handle_line(raw_line, client)
                finally:
                    owner.on_status(f"disconnected:{client}")

        try:
            with _ThreadingTcpServer((self.host, self.port), Handler) as server:
                self._server = server
                self._bound_port = int(server.server_address[1])
                self._ready.set()
                self.on_status(f"listening:{self.host}:{self._bound_port}")
                server.serve_forever(poll_interval=0.2)
        except OSError as exc:
            self._startup_error = str(exc)
            self.on_error(f"receiver start failed: {exc}")
            self._ready.set()
        finally:
            self._server = None

    def _handle_line(self, raw_line: bytes, client: str) -> None:
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.on_error(f"invalid JSON from {client}: {exc}")
            return
        if not isinstance(payload, dict):
            self.on_error(f"JSON message from {client} must be an object")
            return
        self.on_event(payload)


class QtPerceptionReceiver(QObject):
    """Qt signal adapter for the background TCP receiver."""

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
