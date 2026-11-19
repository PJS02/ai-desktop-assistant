"""Select desktop activities from the current window and local Windows signals."""
from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import subprocess
from threading import Lock, Thread
import time

from context.active_window_classifier import get_active_window_info
from context.browser_activity import BrowserActivity, tab_window_title
from context.rules_config import get_rules
from .game_detection import game_activity_for_window
from .office_typing import OfficeTyping


_PDF_VIEWERS = {'acrobat.exe', 'acrord32.exe', 'acrord64.exe', 'sumatrapdf.exe', 'foxitreader.exe',
                'foxitpdfreader.exe', 'pdfxedit.exe', 'pdfxedit64.exe'}
_OFFICE_EDITORS = {'winword.exe', 'hwp.exe', 'hwp64.exe'}
_EDIT_CONTROLS = {'notepad.exe', 'notepad++.exe', 'obsidian.exe', 'onenote.exe'}
_DOCUMENT_EDITORS = (get_rules()['documents'] - _PDF_VIEWERS) | _OFFICE_EDITORS | _EDIT_CONTROLS | {
    'libreoffice.exe', 'soffice.bin', 'wps.exe',
}
_READERS = {'kindle.exe', 'ebook-viewer.exe', 'thorium.exe', 'freda.exe'}
_BROWSERS = get_rules()['browsers']
_PDF_TITLE = re.compile(r'\.pdf(?:\s*\*?\s*$|\s+[-–—|])', re.IGNORECASE)
_BOOK_TITLE = re.compile(r'\.(?:epub|mobi|azw3)(?:\s*$|\s+[-–—|])', re.IGNORECASE)
_MEDIA = {
    'spotify.exe': ('spotify.exe', 'spotifyab.spotifymusic_'),
    'music.ui.exe': ('microsoft.zunemusic_', 'music.ui.exe'),
    'applemusic.exe': ('applemusic.exe', 'appleinc.applemusicwin_'),
    'itunes.exe': ('itunes.exe',),
    'musicbee.exe': ('musicbee.exe', 'musicbee'),
    'foobar2000.exe': ('foobar2000.exe', 'foobar2000'),
    'aimp.exe': ('aimp.exe', 'aimp'),
}
_MUSIC_ALIASES = tuple(alias for aliases in _MEDIA.values() for alias in aliases)
_VIDEO_PLAYERS = get_rules()['media_players'] | {'video.ui.exe', 'music.ui.exe', 'mpv.exe', 'wmplayer.exe'}
_VIDEO_ALIASES = {
    'video.ui.exe': ('video.ui.exe', 'microsoft.zunevideo_'),
    'music.ui.exe': _MEDIA['music.ui.exe'],
}


@dataclass(frozen=True)
class DeskActivity:
    process: str
    window_id: int
    motion: str | None
    tab_id: int | None = None

    @property
    def session_key(self):
        return self.process, self.window_id, self.tab_id


def document_activity(process, title, tab=None):
    title = title.casefold().strip()
    if not title:
        return None
    if tab is not None and tab.activity == 'pdf':
        return 'documents'
    if process in _READERS:
        return 'reading'
    if process in _PDF_VIEWERS:
        if _BOOK_TITLE.search(title):
            return 'reading'
        if _PDF_TITLE.search(title):
            return 'documents'
        return None
    if process in _BROWSERS:
        if title.startswith(('kindle cloud reader', 'kindle for web')):
            return 'reading'
    return None


def _editable_window(process, title):
    return process in _DOCUMENT_EDITORS or (process in _BROWSERS and any(
        tag in title.casefold() for tag in (' - google docs', ' - google 문서', ' | notion', ' - notion')))


class _WindowsProbe:
    """One local worker for document focus and media status."""

    def __init__(self):
        self._requests = Queue(maxsize=1)
        self._lock = Lock()
        self._thread = self._process = self._result = self._key = None
        self._closed = False
        self._next_request = 0.0
        self._query_started = None

    def sample(self, window_id=0, *, editor=False, allow_edit=False, office=False, music=(),
               video=(), video_title=''):
        if self._closed:
            return {}
        request = (window_id if editor else 0, allow_edit, office, music, video, video_title)
        key = window_id, request
        needed = editor or music or video
        now = time.monotonic()
        if self._query_started is not None and now - self._query_started > 10:
            with self._lock:
                if self._process is not None:
                    self._process.kill()
        if needed and self._thread is None:
            self._thread = Thread(target=self._run, daemon=True, name='windows-activity-probe')
            self._thread.start()
        changed = key != self._key
        if self._thread is not None and (changed or (needed and now >= self._next_request)):
            self._key, self._next_request = key, now + 0.8
            self._send(key)
        result = self._result
        if result and result[0] == key and now - result[1] < 2.5:
            return result[2]
        return {}

    def _send(self, key):
        try:
            self._requests.put_nowait(key)
        except Full:
            try:
                self._requests.get_nowait()
            except Empty:
                pass
            self._requests.put_nowait(key)

    def _start_process(self):
        source = Path(__file__).with_name('windows_activity_probe.ps1').read_text(encoding='utf-8')
        command = base64.b64encode(source.encode('utf-16-le')).decode('ascii')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        return subprocess.Popen([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-MTA',
                                 '-EncodedCommand', command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)

    def _run(self):
        retry_at = 0.0
        try:
            while (key := self._requests.get()) is not None:
                process = self._process
                try:
                    _, (editor, allow_edit, office, music, video, video_title) = key
                    if process is None:
                        if time.monotonic() < retry_at or not (editor or music or video):
                            continue
                        with self._lock:
                            if self._closed:
                                return
                            process = self._process = self._start_process()
                    request = {'editor': editor, 'allow_edit': allow_edit, 'office': office,
                               'music': music, 'video': video, 'video_title': video_title}
                    self._query_started = time.monotonic()
                    process.stdin.write(json.dumps(request) + '\n')
                    process.stdin.flush()
                    result = json.loads(process.stdout.readline())
                    self._result = key, time.monotonic(), result
                except (OSError, ValueError):
                    self._result = None
                    self._process = None
                    if process is not None:
                        self._dispose(process)
                    retry_at = time.monotonic() + 30
                finally:
                    self._query_started = None
        finally:
            if self._process is not None:
                self._dispose(self._process)
                self._process = None

    @staticmethod
    def _dispose(process):
        if process.poll() is None:
            process.terminate()
        process.wait()
        process.stdin.close()
        process.stdout.close()

    def close(self):
        with self._lock:
            self._closed = True
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        self._send(None)


class DesktopActivityObserver:
    def __init__(self, host=None):
        self._host = host
        self._probe = _WindowsProbe()
        self._browser = BrowserActivity()
        self._typing = None
        self._video_key = None
        self._video_playing_at = 0.0

    def _watch_video(self, key, state):
        now = time.monotonic()
        if state == 'playing':
            self._video_key, self._video_playing_at = key, now
            return True
        if state == 'buffering' and key == self._video_key:
            return now - self._video_playing_at <= 1.0
        self._video_key = None
        return False

    def observe(self, lookup, game_enabled, desk_enabled):
        info = get_active_window_info(with_window=True) if os.name == 'nt' else None
        if not info:
            self.clear()
            return None
        process, window_id, title = info['process'], info['window_id'], info['title']
        tab = self._browser.sample(process, title) if desk_enabled else None
        action = document_activity(process, title, tab)
        editor = action is None and _editable_window(process, title)
        music = _MUSIC_ALIASES if info['desktop'] else _MEDIA.get(process, ())
        game_lookup = None if action or editor or music or process in _VIDEO_PLAYERS or process in _BROWSERS else lookup
        if game_enabled and (game := game_activity_for_window(info, game_lookup)):
            self.clear()
            return game
        if not desk_enabled:
            self.clear()
            return None
        browser_video = tab.activity if tab else ''
        video, video_title = (), ''
        if action is None:
            if process in _VIDEO_PLAYERS:
                video = _VIDEO_ALIASES.get(process, (process, Path(process).stem))
            elif process in _BROWSERS and tab is None and title:
                video = (process, Path(process).stem)
                video_title = tab_window_title(title, process)
        office = process in _OFFICE_EDITORS
        signals = self._probe.sample(window_id if editor or music or video else 0, editor=editor,
                                     allow_edit=process in _EDIT_CONTROLS, office=office, music=music,
                                     video=video, video_title=video_title)
        focus = signals.get('edit_focus', 0) if office and editor else 0
        if focus and self._host is not None and self._typing is None:
            self._typing = OfficeTyping(self._host)
        native_editing = self._typing.sample(window_id, focus) if self._typing is not None else False
        if editor and (signals.get('editing') or native_editing):
            action = 'writing'
        tab_id = tab.tab_id if tab else None
        video_state = (browser_video or signals.get('video', '')) if action is None and not editor else ''
        if self._watch_video((process, window_id, tab_id), video_state):
            action = 'spectate'
        if action is None and signals.get('music'):
            action = 'music'
        if action or editor:
            return DeskActivity(process, window_id, action, tab_id)

    def clear(self):
        self._video_key = None
        self._probe.sample()
        if self._typing is not None:
            self._typing.close()

    def close(self):
        self.clear()
        self._probe.close()
        self._browser.close()
