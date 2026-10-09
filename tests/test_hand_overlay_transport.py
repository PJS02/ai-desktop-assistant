"""Latest hand display frames share TCP without changing semantic event delivery."""
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / 'medeapipe_capstone'
if str(MEDIAPIPE_ROOT) not in sys.path:
    sys.path.append(str(MEDIAPIPE_ROOT))

from app.holistic_gui_app import HolisticGuiApp  # noqa: E402
from bridge.interaction_event_client import InteractionEventClient  # noqa: E402
from perception.receiver import JsonLineTcpReceiver  # noqa: E402


def hand_packet(sequence=1, session='camera-session'):
    return {'type': 'hand_landmarks', 'version': 1, 'session_id': session,
            'sequence': sequence, 'captured_at': time.time(),
            'image_size': {'width': 1280, 'height': 720}, 'mirror': False,
            'hands': [{'label': 'Right', 'points': [[.4, .5, .01] for _ in range(21)]}]}


def deliver(receiver, payload, client='client-a'):
    receiver._handle_line((json.dumps(payload) + '\n').encode('utf-8'), client)


def test_sender_coalesces_hand_frames_and_preserves_semantic_fifo():
    client = InteractionEventClient()
    client.send({'type': 'recognition_state', 'sequence': 'speech-1'})
    for sequence in range(100):
        client.send_hand_frame(hand_packet(sequence))
    client.send({'type': 'recognition_state', 'sequence': 'speech-2'})
    assert client.events.qsize() == 2

    sent = []
    complete = threading.Event()

    def write(data):
        sent.append(json.loads(data))
        if len(sent) == 3:
            complete.set()

    client.socket = Mock(sendall=write)
    client.start()
    try:
        assert complete.wait(2)
    finally:
        client.stop()
        client.thread.join(2)
    assert not client.thread.is_alive()
    assert [packet['sequence'] for packet in sent if packet['type'] == 'recognition_state'] == ['speech-1', 'speech-2']
    assert [packet['sequence'] for packet in sent if packet['type'] == 'hand_landmarks'] == [99]


def test_coordinate_lane_does_not_consume_full_semantic_queue():
    client = InteractionEventClient()
    for sequence in range(client.events.maxsize):
        client.send({'type': 'recognition_state', 'sequence': sequence})
    for sequence in range(200):
        client.send(hand_packet(sequence))
    assert client.events.qsize() == client.events.maxsize
    assert client._take_hand_frame()['sequence'] == 199
    assert client._take_hand_frame() is None
    assert [client.events.get_nowait()['sequence'] for _ in range(client.events.maxsize)] == list(range(200))


def test_sender_drops_expired_coordinates_without_reconnecting():
    client = InteractionEventClient()
    client._ensure_socket = Mock()
    packet = hand_packet()
    packet['captured_at'] -= 1
    client._send_packet(packet)
    client._ensure_socket.assert_not_called()


def test_hand_packets_are_not_logged_with_coordinates(monkeypatch):
    logged = Mock()
    monkeypatch.setattr('bridge.interaction_event_client.log_event', logged)
    client = InteractionEventClient()
    client.socket = Mock()
    packet = hand_packet()
    client.send_hand_frame(packet)
    client._send_packet(client._take_hand_frame())
    assert logged.call_count == 0
    client.socket.sendall.assert_called_once()


def test_receiver_replaces_frames_without_semantic_callback():
    semantic = []
    receiver = JsonLineTcpReceiver(on_event=semantic.append)
    for sequence in range(100):
        deliver(receiver, hand_packet(sequence))
    deliver(receiver, {'type': 'recognition_state', 'speech': {'sequence': 3}})
    assert semantic == [{'type': 'recognition_state', 'speech': {'sequence': 3}}]
    frame = receiver.take_latest_hand_frame()
    assert frame['sequence'] == 99
    assert frame['_received_at'] <= time.monotonic()
    assert receiver.take_latest_hand_frame() is None


def test_real_tcp_keeps_newest_hand_packet_and_semantic_order():
    semantic = queue.Queue()
    receiver = JsonLineTcpReceiver(on_event=semantic.put, port=0)
    try:
        assert receiver.start()
        with socket.create_connection(('127.0.0.1', receiver.bound_port), timeout=2) as client:
            packets = [{'type': 'recognition_state', 'sequence': 'speech-1'}]
            packets += [hand_packet(sequence) for sequence in range(60)]
            packets += [{'type': 'recognition_state', 'sequence': 'speech-2'}]
            client.sendall(''.join(json.dumps(packet) + '\n' for packet in packets).encode('utf-8'))
            assert semantic.get(timeout=2)['sequence'] == 'speech-1'
            # This later semantic event is a barrier for all preceding TCP frames.
            assert semantic.get(timeout=2)['sequence'] == 'speech-2'
            frame = receiver.take_latest_hand_frame()
            assert frame['sequence'] == 59
            assert receiver.take_latest_hand_frame() is None
            assert semantic.empty()
    finally:
        receiver.stop()


@pytest.mark.parametrize('malformation', ['points_count', 'nan', 'huge_integer', 'boolean_sequence',
                                         'missing_mirror', 'invalid_label', 'zero_width', 'clear_with_pose'])
def test_malformed_hand_packets_do_not_replace_good_frame_or_enter_semantic_lane(malformation):
    semantic = []
    receiver = JsonLineTcpReceiver(on_event=semantic.append)
    deliver(receiver, hand_packet(1))
    malformed = hand_packet(2)
    if malformation == 'points_count':
        malformed['hands'][0]['points'].pop()
    elif malformation == 'nan':
        malformed['hands'][0]['points'][8][0] = float('nan')
    elif malformation == 'huge_integer':
        malformed['hands'][0]['points'][8][0] = 10 ** 400
    elif malformation == 'boolean_sequence':
        malformed['sequence'] = True
    elif malformation == 'missing_mirror':
        malformed.pop('mirror')
    elif malformation == 'invalid_label':
        malformed['hands'][0]['label'] = 'Other'
    elif malformation == 'zero_width':
        malformed['image_size']['width'] = 0
    elif malformation == 'clear_with_pose':
        malformed['clear'] = True
    deliver(receiver, malformed)
    assert receiver.take_latest_hand_frame()['sequence'] == 1
    assert semantic == []


def test_disconnect_only_clears_latest_producer_connection():
    receiver = JsonLineTcpReceiver(on_event=Mock())
    deliver(receiver, hand_packet(8), 'old-connection')
    deliver(receiver, hand_packet(9), 'new-connection')
    receiver._clear_hand_client('old-connection')
    assert receiver.take_latest_hand_frame()['sequence'] == 9
    receiver._clear_hand_client('unrelated-client')
    assert receiver.take_latest_hand_frame() is None
    receiver._clear_hand_client('new-connection')
    clear = receiver.take_latest_hand_frame()
    assert clear['hands'] == []
    assert clear['disconnected'] is True and clear['clear'] is True
    assert clear['sequence'] == 10
    assert clear['session_id'] == 'camera-session'


def make_producer():
    producer = HolisticGuiApp.__new__(HolisticGuiApp)
    producer.hand_overlay_enabled = False
    producer.hand_overlay_session = 'camera-session'
    producer.hand_overlay_sequence = 0
    producer.hand_overlay_image_size = (640, 480)
    producer.mirror_var = Mock(**{'get.return_value': False})
    producer.event_client = Mock()
    producer.cap = Mock()
    points = [SimpleNamespace(x=.3 + i * .001, y=.5, z=-.02) for i in range(21)]
    results = SimpleNamespace(left_hand_landmarks=None,
                              right_hand_landmarks=SimpleNamespace(landmark=points))
    return producer, results


def test_producer_exports_existing_landmarks_only_after_opt_in_and_clears_on_disable():
    producer, results = make_producer()
    producer.send_hand_landmarks(results, 640, 480, 100.0)
    producer.event_client.send_hand_frame.assert_not_called()
    producer.set_hand_overlay_enabled(True)
    new_session = producer.hand_overlay_session
    assert new_session != 'camera-session'
    producer.send_hand_landmarks(results, 640, 480, 123.0)
    exported = producer.event_client.send_hand_frame.call_args.args[0]
    assert exported['captured_at'] == 123.0
    assert exported['session_id'] == new_session and exported['sequence'] == 1
    assert exported['hands'][0]['points'][8] == [.308, .5, -.02]
    assert results.right_hand_landmarks.landmark[8].x == .308
    producer.set_hand_overlay_enabled(False)
    clear = producer.event_client.send_hand_frame.call_args.args[0]
    assert clear['clear'] is True and clear['hands'] == [] and clear['sequence'] == 2
    assert clear['session_id'] == new_session
    producer.send_hand_landmarks(results, 640, 480, 124.0)
    assert producer.event_client.send_hand_frame.call_count == 2


def test_camera_release_clears_overlay_and_pending_capture():
    producer, _ = make_producer()
    producer.hand_overlay_enabled = True
    producer.pending_frame = object()
    producer.pending_frame_captured_at = 123.0
    camera = producer.cap
    producer.release_camera()
    camera.release.assert_called_once()
    assert producer.cap is None and producer.pending_frame is None
    assert producer.pending_frame_captured_at is None
    clear = producer.event_client.send_hand_frame.call_args.args[0]
    assert clear['clear'] is True and clear['hands'] == []


def test_exact_stdin_commands_enable_and_disable_overlay():
    producer, _ = make_producer()
    producer.root = Mock()
    producer.is_shutting_down = False
    producer.control_commands = queue.Queue()
    producer.set_hand_overlay_enabled = Mock()
    for command in ('hand_overlay 1', 'hand_overlay 0', 'hand_overlay 2'):
        producer.control_commands.put(command)
    producer.poll_control_commands()
    assert [call.args for call in producer.set_hand_overlay_enabled.call_args_list] == [(True,), (False,)]
