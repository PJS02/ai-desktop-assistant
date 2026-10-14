import queue
import socket

from perception.receiver import JsonLineTcpReceiver


def test_receives_one_json_line_over_tcp():
    received = queue.Queue()
    errors = queue.Queue()
    receiver = JsonLineTcpReceiver(
        host="127.0.0.1",
        port=0,
        on_event=received.put,
        on_error=errors.put,
    )

    try:
        assert receiver.start()
        assert receiver.bound_port is not None
        with socket.create_connection(("127.0.0.1", receiver.bound_port), timeout=2.0) as client:
            client.sendall(b'{"type":"perception","version":1,"source":"test"}\n')
        assert received.get(timeout=2.0)["source"] == "test"
        assert errors.empty()
    finally:
        receiver.stop()
