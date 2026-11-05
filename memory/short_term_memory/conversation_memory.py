"""앱 실행 중 최근 대화를 보관하는 스레드 안전 단기기억 모듈."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Deque, Literal


# 저장 가능한 화자. 프롬프트에서 사용자와 AI 발화를 구분한다.
Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class MemoryMessage:
    """대화 한 건. 앱을 종료하면 함께 사라진다."""

    role: Role
    content: str
    created_at: datetime


class ConversationMemory:
    """최근 대화를 제한된 크기로 메모리에만 보관한다."""

    def __init__(self, max_messages: int = 12, max_context_chars: int = 4_000):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        if max_context_chars < 1:
            raise ValueError("max_context_chars must be at least 1")
        # AI 프롬프트가 너무 길어지지 않도록 문맥 글자 수를 제한한다.
        self.max_context_chars = max_context_chars
        # deque(maxlen)는 새 메시지가 들어올 때 가장 오래된 메시지를 자동 제거한다.
        self._messages: Deque[MemoryMessage] = deque(maxlen=max_messages)
        # AI 응답은 별도 스레드에서 오므로, 동시 접근을 잠근다.
        self._lock = RLock()

    def add(self, role: Role, content: str) -> None:
        """비어 있지 않은 사용자 또는 AI 메시지를 저장한다."""
        if role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        content = content.strip()
        if not content:
            return
        with self._lock:
            # UTC 시간을 함께 저장하면 이후 장기기억 기능에서 정렬·분석할 수 있다.
            self._messages.append(MemoryMessage(role, content, datetime.now(timezone.utc)))

    def recent(self) -> list[MemoryMessage]:
        """가장 오래된 메시지부터 복사본으로 반환한다."""
        with self._lock:
            return list(self._messages)

    def build_context(self) -> str:
        """최근 메시지를 AI 프롬프트에 넣을 문자열로 만든다."""
        with self._lock:
            lines = [f"{'사용자' if item.role == 'user' else 'AI'}: {item.content}" for item in self._messages]
        selected: list[str] = []
        used = 0
        # 최신 대화부터 담는다. 한도를 넘으면 더 오래된 대화는 제외한다.
        for line in reversed(lines):
            extra = len(line) + (1 if selected else 0)
            if selected and used + extra > self.max_context_chars:
                break
            # 메시지 하나가 한도보다 길면, 가장 최근 부분만 남긴다.
            if not selected and len(line) > self.max_context_chars:
                selected.append(line[-self.max_context_chars:])
                break
            selected.append(line)
            used += extra
        # 최신순으로 고른 목록을 원래 대화 순서로 되돌린다.
        return "\n".join(reversed(selected))

    def clear(self) -> None:
        """현재 실행 중인 대화 기록을 모두 지운다."""
        with self._lock:
            self._messages.clear()
