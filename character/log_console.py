from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import sys
import threading
from typing import TextIO

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)


LOG_CATEGORIES = (
    "전체",
    "사용자 인식",
    "캐릭터 상태",
    "대화·AI",
    "시스템",
    "오류",
)


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    category: str
    message: str

    def format(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] [{self.category}] {self.message}"


def classify_log_message(message: str, is_error: bool = False) -> str:
    """기존 로그 접두사와 핵심 단어를 이용해 화면 탭을 결정한다."""
    lowered = message.lower()
    if is_error or any(
        token in lowered
        for token in ("[오류]", "[경고]", " error", "error]", "traceback", "timeout")
    ):
        return "오류"

    if any(
        token in lowered
        for token in (
            "gemini",
            "api 요청",
            "api 응답",
            "대사",
            "dialogue",
            "말풍선",
        )
    ):
        return "대화·AI"

    if any(
        token in lowered
        for token in (
            "mediapipe",
            "외부 감정",
            "외부 동작",
            "외부 고개",
            "외부 상태",
            "인식 수신기",
            "recognition",
            "speech",
            "stt",
            "음성 인식",
            "카메라",
        )
    ):
        return "사용자 인식"

    if any(
        token in lowered
        for token in (
            "점프",
            "착지",
            "애니메이션",
            "감정 상태",
            "mood",
            "idle",
            "surface",
            "on_",
            "random skip",
            "드래그",
        )
    ):
        return "캐릭터 상태"

    return "시스템"


class AppLogManager(QObject):
    """프로세스 로그를 보관하고 Qt 로그창에 스레드 안전하게 전달한다."""

    entry_added = pyqtSignal(object)
    logs_cleared = pyqtSignal()

    def __init__(self, max_entries: int = 5000) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._stdout_original: TextIO | None = None
        self._stderr_original: TextIO | None = None

    def install_capture(self) -> None:
        if self._stdout_original is not None:
            return
        self._stdout_original = sys.stdout
        self._stderr_original = sys.stderr
        sys.stdout = LogStream(self, self._stdout_original, is_error=False)
        sys.stderr = LogStream(self, self._stderr_original, is_error=True)

    def restore_capture(self) -> None:
        if self._stdout_original is None:
            return
        sys.stdout = self._stdout_original
        sys.stderr = self._stderr_original or self._stdout_original
        self._stdout_original = None
        self._stderr_original = None

    def add(self, message: str, is_error: bool = False) -> None:
        clean_message = message.strip()
        if not clean_message:
            return
        entry = LogEntry(
            timestamp=datetime.now(),
            category=classify_log_message(clean_message, is_error=is_error),
            message=clean_message,
        )
        with self._lock:
            self._entries.append(entry)
        self.entry_added.emit(entry)

    def entries(self) -> list[LogEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        self.logs_cleared.emit()


class LogStream:
    """터미널 출력을 유지하면서 완성된 줄을 AppLogManager에도 전달한다."""

    def __init__(self, manager: AppLogManager, original: TextIO, is_error: bool) -> None:
        self.manager = manager
        self.original = original
        self.is_error = is_error
        self._buffers: dict[int, str] = {}
        self._lock = threading.Lock()

    @property
    def encoding(self):
        return getattr(self.original, "encoding", "utf-8")

    def isatty(self) -> bool:
        return bool(getattr(self.original, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self.original.fileno()

    def write(self, text: str) -> int:
        written = self.original.write(text)
        thread_id = threading.get_ident()
        completed_lines: list[str] = []

        with self._lock:
            buffered = self._buffers.get(thread_id, "") + text
            pieces = buffered.splitlines(keepends=True)
            remainder = ""
            for piece in pieces:
                if piece.endswith(("\n", "\r")):
                    completed_lines.append(piece.rstrip("\r\n"))
                else:
                    remainder = piece
            self._buffers[thread_id] = remainder

        for line in completed_lines:
            self.manager.add(line, is_error=self.is_error)
        return written

    def flush(self) -> None:
        self.original.flush()


class LogWindow(QWidget):
    """카테고리 필터와 검색 도구를 제공하는 독립 로그창."""

    def __init__(self, manager: AppLogManager) -> None:
        super().__init__()
        self.manager = manager
        self.is_paused = False
        self._allow_close = False
        self.setWindowTitle("AI Desktop Assistant 로그")
        self.resize(1050, 650)

        root_layout = QVBoxLayout(self)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for category in LOG_CATEGORIES:
            self.tabs.addTab(category)
        self.tabs.currentChanged.connect(self.refresh)
        root_layout.addWidget(self.tabs)

        toolbar = QHBoxLayout()
        self.auto_scroll = QCheckBox("자동 스크롤")
        self.auto_scroll.setChecked(True)
        self.pause_button = QPushButton("일시정지")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("로그 검색")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        self.copy_button = QPushButton("복사")
        self.copy_button.clicked.connect(self.copy_logs)
        self.clear_button = QPushButton("지우기")
        self.clear_button.clicked.connect(self.manager.clear)

        toolbar.addWidget(self.auto_scroll)
        toolbar.addWidget(self.pause_button)
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(self.clear_button)
        root_layout.addLayout(toolbar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFont("Consolas", 10))
        self.output.document().setMaximumBlockCount(5000)
        root_layout.addWidget(self.output, 1)

        self.manager.entry_added.connect(self.on_entry_added)
        self.manager.logs_cleared.connect(self.output.clear)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def current_category(self) -> str:
        return LOG_CATEGORIES[self.tabs.currentIndex()]

    def matches_filters(self, entry: LogEntry) -> bool:
        category = self.current_category()
        if category != "전체" and entry.category != category:
            return False
        query = self.search_input.text().strip().lower()
        return not query or query in entry.message.lower()

    def on_entry_added(self, entry: LogEntry) -> None:
        if self.is_paused or not self.matches_filters(entry):
            return
        self.output.appendPlainText(entry.format())
        if self.auto_scroll.isChecked():
            self.output.verticalScrollBar().setValue(
                self.output.verticalScrollBar().maximum()
            )

    def refresh(self) -> None:
        if self.is_paused:
            return
        lines = [
            entry.format()
            for entry in self.manager.entries()
            if self.matches_filters(entry)
        ]
        self.output.setPlainText("\n".join(lines))
        if self.auto_scroll.isChecked():
            self.output.verticalScrollBar().setValue(
                self.output.verticalScrollBar().maximum()
            )

    def toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        self.pause_button.setText("재개" if self.is_paused else "일시정지")
        if not self.is_paused:
            self.refresh()

    def copy_logs(self) -> None:
        selected_text = self.output.textCursor().selectedText().replace("\u2029", "\n")
        QApplication.clipboard().setText(selected_text or self.output.toPlainText())

    def shutdown(self) -> None:
        self._allow_close = True
        self.close()

    def closeEvent(self, event) -> None:
        if self._allow_close:
            event.accept()
            return
        # 창을 다시 열 때 누적된 로그를 그대로 볼 수 있도록 객체는 유지한다.
        self.hide()
        event.ignore()
