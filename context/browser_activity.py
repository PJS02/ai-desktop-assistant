"""Foreground tab state from the local browser extension."""
from dataclasses import dataclass
import threading
import time

from .active_window_classifier import start_url_server


_BROWSER_NAMES = {
    'chrome.exe': ('google chrome', 'chrome', 'chromium'),
    'msedge.exe': ('microsoft edge', 'edge'),
}


def tab_window_title(window_title, process):
    title = window_title.strip()
    for marker in ('\u200e', '\u200f', '\u200b', '\u200c'):
        title = title.replace(marker, '')
    tab, separator, browser = title.rpartition(' - ')
    if separator and browser.casefold() in _BROWSER_NAMES.get(process, ()):
        return tab.strip()
    return title


@dataclass(frozen=True)
class BrowserTab:
    tab_id: int
    title: str
    activity: str
    received_at: float


class BrowserActivity:
    def __init__(self):
        self._tabs = {}
        self._lock = threading.Lock()
        self._server = None
        self._retry_at = 0.0

    def receive(self, data):
        process, tab = data.get('browser'), data.get('tab')
        title, activity = data.get('title'), data.get('activity')
        if (not isinstance(process, str) or process not in _BROWSER_NAMES
                or type(tab) is not int or tab < -1 or not isinstance(title, str) or len(title) > 1024
                or not isinstance(activity, str)
                or activity not in ('', 'pdf', 'playing', 'paused', 'buffering', 'ended')):
            return False
        with self._lock:
            if tab < 0:
                self._tabs.pop(process, None)
            else:
                self._tabs[process] = BrowserTab(tab, title, activity, time.monotonic())
        return True

    def sample(self, process, window_title):
        if process not in _BROWSER_NAMES:
            return None
        now = time.monotonic()
        if self._server is None and now >= self._retry_at:
            try:
                self._server = start_url_server(8766, on_activity=self.receive)
            except OSError:
                self._retry_at = now + 10
        with self._lock:
            tab = self._tabs.get(process)
        if tab is None or not tab.title or tab_window_title(window_title, process).casefold() != tab.title.casefold():
            return None
        max_age = 3 if tab.activity in ('playing', 'buffering') else 45
        return tab if now - tab.received_at < max_age else None

    def close(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
