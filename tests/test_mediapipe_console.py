from io import StringIO
from pathlib import Path
import queue
import sys
from unittest.mock import Mock


MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / "medeapipe_capstone"
if str(MEDIAPIPE_ROOT) not in sys.path:
    sys.path.append(str(MEDIAPIPE_ROOT))

from app.holistic_gui_app import HolisticGuiApp  # noqa: E402


def make_console_app():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.root = Mock()
    app.control_commands = queue.Queue()
    app.is_shutting_down = False
    return app


def test_show_and_hide_console_only_change_window_state():
    app = make_console_app()

    app.show_console()
    app.hide_console()

    app.root.deiconify.assert_called_once_with()
    app.root.state.assert_called_once_with("normal")
    app.root.lift.assert_called_once_with()
    app.root.focus_force.assert_called_once_with()
    app.root.withdraw.assert_called_once_with()


def test_command_reader_forwards_commands_and_shutdown():
    app = make_console_app()
    app.command_stream = StringIO("show\nhide\n")

    app.read_control_commands()

    assert app.control_commands.get_nowait() == "show"
    assert app.control_commands.get_nowait() == "hide"
    assert app.control_commands.get_nowait() == "shutdown"


def test_shutdown_command_closes_without_scheduling_another_poll():
    app = make_console_app()
    app.on_close = Mock()
    app.control_commands.put("shutdown")

    app.poll_control_commands()

    app.on_close.assert_called_once_with()
    app.root.after.assert_not_called()


def test_stt_speech_event_updates_text_and_sequence():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.root = Mock()
    app.stt = Mock()
    app.stt.drain_events.return_value = [("speech", "테스트 음성")]
    app.latest_speech_text = ""
    app.speech_sequence = 0
    app.send_recognition_state = Mock()

    app.poll_stt_events()

    assert app.latest_speech_text == "테스트 음성"
    assert app.speech_sequence == 1
    app.send_recognition_state.assert_called_once_with()
    app.root.after.assert_called_once_with(100, app.poll_stt_events)


def test_camera_refresh_releases_active_camera_before_full_discovery(monkeypatch):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.camera_discovery_thread = None
    app.status_var = Mock()
    app.cap = Mock()
    app.release_camera = Mock()

    thread = Mock()
    monkeypatch.setattr(
        "app.holistic_gui_app.threading.Thread",
        Mock(return_value=thread),
    )

    app.start_full_camera_discovery()

    assert app.restart_camera_after_discovery is True
    app.release_camera.assert_called_once_with()
    thread.start.assert_called_once_with()


def test_saved_bool_accepts_only_json_boolean_values():
    assert HolisticGuiApp.saved_bool({"enabled": False}, "enabled", True) is False
    assert HolisticGuiApp.saved_bool({"enabled": "false"}, "enabled", True) is True
    assert HolisticGuiApp.saved_bool({}, "enabled", False) is False


def test_recognition_mode_and_tools_are_saved_together():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.device_settings = {}
    app.active_mode = "air"
    app.rps_session = None
    app.tracking_var = Mock(**{"get.return_value": True})
    app.marker_only_var = Mock(**{"get.return_value": False})
    app.mirror_var = Mock(**{"get.return_value": True})
    app.info_overlay_var = Mock(**{"get.return_value": False})
    app.emotion_var = Mock(**{"get.return_value": True})
    app.emotion_model_var = Mock(**{"get.return_value": "EmotiEffNet B2"})
    app.always_recognition_var = Mock(**{"get.return_value": True})
    app.save_device_settings_safely = Mock()

    app.save_recognition_settings()

    assert app.device_settings["recognition"] == {
        "mode": "air",
        "tracking": True,
        "marker_only": False,
        "mirror": True,
        "info_overlay": False,
        "emotion": True,
        "emotion_model": "emotieff_b2",
        "always_recognition": True,
    }
    app.save_device_settings_safely.assert_called_once_with()


def test_emotion_model_selection_loads_both_models_and_saves_choice(monkeypatch):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.emotion_model_var = Mock()
    app.status_var = Mock()
    app.save_recognition_settings = Mock()
    old_model = Mock()
    new_model = Mock()
    monkeypatch.setattr("app.holistic_gui_app.EmotionRecognizer", Mock(return_value=old_model))
    monkeypatch.setattr("app.holistic_gui_app.EmotiEffNetB2Recognizer", Mock(return_value=new_model))

    app.emotion_model_var.get.return_value = "EmotiEffNet B2"
    app.change_emotion_model(None)
    assert app.emotion_recognizer is new_model
    assert app.loaded_emotion_model_key == "emotieff_b2"

    app.emotion_model_var.get.return_value = "MobileNetV3 (기존)"
    app.change_emotion_model(None)
    assert app.emotion_recognizer is old_model
    assert app.loaded_emotion_model_key == "mobilenet_v3"
    assert app.save_recognition_settings.call_count == 2


def test_failed_emotion_model_change_keeps_previous_model(monkeypatch):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.emotion_model_var = Mock()
    app.emotion_model_var.get.return_value = "EmotiEffNet B2"
    app.status_var = Mock()
    app.emotion_recognizer = Mock()
    app.loaded_emotion_model_label = "MobileNetV3 (기존)"
    app.loaded_emotion_model_key = "mobilenet_v3"
    monkeypatch.setattr(
        "app.holistic_gui_app.EmotiEffNetB2Recognizer",
        Mock(side_effect=FileNotFoundError("model weights")),
    )

    previous_model = app.emotion_recognizer
    app.load_emotion_model()

    assert app.emotion_recognizer is previous_model
    assert app.loaded_emotion_model_key == "mobilenet_v3"
    app.emotion_model_var.set.assert_called_once_with("MobileNetV3 (기존)")


def test_b2_keeps_its_top_class_while_legacy_model_uses_neutral_correction():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    scores = {"Happiness": 0.42, "Neutral": 0.37, "Sadness": 0.21}

    app.loaded_emotion_model_key = "emotieff_b2"
    assert app.get_emotion_display_label(scores) == "Happiness"
    assert app.get_emotion_display_label({"Happiness": 0.54, "Sadness": 0.45}) == "Happiness"
    assert app.get_emotion_display_label({"Neutral": 0.37, "Happiness": 0.22}) == "Neutral"

    app.loaded_emotion_model_key = "mobilenet_v3"
    assert app.get_emotion_display_label(scores) == "Neutral"
    assert app.get_emotion_display_label({"Happiness": 0.54, "Sadness": 0.45}) == "Neutral"


def test_game_commands_restore_previous_mode_without_saving_override():
    app = make_console_app()
    app.active_mode = None
    app.rps_session = None
    app.cap = Mock()
    app.update_mode_status = Mock()
    app.save_recognition_settings = Mock()
    app.control_commands.put("rps_begin session1")
    app.poll_control_commands()
    assert app.active_mode == "rps"
    # 다시 하기와 지연된 이전 세션 종료 명령에도 원래 모드를 유지한다.
    app.begin_rps_game("session1")
    app.end_rps_game("old-session")
    assert app.active_mode == "rps"
    app.end_rps_game("session1")
    assert app.active_mode is None
    assert app.rps_session is None
    app.save_recognition_settings.assert_not_called()


def test_rps_frames_reach_tracker_through_existing_tcp_bridge():
    from bridge.interaction_event_client import InteractionEventClient
    from perception.receiver import JsonLineTcpReceiver
    from character.rps_game import HandTracker

    received = queue.Queue()
    receiver = JsonLineTcpReceiver(received.put, port=0)
    assert receiver.start()
    client = InteractionEventClient(port=receiver.bound_port)
    client.start()
    sender = HolisticGuiApp.__new__(HolisticGuiApp)
    sender.always_results = {}
    sender.emotion_result = None
    sender.latest_speech_text = ""
    sender.speech_sequence = 0
    sender.event_client = client
    sender.last_sent_interaction_events = {}
    sender.mode_result = {"active": "rps", "result": {"left": "PAPER", "right": "NONE"}}
    tracker = HandTracker("integration", 100)
    try:
        # 같은 손이어도 매 프레임 시각이 바뀌므로 변경 감지 필터를 통과해야 한다.
        for stamp in (100.1, 100.4):
            sender.rps_sample = {"session": "integration", "captured_at": stamp,
                                 "hands": sender.mode_result["result"]}
            sender.send_recognition_state()
            payload = received.get(timeout=2)
            assert tracker.feed(payload, stamp)
        assert tracker.stable_hand(100.4) == "PAPER"
        # STT가 같은 프레임을 다시 보내더라도 게임에서는 새 관측으로 세지 않는다.
        sender.speech_sequence += 1
        sender.send_recognition_state()
        assert not tracker.feed(received.get(timeout=2), 100.5)
        assert tracker.count == 2
    finally:
        client.stop()
        receiver.stop()
