# json 파일 실시간으로 받는 예시 코드

from __future__ import annotations

import json
import socketserver
from datetime import datetime


HOST = "127.0.0.1"
PORT = 8765


class JsonLineHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"[connected] {client}")
        try:
            for raw_line in self.rfile:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self.print_event(client, line)
        finally:
            print(f"[disconnected] {client}")

    def print_event(self, client: str, line: str) -> None:
        received_at = datetime.now().strftime("%H:%M:%S")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print(f"[{received_at}] {client} invalid json: {line}")
            return

        event_type = event.get("type", "unknown")
        print(f"\n[{received_at}] {event_type}")
        print(json.dumps(event, ensure_ascii=False, indent=2))


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> None:
    with ThreadingTcpServer((HOST, PORT), JsonLineHandler) as server:
        print(f"Listening for JSON Lines on {HOST}:{PORT}")
        print("Send one JSON object per line. Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping receiver.")


if __name__ == "__main__":
    main()
