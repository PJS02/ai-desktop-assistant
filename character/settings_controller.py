from app_logging import log_event, new_trace_id
from inspect import signature

from PyQt6.QtCore import QObject, QTimer

from .ai_settings import load_ai_settings, save_ai_settings
from .config_manager import load_config, load_character_options, load_dialogue_style, save_config
from .settings_dialog import SettingsDialog
from .motion_options import DEFAULT_CHARACTER_OPTIONS


class SettingsController(QObject):
    def __init__(self, character, manager):
        super().__init__(character)
        self.character = character
        self.manager = manager
        self.dialog = None
        self.request_id = None
        self.applied_local = {}
        self.operation_id = None
        self._operations = {}
        manager.settings_message.connect(self.handle_message)
        self.load_timeout = QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.timeout.connect(self.connection_timeout)

    def show(self):
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if self.dialog is not None:
            self.dialog.deleteLater()
        self.request_id = None
        width, height, personality = load_config()
        tts = self.character.dialogue_system.tts
        try:
            ai = load_ai_settings()
            ai_error = None
        except (OSError, ValueError) as exc:
            log_event('settings.ai.load_failed', 'AI 설정을 읽지 못해 실행 중인 설정을 표시합니다.',
                      category='오류', level='ERROR', error=str(exc))
            ai = self.character.gemini_config
            ai_error = 'AI 설정 파일을 읽을 수 없습니다. 파일을 확인한 뒤 다시 열어 주세요.'
        local = {'character': {'width': width, 'height': height, 'personality': personality},
                 'voice': {'enabled': tts.enabled, 'voice_id': tts.voice_id},
                 'ai': {'api_key': ai.get('api_key', ''), 'model': ai.get('model', '')}}
        local['character'].update(load_character_options())
        local['dialogue'] = {'style': load_dialogue_style()}
        self.dialog = SettingsDialog(local, self.character)
        self.dialog.apply_requested.connect(self.apply)
        self.dialog.apply_timeout.connect(self._apply_timed_out)
        self.dialog.refresh_requested.connect(self.refresh)
        self.dialog.character_command_requested.connect(self.character.manual_control.execute)
        self.character.manual_control.status_changed.connect(self.dialog.set_manual_status)
        self.dialog.set_manual_status(self.character.manual_control.status)
        self.dialog.display_emotion_requested.connect(self.character.manual_control.set_display_emotion)
        self.character.manual_control.display_emotion_changed.connect(self.dialog.set_display_emotion_state)
        self.dialog.set_display_emotion_state(self.character.manual_control.display_emotion or '')
        if ai_error:
            self.dialog.status.setText(ai_error)
            self.dialog.api_key.setEnabled(False)
            self.dialog.model.setEnabled(False)
        self.dialog.show()
        self.refresh(False)

    def refresh(self, devices=False):
        if self.dialog.pending:
            return
        self.dialog.remote_status.setText('장치를 검색하는 중…' if devices else '현재 설정을 불러오는 중…')
        self.dialog.refresh_button.setEnabled(False)
        log_event('settings.refresh.requested', '인식 설정을 요청합니다.', devices=devices)
        if not self.manager.request_settings(devices):
            self.connection_timeout()
        else:
            self.load_timeout.start(45000)

    def connection_timeout(self):
        log_event('settings.refresh.unavailable', '인식 설정 응답을 확인하지 못했습니다.',
                  level='WARNING', reason='not_connected_or_timeout')
        if self.dialog is not None:
            self.dialog.remote_unavailable('인식 기능에 연결하지 못했습니다. 장치 새로고침으로 다시 연결할 수 있습니다.')
            self.dialog.refresh_button.setEnabled(True)

    def _apply_timed_out(self, operation_id):
        if operation_id in self._operations:
            self._operations[operation_id] = 'unknown'

    def apply(self, changes):
        self.applied_local = {}
        self.operation_id = new_trace_id('settings')
        if len(self._operations) >= 256:
            self._operations.pop(next(iter(self._operations)))
        self._operations[self.operation_id] = 'applying'
        self.dialog.log_trace_id = self.operation_id
        log_event('settings.apply.started', '설정 적용을 시작합니다.', trace_id=self.operation_id,
                  changed_fields=changes)
        try:
            for section, value in changes['local'].items():
                if section == 'character':
                    options = {key: value[key] for key in DEFAULT_CHARACTER_OPTIONS}
                    save_config(value['width'], value['height'], value['personality'],
                                character_options=options, trace_id=self.operation_id)
                    apply_runtime = self.character.apply_character_settings
                    runtime_options = dict(options)
                    try:
                        accepts_trace = 'trace_id' in signature(apply_runtime).parameters
                    except (TypeError, ValueError):
                        accepts_trace = False
                    if accepts_trace:
                        runtime_options['trace_id'] = self.operation_id
                    apply_runtime(value['width'], value['height'], value['personality'], **runtime_options)
                elif section == 'voice':
                    tts = self.character.dialogue_system.tts
                    tts.set_voice(value['voice_id'])
                    tts.set_enabled(value['enabled'])
                    tts.sync_settings()
                elif section == 'dialogue':
                    width, height, personality = load_config()
                    save_config(width, height, personality, dialogue_style=value['style'],
                                trace_id=self.operation_id)
                    self.character.dialogue_system.set_bubble_style(value['style'])
                elif section == 'ai':
                    save_ai_settings(value['api_key'], value['model'], trace_id=self.operation_id)
                    self.character._load_gemini_config()
                    self.character.dialogue_system._load_gemini_config()
                self.applied_local[section] = value
                log_event('settings.local.applied', '로컬 설정을 저장하고 실행 중인 기능에 적용했습니다.',
                          trace_id=self.operation_id, section=section, values=value)
        except (OSError, ValueError) as exc:
            self._operations[self.operation_id] = 'failed'
            log_event('settings.local.failed', '로컬 설정 적용에 실패했습니다.',
                      category='오류', level='ERROR', trace_id=self.operation_id,
                      error=str(exc), applied_sections=list(self.applied_local))
            self.dialog.complete(f'일부 설정을 저장하지 못했습니다: {exc}', False, local=self.applied_local)
            return
        if changes['remote']:
            self.request_id = self.operation_id
            log_event('settings.remote.requested', '인식 프로세스에 설정 적용을 요청합니다.',
                      trace_id=self.operation_id, values=changes['remote'])
            if not self.manager.apply_settings(self.request_id, changes['remote']):
                self._operations[self.operation_id] = 'not_sent'
                log_event('settings.remote.not_sent', '인식 설정 요청을 전송하지 못했습니다.',
                          category='오류', level='ERROR', trace_id=self.operation_id)
                self.request_id = None
                self.dialog.complete('기본 설정은 저장했습니다. 사용자 인식 설정은 연결 실패로 적용하지 못했습니다.', False, local=self.applied_local)
        else:
            self._operations[self.operation_id] = 'completed'
            log_event('settings.apply.completed', '설정을 저장하고 적용했습니다.',
                      trace_id=self.operation_id, applied_sections=list(self.applied_local))
            self.dialog.complete('설정을 저장하고 적용했습니다.', local=self.applied_local)

    def handle_message(self, message):
        received_id = message.get('request_id')
        if message.get('kind') == 'result':
            previous = self._operations.get(received_id)
            self._operations[received_id] = 'completed' if message.get('ok') else 'failed'
            log_event('settings.remote.acknowledged', '인식 설정 적용 결과를 받았습니다.',
                      trace_id=received_id, level='INFO' if message.get('ok') else 'ERROR',
                      category='시스템' if message.get('ok') else '오류',
                      result=message, previous_status=previous,
                      late=received_id != self.request_id or self.dialog is None or not self.dialog.pending)
        elif message.get('kind') == 'unavailable' and self.request_id:
            self._operations[self.request_id] = 'unknown'
            log_event('settings.remote.unknown', '인식 프로세스 종료로 실제 적용 결과를 알 수 없습니다.',
                      level='WARNING', trace_id=self.request_id)
        if self.dialog is None:
            return
        if message.get('kind') == 'unavailable':
            self.load_timeout.stop()
            self.request_id = None
            self.connection_timeout()
            if self.dialog.pending:
                self.dialog.complete('인식 기능이 종료되어 적용 결과를 확인하지 못했습니다. 인식 콘솔과 로그창을 확인하세요.', False, local=self.applied_local)
        elif message.get('kind') == 'state':
            self.load_timeout.stop()
            self.dialog.refresh_button.setEnabled(True)
            self.dialog.set_remote(message['state'], preserve_draft=True)
        elif message.get('kind') == 'result' and message.get('request_id') == self.request_id:
            self.request_id = None
            self.dialog.complete(message['message'], message['ok'], local=self.applied_local, remote=message.get('state'))
