from io import StringIO

from PyQt6.QtWidgets import QApplication

from character.log_console import (
    AppLogManager,
    LogStream,
    LogWindow,
    classify_log_message,
)


def test_classifies_major_log_categories():
    assert classify_log_message("[외부 감정 인식] happy") == "사용자 인식"
    assert classify_log_message("[외부 음성 인식] 안녕하세요") == "사용자 인식"
    assert classify_log_message("[점프!] velocity_y=-15") == "캐릭터 상태"
    assert classify_log_message("[Gemini 응답] 안녕하세요") == "대화·AI"
    assert classify_log_message("[설정] 저장된 성격") == "시스템"
    assert classify_log_message("[경고] 이미지 파일 없음") == "오류"


def test_log_stream_keeps_terminal_output_and_collects_complete_lines():
    manager = AppLogManager()
    terminal = StringIO()
    stream = LogStream(manager, terminal, is_error=False)

    stream.write("첫 번째 로그")
    stream.write("\n두 번째 로그\n")

    assert terminal.getvalue() == "첫 번째 로그\n두 번째 로그\n"
    assert [entry.message for entry in manager.entries()] == [
        "첫 번째 로그",
        "두 번째 로그",
    ]


def test_clear_only_removes_collected_log_history():
    manager = AppLogManager()
    manager.add("보관할 로그")

    manager.clear()

    assert manager.entries() == []


def test_pause_stops_only_display_updates_and_resume_catches_up():
    app = QApplication.instance() or QApplication([])
    manager = AppLogManager()
    window = LogWindow(manager)

    manager.add("첫 번째 로그")
    app.processEvents()
    assert "첫 번째 로그" in window.output.toPlainText()

    window.toggle_pause()
    manager.add("일시정지 중 수집된 로그")
    app.processEvents()
    assert "일시정지 중 수집된 로그" not in window.output.toPlainText()
    assert any(entry.message == "일시정지 중 수집된 로그" for entry in manager.entries())

    window.toggle_pause()
    app.processEvents()
    assert "일시정지 중 수집된 로그" in window.output.toPlainText()
    window.shutdown()
