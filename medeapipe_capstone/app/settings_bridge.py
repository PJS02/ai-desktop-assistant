"""Settings commands run on the existing Tk loop, never the stdin thread."""
import json
import time
from copy import deepcopy
from app_logging import log_event, new_trace_id, write_protocol

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
        log_event('settings.recognition.ack', '인식 설정 응답 전송', category='시스템',
                  trace_id=message.get('request_id'), payload=message)
        write_protocol('APP_SETTINGS', message)

    def emit_settings_state(self):
        self.emit_settings({'kind': 'state', 'state': self.settings_state()})

    def settings_result(self, request_id, ok, message, *, runtime_status=None):
        self.settings_apply_pending = False
        saved = bool(getattr(self, '_settings_saved', False)) and request_id == getattr(self, '_settings_request_id', None)
        runtime_status = runtime_status or ('applied' if ok else 'failed')
        runtime_applied = None if runtime_status == 'unknown' else bool(ok)
        log_event('settings.recognition.completed', '인식 설정 적용 결과',
                  category='시스템' if ok else '오류', level='INFO' if ok else 'ERROR',
                  trace_id=request_id, ok=ok, saved=saved,
                  runtime_applied=runtime_applied, runtime_status=runtime_status, result_message=message)
        self.emit_settings({'kind': 'result', 'request_id': request_id, 'ok': ok,
                            'message': message, 'state': self.settings_state(),
                            'saved': saved, 'runtime_applied': runtime_applied, 'runtime_status': runtime_status})
        if request_id == getattr(self, '_settings_request_id', None):
            self._settings_request_id = None

    def handle_settings_command(self, command):
        request = {}
        try:
            request = json.loads(command)
            if not isinstance(request, dict):
                raise ValueError('잘못된 설정 요청입니다.')
            action = request.get('action')
            log_event('settings.recognition.request', '인식 설정 요청 수신', category='시스템',
                      trace_id=request.get('request_id'), action=action, values=request.get('values'))
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
            log_event('settings.recognition.failed', '인식 설정 요청 실패', category='오류', level='ERROR',
                      trace_id=request_id, error=str(exc))
            self.settings_result(request_id, False, f'사용자 인식 설정을 모두 적용하지 못했습니다: {exc}')

    def apply_unified_settings(self, request_id, patch):
        self._settings_request_id = request_id or new_trace_id('settings')
        self._settings_saved = False
        log_event('settings.recognition.applying', '인식 설정 적용 시작', category='시스템',
                  trace_id=self._settings_request_id, fields=list(patch) if isinstance(patch, dict) else [], patch=patch)
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
                    log_event('settings.recognition.camera_restored', '이전 카메라 복원 시도', category='시스템',
                              trace_id=request_id, requested=patch['camera'], restored=old_label, running=self.cap is not None)
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
            self._settings_saved = True
            log_event('settings.recognition.saved', '인식 설정 파일 저장 완료', category='시스템',
                      trace_id=request_id, fields=list(patch), saved=True)
        except OSError as exc:
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
            log_event('settings.recognition.rolled_back', '저장 실패 후 설정 복원', category='오류', level='ERROR',
                      trace_id=request_id, error=str(exc), saved=False, restored_fields=list(state['values']),
                      restored_model=previous_model_key, camera_running=self.cap is not None,
                      camera_selection_restored='camera' not in patch)
            raise
        log_event('settings.recognition.runtime_configured', '인식 실행 설정 반영', category='시스템',
                  trace_id=request_id, fields=list(patch), camera_running=self.cap is not None,
                  stt_running=self.stt.is_running, stopped_device_effect='next_start')
        if self.stt.is_running and any(key in patch for key in STT_FIELDS):
            self.settings_apply_pending = True
            log_event('settings.recognition.stt_restarting', '변경한 설정으로 음성 인식 재시작',
                      category='사용자 인식', trace_id=request_id)
            self.stop_stt()
            deadline = time.monotonic() + 20
            self.root.after(100, lambda: self.restart_settings_stt(request_id, deadline))
        else:
            self.settings_result(request_id, True, '설정을 저장하고 적용했습니다. 중지된 장치는 다음 시작부터 새 설정을 사용합니다.')

    def restart_settings_stt(self, request_id, deadline, started=False):
        if self.is_shutting_down:
            return
        if time.monotonic() > deadline:
            log_event('settings.recognition.stt_timeout', '설정 저장 후 음성 재시작 확인 시간 초과',
                      category='오류', level='WARNING', trace_id=request_id, saved=True, runtime_status='unknown')
            self.settings_result(request_id, False, '설정은 저장했지만 음성 인식 재시작을 확인하지 못했습니다. 인식 콘솔에서 상태를 확인하세요.', runtime_status='unknown')
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
