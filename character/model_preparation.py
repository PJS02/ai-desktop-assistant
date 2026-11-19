"""Prepare shared memory and screen models sequentially outside the Qt thread."""

import threading

from app_logging import log_event
from context.screen_privacy import prepare as prepare_screen


class ModelPreparation:
    def __init__(self, memory, *, screen_enabled):
        self.memory = memory
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False
        self._memory_pending = True
        self._screen_enabled = bool(screen_enabled)
        self._screen_pending = self._screen_enabled
        self._screen_failed = False
        self._screen_retry = False
        log_event('screen.models.configuration', '화면 분석 사전 준비 설정',
                  category='대화·AI', enabled=self._screen_enabled)

    def start(self):
        with self._lock:
            if self._closed or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, daemon=True,
                                           name='character-model-preparation')
            self._thread.start()

    def configure_screen(self, enabled):
        enabled = bool(enabled)
        with self._lock:
            if self._closed or enabled == self._screen_enabled:
                return
            self._screen_enabled = enabled
            self._screen_pending = enabled
            self._screen_failed = False
            self._screen_retry = False
        log_event('screen.models.configuration', '화면 분석 사전 준비 설정',
                  category='대화·AI', enabled=enabled)
        if enabled:
            self.start()

    def retry_screen(self):
        with self._lock:
            if self._closed or not self._screen_enabled or not self._screen_failed:
                return False
            self._screen_failed = False
            self._screen_pending = self._screen_retry = True
        self.start()
        return True

    def close(self):
        # Model imports cannot be interrupted safely; skip subsequent work without joining on Qt.
        with self._lock:
            self._closed = True

    def _screen_cancelled(self):
        with self._lock:
            return self._closed or not self._screen_enabled

    def _run(self):
        while True:
            with self._lock:
                if not self._closed and self._memory_pending:
                    self._memory_pending = False
                    prefix, label = 'memory.model', '장기기억'
                elif not self._closed and self._screen_pending and self._screen_enabled:
                    self._screen_pending = False
                    retry, self._screen_retry = self._screen_retry, False
                    prefix, label = 'screen.models', '화면 분석'
                else:
                    self._thread = None
                    return
            log_event(prefix + '.loading', label + ' 모델 준비 시작', category='대화·AI')
            try:
                if prefix == 'memory.model':
                    self.memory.prepare()
                    ready = True
                else:
                    ready = prepare_screen(cancelled=self._screen_cancelled, reset_worker=retry)
            except Exception as exc:
                if prefix == 'screen.models':
                    with self._lock:
                        if self._closed or not self._screen_enabled or self._screen_pending:
                            continue
                        self._screen_failed = True
                    log_event(prefix + '.failed', label + ' 모델 준비 실패', category='오류',
                              level='ERROR', error_type=type(exc).__name__)
                else:
                    log_event(prefix + '.failed', label + ' 모델 준비 실패', category='오류',
                              level='ERROR', error=str(exc))
            else:
                if ready:
                    log_event(prefix + '.ready', label + ' 모델 준비 완료', category='대화·AI')
