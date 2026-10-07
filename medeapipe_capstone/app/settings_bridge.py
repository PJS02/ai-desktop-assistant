"""Settings commands run on the existing Tk loop, never the stdin thread."""
import json
import time
from copy import deepcopy

from app.device_settings import save_device_settings
from recognition.stt_engine import LANGUAGE_OPTIONS, PROVIDER_OPTIONS, SENSITIVITY_OPTIONS, SILENCE_OPTIONS

MODEL_OPTIONS = {'EmotiEffNet B2': 'emotieff_b2', 'MobileNetV3 (기존)': 'mobilenet_v3'}
BOOL_FIELDS = ('tracking', 'marker_only', 'mirror', 'info_overlay', 'emotion', 'always_recognition', 'timestamps')
STT_FIELDS = ('microphone', 'provider', 'language', 'silence', 'sensitivity', 'timestamps')


class SettingsBridge:
    def settings_state(self):
        cameras = [f"index {item['index']} / {item['backend_label']}" for item in self.camera_candidates]
        microphones = [device.label for device in self.stt.audio_devices]
        values = {'camera': self.camera_var.get() if cameras else None,
                  'microphone': self.stt_mic_var.get() if microphones else None,
                  'mode': self.rps_previous_mode if self.rps_session else self.active_mode,
                  'emotion_model': MODEL_OPTIONS[self.emotion_model_var.get()]}
        for key in BOOL_FIELDS:
            variable = self.stt_timestamps_var if key == 'timestamps' else getattr(self, key + '_var')
            values[key] = bool(variable.get())
        for key in ('provider', 'language', 'silence', 'sensitivity'):
            values[key] = getattr(self, 'stt_' + key + '_var').get()
        def options(items):
            return [{'label': item, 'value': item} for item in items]
        choices = {'camera': options(cameras), 'microphone': options(microphones),
                   'mode': [{'label': '끄기', 'value': None}, {'label': '가위바위보', 'value': 'rps'},
                            {'label': '참참참', 'value': 'cham'}, {'label': '에어드로잉', 'value': 'air'}],
                   'emotion_model': [{'label': label, 'value': key} for label, key in MODEL_OPTIONS.items()],
                   'provider': options(PROVIDER_OPTIONS), 'language': options(LANGUAGE_OPTIONS),
                   'silence': options(SILENCE_OPTIONS), 'sensitivity': options(SENSITIVITY_OPTIONS)}
        names = {'google': 'Google Web Speech', 'ko-KR': '한국어', 'en-US': '영어',
                 'ja-JP': '일본어', 'zh-CN': '중국어', 'high': '높음', 'medium': '보통', 'low': '낮음'}
        for key in ('provider', 'language', 'silence', 'sensitivity'):
            for item in choices[key]:
                item['label'] = names.get(item['value'], item['value'].replace(' sec', '초'))
        status = f"카메라 {'실행 중' if self.cap is not None else '중지'} · 음성 인식 {'실행 중' if self.stt.is_running else '중지'}"
        if self.rps_session:
            status += '\n가위바위보 게임을 닫으면 인식 모드를 변경할 수 있습니다.'
        return {'values': values, 'choices': choices, 'status': status, 'game_active': bool(self.rps_session),
                'camera_running': self.cap is not None, 'stt_running': self.stt.is_running}

    @staticmethod
    def emit_settings(message):
        print('APP_SETTINGS ' + json.dumps(message, ensure_ascii=False), flush=True)

    def emit_settings_state(self):
        self.emit_settings({'kind': 'state', 'state': self.settings_state()})

    def settings_result(self, request_id, ok, message):
        self.settings_apply_pending = False
        self.emit_settings({'kind': 'result', 'request_id': request_id, 'ok': ok,
                            'message': message, 'state': self.settings_state()})

    def handle_settings_command(self, command):
        request = {}
        try:
            request = json.loads(command)
            if not isinstance(request, dict):
                raise ValueError('잘못된 설정 요청입니다.')
            action = request.get('action')
            if action == 'get':
                self.emit_settings_state()
            elif action == 'refresh':
                self.refresh_stt_microphones(show_error=False)
                self.settings_refresh_pending = True
                self.start_full_camera_discovery()
            elif action == 'apply':
                if getattr(self, 'settings_apply_pending', False):
                    raise ValueError('이전 설정을 적용하는 중입니다. 잠시 후 다시 시도하세요.')
                self.apply_unified_settings(request.get('request_id'), request.get('values'))
            else:
                raise ValueError('지원하지 않는 설정 요청입니다.')
        except (ValueError, OSError, RuntimeError) as exc:
            request_id = request.get('request_id') if isinstance(request, dict) else None
            self.settings_result(request_id, False, f'사용자 인식 설정을 모두 적용하지 못했습니다: {exc}')

    def apply_unified_settings(self, request_id, patch):
        if not isinstance(patch, dict):
            raise ValueError('설정 값이 올바르지 않습니다.')
        state = self.settings_state()
        original_settings = deepcopy(self.device_settings)
        previous_model = getattr(self, 'emotion_recognizer', None)
        previous_model_key = getattr(self, 'loaded_emotion_model_key', None)
        if self.rps_session and 'mode' in patch:
            raise ValueError('가위바위보 게임을 닫은 뒤 인식 모드를 변경하세요.')
        if self.camera_discovery_thread is not None and self.camera_discovery_thread.is_alive():
            raise ValueError('장치 검색이 끝난 뒤 적용하세요.')
        for key, value in patch.items():
            if key in BOOL_FIELDS:
                if not isinstance(value, bool):
                    raise ValueError('인식 토글 값이 올바르지 않습니다.')
            elif key in state['choices']:
                if value not in [choice['value'] for choice in state['choices'][key]]:
                    raise ValueError(f'{key}: 사용할 수 없는 선택입니다. 장치를 새로고침하세요.')
            else:
                raise ValueError('알 수 없는 설정 항목입니다.')
        if patch.get('emotion_model', state['values']['emotion_model']) != state['values']['emotion_model']:
            model_key = patch['emotion_model']
            self.emotion_model_var.set(next(label for label, key in MODEL_OPTIONS.items() if key == model_key))
            self.load_emotion_model()
            if getattr(self, 'loaded_emotion_model_key', None) != model_key:
                raise RuntimeError('감정 인식 모델을 불러오지 못했습니다. 기존 모델을 유지합니다.')
            self.emotion_result = None
        if 'camera' in patch:
            self.camera_var.set(patch['camera'])
            if self.cap is not None:
                old_label = state['values']['camera']
                self.start_selected_camera()
                if self.cap is None:
                    self.camera_var.set(old_label)
                    self.start_selected_camera()
                    raise RuntimeError('선택한 카메라를 열지 못했습니다. 이전 카메라로 복원을 시도했습니다.')
            else:
                candidate = next(item for item in self.camera_candidates if f"index {item['index']} / {item['backend_label']}" == patch['camera'])
                self.device_settings['camera'] = {'index': candidate['index'], 'backend_label': candidate['backend_label']}
        if 'mode' in patch:
            self.active_mode = patch['mode']
            self.update_mode_status()
        for key in BOOL_FIELDS:
            if key in patch:
                variable = self.stt_timestamps_var if key == 'timestamps' else getattr(self, key + '_var')
                variable.set(patch[key])
        for key in ('provider', 'language', 'silence', 'sensitivity'):
            if key in patch:
                getattr(self, 'stt_' + key + '_var').set(patch[key])
        if 'microphone' in patch:
            self.stt_mic_var.set(patch['microphone'])
        # Existing console methods populate the same state; suppress their best-effort
        # writes here so one checked write determines the acknowledgement.
        self.settings_collecting = True
        try:
            self.save_recognition_settings()
            self.save_stt_device_settings()
        finally:
            self.settings_collecting = False
        try:
            save_device_settings(self.device_settings)
        except OSError:
            self.device_settings = original_settings
            if previous_model is not None:
                self.emotion_recognizer = previous_model
                self.loaded_emotion_model_key = previous_model_key
                self.loaded_emotion_model_label = next(label for label, key in MODEL_OPTIONS.items() if key == previous_model_key)
                self.emotion_model_var.set(self.loaded_emotion_model_label)
            # Restore editable fields so the failed draft remains retryable.
            for key in BOOL_FIELDS:
                variable = self.stt_timestamps_var if key == 'timestamps' else getattr(self, key + '_var')
                variable.set(state['values'][key])
            for key in ('provider', 'language', 'silence', 'sensitivity'):
                getattr(self, 'stt_' + key + '_var').set(state['values'][key])
            self.stt_mic_var.set(state['values']['microphone'] or '')
            if not self.rps_session:
                self.active_mode = state['values']['mode']
                self.update_mode_status()
            raise
        if self.stt.is_running and any(key in patch for key in STT_FIELDS):
            self.settings_apply_pending = True
            self.stop_stt()
            deadline = time.monotonic() + 20
            self.root.after(100, lambda: self.restart_settings_stt(request_id, deadline))
        else:
            self.settings_result(request_id, True, '설정을 저장하고 적용했습니다. 중지된 장치는 다음 시작부터 새 설정을 사용합니다.')

    def restart_settings_stt(self, request_id, deadline, started=False):
        if self.is_shutting_down:
            return
        if time.monotonic() > deadline:
            self.settings_result(request_id, False, '설정은 저장했지만 음성 인식 재시작을 확인하지 못했습니다. 인식 콘솔에서 상태를 확인하세요.')
            return
        if not started:
            if self.stt.is_running:
                self.root.after(100, lambda: self.restart_settings_stt(request_id, deadline))
                return
            self.start_stt(show_error=False)
            if not self.stt.is_running:
                self.settings_result(request_id, False, '설정은 저장했지만 음성 인식을 시작하지 못했습니다. 마이크 상태를 확인하세요.')
                return
            self.root.after(100, lambda: self.restart_settings_stt(request_id, deadline, True))
        elif self.stt.is_running and self.stt.stream is not None:
            self.settings_result(request_id, True, '설정을 저장하고 적용했습니다. 음성 인식도 새 설정으로 다시 시작했습니다.')
        elif not self.stt.is_running:
            self.settings_result(request_id, False, '설정은 저장했지만 마이크를 열지 못했습니다. 인식 콘솔에서 상태를 확인하세요.')
        else:
            self.root.after(100, lambda: self.restart_settings_stt(request_id, deadline, True))
