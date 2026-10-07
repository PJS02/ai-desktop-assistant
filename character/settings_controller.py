from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .ai_settings import load_ai_settings, save_ai_settings
from .config_manager import load_config, load_character_options, save_config
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
        except (OSError, ValueError):
            ai = self.character.gemini_config
            ai_error = 'AI 설정 파일을 읽을 수 없습니다. 파일을 확인한 뒤 다시 열어 주세요.'
        local = {'character': {'width': width, 'height': height, 'personality': personality},
                 'voice': {'enabled': tts.enabled, 'voice_id': tts.voice_id},
                 'ai': {'api_key': ai.get('api_key', ''), 'model': ai.get('model', '')}}
        local['character'].update(load_character_options())
        self.dialog = SettingsDialog(local, self.character)
        self.dialog.apply_requested.connect(self.apply)
        self.dialog.refresh_requested.connect(self.refresh)
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
        if not self.manager.request_settings(devices):
            self.connection_timeout()
        else:
            self.load_timeout.start(45000)

    def connection_timeout(self):
        if self.dialog is not None:
            self.dialog.remote_unavailable('인식 기능에 연결하지 못했습니다. 장치 새로고침으로 다시 연결할 수 있습니다.')
            self.dialog.refresh_button.setEnabled(True)

    def apply(self, changes):
        self.applied_local = {}
        try:
            for section, value in changes['local'].items():
                if section == 'character':
                    options = {key: value[key] for key in DEFAULT_CHARACTER_OPTIONS}
                    save_config(value['width'], value['height'], value['personality'], character_options=options)
                    self.character.apply_character_settings(value['width'], value['height'], value['personality'], **options)
                elif section == 'voice':
                    tts = self.character.dialogue_system.tts
                    tts.set_voice(value['voice_id'])
                    tts.set_enabled(value['enabled'])
                    tts.sync_settings()
                elif section == 'ai':
                    save_ai_settings(value['api_key'], value['model'])
                    self.character._load_gemini_config()
                    self.character.dialogue_system._load_gemini_config()
                self.applied_local[section] = value
        except (OSError, ValueError) as exc:
            self.dialog.complete(f'일부 설정을 저장하지 못했습니다: {exc}', False, local=self.applied_local)
            return
        if changes['remote']:
            self.request_id = uuid4().hex
            if not self.manager.apply_settings(self.request_id, changes['remote']):
                self.request_id = None
                self.dialog.complete('기본 설정은 저장했습니다. 사용자 인식 설정은 연결 실패로 적용하지 못했습니다.', False, local=self.applied_local)
        else:
            self.dialog.complete('설정을 저장하고 적용했습니다.', local=self.applied_local)

    def handle_message(self, message):
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
