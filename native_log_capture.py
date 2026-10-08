"""Capture import-time Python output and native fd output before Qt loads."""
from __future__ import annotations
import codecs
import os
import sys
import threading
import traceback
from app_logging import log_event


class _EarlyStream:
    def __init__(self, original, is_error):
        self.original = original
        self.is_error = is_error
        self.buffers = {}
        self.lock = threading.Lock()
    @property
    def encoding(self):
        return getattr(self.original, 'encoding', 'utf-8')
    def fileno(self):
        return self.original.fileno()
    def isatty(self):
        return self.original.isatty()
    def write(self, text):
        result = self.original.write(text)
        thread = threading.get_ident()
        with self.lock:
            value = self.buffers.get(thread, '') + text
            lines = value.split('\n')
            self.buffers[thread] = lines.pop()
        for line in lines:
            if line.strip():
                log_event('bootstrap.stderr' if self.is_error else 'bootstrap.stdout', line.rstrip('\r'),
                          category='오류' if self.is_error else '시스템', level='ERROR' if self.is_error else 'INFO')
        return result
    def flush_pending(self, all_threads=False):
        with self.lock:
            keys = list(self.buffers) if all_threads else [threading.get_ident()]
            values = [self.buffers.pop(key, '') for key in keys]
        for value in values:
            if value.strip():
                log_event('bootstrap.partial', value, category='오류' if self.is_error else '시스템',
                          level='ERROR' if self.is_error else 'INFO', stream='stderr' if self.is_error else 'stdout')
    def flush(self):
        self.flush_pending()
        self.original.flush()


class StartupCapture:
    def __init__(self):
        self.originals = (sys.stdout, sys.stderr)
        self.redirects = []
        self.streams = []
        self.old_hook = sys.excepthook
        self.old_thread_hook = threading.excepthook
        for fd, original in zip((1, 2), self.originals):
            duplicate = read_fd = write_fd = terminal_fd = None
            terminal = None
            redirected = False
            try:
                original.flush()
                duplicate = os.dup(fd)
                read_fd, write_fd = os.pipe()
                os.dup2(write_fd, fd, inheritable=False)
                redirected = True
                self._set_windows_handle(fd)
                os.close(write_fd)
                write_fd = None
                terminal_fd = os.dup(duplicate)
                terminal = os.fdopen(terminal_fd, 'w', encoding=getattr(original, 'encoding', None) or 'utf-8', errors='replace', buffering=1)
                reader = threading.Thread(target=self._read, args=(fd, read_fd, duplicate),
                                          name=f'native-log-{fd}', daemon=True)
                reader.start()
                self.redirects.append((fd, duplicate, reader, terminal))
            except (OSError, RuntimeError, ValueError) as exc:
                if redirected and duplicate is not None:
                    try:
                        os.dup2(duplicate, fd)
                        self._set_windows_handle(fd)
                    except OSError:
                        pass
                if terminal is not None:
                    terminal.close()
                for descriptor in (read_fd, write_fd, terminal_fd, duplicate):
                    if descriptor is not None:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
                terminal = original
                log_event('logging.native_unavailable', '네이티브 출력 수집 초기화 실패', category='오류', level='WARNING', fd=fd, error=str(exc))
            self.streams.append(_EarlyStream(terminal, fd == 2))
        sys.stdout, sys.stderr = self.streams
        sys.excepthook = self._exception
        threading.excepthook = self._thread_exception

    def _read(self, fd, read_fd, duplicate):
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        buffered = ''
        try:
            while True:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    buffered += decoder.decode(b'', final=True)
                    break
                try:
                    os.write(duplicate, chunk)
                except OSError:
                    pass
                buffered += decoder.decode(chunk)
                lines = buffered.split('\n')
                buffered = lines.pop()
                for line in lines:
                    self._line(fd, line)
            if buffered:
                self._line(fd, buffered)
        except OSError as exc:
            log_event('logging.native_read_error', '네이티브 출력 수집 종료', category='오류', level='WARNING', fd=fd, error=str(exc))
        finally:
            os.close(read_fd)

    @staticmethod
    def _set_windows_handle(fd):
        if sys.platform == 'win32':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            setter = ctypes.windll.kernel32.SetStdHandle
            setter.argtypes = (wintypes.DWORD, wintypes.HANDLE)
            setter.restype = wintypes.BOOL
            if not setter((-11 if fd == 1 else -12) & 0xffffffff, msvcrt.get_osfhandle(fd)):
                raise ctypes.WinError()

    @staticmethod
    def _line(fd, line):
        if line.strip():
            log_event('native.stderr' if fd == 2 else 'native.stdout', line.rstrip('\r'),
                      category='오류' if fd == 2 else '시스템', level='WARNING' if fd == 2 else 'INFO', fd=fd)

    def _exception(self, kind, value, tb):
        log_event('application.uncaught_exception', str(value), category='오류', level='ERROR',
                  traceback=''.join(traceback.format_exception(kind, value, tb)))
        self.old_hook(kind, value, tb)

    def _thread_exception(self, args):
        log_event('application.thread_exception', str(args.exc_value), category='오류', level='ERROR',
                  thread_name=args.thread.name, traceback=''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        self.old_thread_hook(args)

    def handoff_python(self):
        """The Qt manager takes Python capture; retain only native fd readers."""
        for stream in self.streams:
            stream.flush_pending(all_threads=True)
        sys.stdout, sys.stderr = [stream.original for stream in self.streams]

    def close(self):
        for stream in self.streams:
            stream.flush_pending(all_threads=True)
        for fd, duplicate, reader, terminal in self.redirects:
            terminal.flush()
            os.dup2(duplicate, fd)
            self._set_windows_handle(fd)
        sys.stdout, sys.stderr = self.originals
        sys.excepthook = self.old_hook
        threading.excepthook = self.old_thread_hook
        for fd, duplicate, reader, terminal in self.redirects:
            reader.join(2)
            if reader.is_alive():
                log_event('logging.native_shutdown_pending', '네이티브 출력 수집 종료 지연', category='오류', level='WARNING', fd=fd)
            else:
                os.close(duplicate)
            terminal.close()
        self.redirects.clear()
