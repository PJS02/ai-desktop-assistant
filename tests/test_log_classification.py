from io import StringIO
from types import SimpleNamespace

import pytest

from log_classification import classify_output


@pytest.mark.parametrize('message,is_error,expected', [
    ('INFO: Created TensorFlow Lite XNNPACK delegate for CPU.', True, ('사용자 인식', 'INFO')),
    ('2026-10-08 12:02:51.123: I tensorflow/lite: initialized', True, ('사용자 인식', 'INFO')),
    ('W0000 00:00:123 warning from mediapipe', True, ('사용자 인식', 'WARNING')),
    ('E0000 00:00:123 failure from mediapipe', True, ('사용자 인식', 'ERROR')),
    ('[STT 오류] 마이크 연결 끊김', False, ('사용자 인식', 'ERROR')),
    ('[Gemini 응답] no error today', False, ('대화·AI', 'INFO')),
    ('[Gemini 응답] 카메라와 speech recognition을 설명할게요', False, ('대화·AI', 'INFO')),
    ('[외부 음성 인식] Gemini에게 대화를 전달해줘', False, ('사용자 인식', 'INFO')),
    ('[TTS 오류] speech synthesis failed', True, ('대화·AI', 'ERROR')),
    ('[Gemini 오류] HTTP 500', True, ('대화·AI', 'ERROR')),
    ('[경고] 이미지 파일 없음', False, ('시스템', 'WARNING')),
    ('Traceback (most recent call last):', True, ('시스템', 'ERROR')),
    ('ValueError: invalid setting', True, ('시스템', 'ERROR')),
    ('some native diagnostic', True, ('시스템', 'WARNING')),
    ('some normal output', False, ('시스템', 'INFO')),
    ('Russell 좌표: Valence=+0.45, Arousal=-0.05', False, ('캐릭터 상태', 'INFO')),
    ('OCC intensity joy=0.4', False, ('캐릭터 상태', 'INFO')),
    ('  happy | ███████████░░░░░░░░░ | 0.545 ◀ 주요', False, ('캐릭터 상태', 'INFO')),
    ('[클릭 이벤트 발생]', False, ('캐릭터 상태', 'INFO')),
    ('[mousePressEvent] button=LeftButton', False, ('캐릭터 상태', 'INFO')),
])
def test_classifies_domain_and_severity_independently(message, is_error, expected):
    assert classify_output(message, is_error=is_error) == expected


def test_multiline_error_retains_its_domain():
    assert classify_output('Gemini request\nTraceback (most recent call last):\nValueError: broken') == ('대화·AI', 'ERROR')


def test_child_stderr_keeps_native_info_and_unknown_diagnostics(monkeypatch):
    import main
    recorded = []
    monkeypatch.setattr(main, 'log_event', lambda event, message, **data: recorded.append((event, message, data)))
    process = SimpleNamespace(pid=123, stderr=StringIO(
        'INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\n'
        'unknown native diagnostic\n'
        'ValueError: malformed input\n'))

    main.MediaPipeProcessManager()._forward_stderr(process)

    assert len(recorded) == 3
    assert [record[2]['level'] for record in recorded] == ['INFO', 'WARNING', 'ERROR']
    assert all(record[2]['category'] == '사용자 인식' for record in recorded)
    assert all(record[2]['stream'] == 'stderr' and record[2]['pid'] == 123 for record in recorded)
    assert recorded[1][1] == 'unknown native diagnostic'


def test_early_stderr_flush_uses_content_severity_and_keeps_the_original(monkeypatch):
    import native_log_capture
    recorded = []
    monkeypatch.setattr(native_log_capture, 'log_event', lambda event, message, **data: recorded.append((event, message, data)))
    original = StringIO()
    stream = native_log_capture._EarlyStream(original, True)
    info = 'INFO: Created TensorFlow Lite XNNPACK delegate for CPU.'
    stream.write(info + '\n')
    stream.write('unclassified partial diagnostic')
    stream.flush()

    assert original.getvalue() == info + '\nunclassified partial diagnostic'
    assert [record[2]['level'] for record in recorded] == ['INFO', 'WARNING']
    assert recorded[0][2]['category'] == '사용자 인식'
    assert all(record[2]['stream'] == 'stderr' for record in recorded)


def test_native_lines_do_not_turn_initialization_info_into_error(monkeypatch):
    import native_log_capture
    recorded = []
    monkeypatch.setattr(native_log_capture, 'log_event', lambda event, message, **data: recorded.append((event, message, data)))
    native_log_capture.StartupCapture._line(2, 'INFO: Created TensorFlow Lite XNNPACK delegate for CPU.')
    native_log_capture.StartupCapture._line(2, 'Traceback (most recent call last):')
    native_log_capture.StartupCapture._line(2, 'unknown native diagnostic')
    assert [record[2]['level'] for record in recorded] == ['INFO', 'ERROR', 'WARNING']
    assert [record[1] for record in recorded][-1] == 'unknown native diagnostic'


def test_mood_change_records_one_full_snapshot_instead_of_orphan_lines(monkeypatch):
    import character.character_widget as module
    recorded = []
    monkeypatch.setattr(module, 'log_event', lambda event, message, **data: recorded.append((event, message, data)))
    state = {'valence': .45, 'arousal': -.05}
    final_emotion = {'emotion': 'happy', 'intensity': .4}
    formatted = '[감정 상태] 현재 기분: happy\nRussell 좌표: Valence=+0.45, Arousal=-0.05\n  happy | █░ | 0.545'
    mood = SimpleNamespace(
        update_idle_pressure=lambda seconds: None,
        decay=lambda: None,
        decide_emotion=lambda: final_emotion,
        has_emotion_changed=lambda: (True, 'neutral', 'happy'),
        get_formatted_mood_log=lambda: formatted,
        get_russell_state=lambda: state,
    )
    host = SimpleNamespace(
        is_dragging=False, is_moving=False, rig_view=None,
        get_character_idle_time=lambda: 10,
        mood_system=mood, idle_counter=0,
        _maybe_run_autonomous_event=lambda seconds: None,
        update_action=lambda value: None,
    )
    module.CharacterWidget.update_mood(host)

    assert len(recorded) == 1
    event, _, data = recorded[0]
    assert event == 'mood.snapshot'
    assert data['category'] == '캐릭터 상태'
    assert data['state'] == state and data['final_emotion'] == final_emotion
    assert data['formatted_state'] == formatted
    assert data['old_emotion'] == 'neutral' and data['new_emotion'] == 'happy'
