"""Readable projections of diagnostic events without dropping any event or data.

This module has no Qt dependency. Table previews are short; complete field values
are always available in sections, and the UI retains each original LogEvent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from app_logging import LogEvent, sanitize


CATEGORY_TABS = {
    '전체': ('통합', '원본'),
    '사용자 인식': ('통합', '음성', '감정·동작·주의', '장치·연결', '원본'),
    '캐릭터 상태': ('통합', '감정', '상호작용·게임', '이동·표면', '원본'),
    '대화·AI': ('통합', '대화 흐름', '요청·응답 전문', '음성 출력', '원본'),
    '시스템': ('통합', '시작·종료', '설정', '렌더·파일', '원본'),
    '오류': ('통합', '오류', '경고', '원본'),
}


@dataclass(frozen=True)
class PresentedEvent:
    domain: str
    topic: str
    action: str
    summary: str
    sections: tuple[tuple[str, str], ...]


_LABELS = {
    'text': '문장', 'raw_text': '입력 원문', 'prepared_text': '발화 준비 문장',
    'prompt': '프롬프트 전문', 'payload': '전송 본문', 'body': 'HTTP 응답 전문',
    'response': '응답 전문', 'raw_response': '모델 응답 원문', 'final_text': '최종 대사',
    'previous_text': '이전 문장', 'history': '대화 기록', 'source': '입력 경로',
    'source_category': '원래 분류', 'reason': '이유', 'error': '오류 내용',
    'parse_error': '파싱 결과', 'traceback': '오류 스택', 'model': '모델',
    'status': '상태', 'attempt': '요청 횟수', 'next_attempt': '다음 요청 횟수',
    'timeout_seconds': '제한 시간(초)', 'delay_seconds': '재시도 대기(초)',
    'elapsed_ms': '소요 시간(ms)', 'elapsed_seconds': '소요 시간(초)',
    'elapsed': '소요 시간(초)', 'queued_seconds': '입력 대기 시간(초)',
    'queue_size': '대기 건수', 'retry_of': '재시도 대상', 'turn_id': '대화 번호',
    'generation': '처리 세대', 'input_epoch': '입력 순번', 'mode': '처리 방식',
    'selected_field': '선택한 응답 필드', 'fenced': '코드 블록 여부',
    'history_count': '대화 기록 수', 'duration_ms': '표시 시간(ms)',
    'display_type': '표시 방식', 'visible': '위젯 표시 여부', 'shown': '표시 결과',
    'failed': '실패 여부', 'outcome': '처리 결과', 'state': '상태',
    'voice_id': '음성', 'language': '언어', 'enabled': '사용 여부',
    'component': '구성 요소', 'audio_seconds': '오디오 길이(초)',
    'sample_rate': '샘플레이트(Hz)', 'pcm_bytes': '오디오 크기(byte)',
    'device': '장치', 'channels': '채널 수', 'sample_format': '오디오 형식',
    'label': '인식 감정', 'confidence': '신뢰도', 'kind': '반응 종류',
    'previous': '이전 상태', 'current': '현재 상태', 'previous_reason': '이전 이유',
    'speaking': '음성 재생 여부', 'ignore_until': '입력 억제 종료 시각',
    'suppressed_since_previous': '이전 기록 이후 같은 사유로 생략된 횟수',
    'repeated_packets': '같은 인식 내용의 반복 패킷 수',
    'suppressed_chunks': '억제된 오디오 청크 수', 'discarded_chunks': '폐기 청크 수',
    'speech_session': '음성 세션', 'speech_sequence': '음성 순번',
    'request_sequence': '음성 요청 순번', 'recognized_at': '인식 시각',
    'microphone': '마이크', 'requested_label': '요청 마이크',
    'requested_index': '요청 장치 번호', 'actual_index': '실제 장치 번호',
    'actual_sample_rate': '실제 샘플레이트(Hz)', 'selection_reason': '장치 선택 이유',
    'duration': '길이(초)', 'rms': '음량(RMS)', 'threshold': '음량 기준',
    'requested': '요청 장치', 'selected': '선택 장치', 'saved': '저장 결과',
    'path': '파일 경로', 'paths': '파일 경로', 'settings': '저장 설정',
    'candidates': '발견한 장치', 'labels': '발견한 마이크', 'count': '횟수',
    'fps': '프레임레이트', 'requested_width': '요청 너비',
    'requested_height': '요청 높이', 'actual_width': '실제 너비', 'actual_height': '실제 높이',
    'host': '호스트', 'port': '포트', 'client': '연결 상대', 'bytes': '전송 크기(byte)',
    'retry_scheduled': '재전송 예정 여부', 'remaining_queue': '남은 대기 건수',
    'influence': '감정 변화 내역', 'final_emotion': '최종 감정', 'before': '변화 전',
    'formatted_state': '감정 상태 전문', 'old_emotion': '이전 감정', 'new_emotion': '현재 감정',
    'item': '획득 아이템', 'held_item_count': '보유 아이템 수',
    'after': '변화 후', 'target': '목표값', 'occ_changes': 'OCC 감정 변화',
    'occ_after': '현재 OCC 감정', 'event_input': '감정 사건 입력', 'merged': '기존 사건과 합쳐짐',
    'reward': '쓰다듬기 보상', 'amount': '보상 크기', 'total_count': '누적 횟수',
    'mood': '현재 감정', 'emotion': '감정', 'action': '동작', 'position': '위치',
    'start_position': '시작 위치', 'release_position': '놓은 위치', 'target_x': '목표 X',
    'velocity': '속도', 'velocity_x': '가로 속도', 'velocity_y': '세로 속도',
    'move_range': '이동 범위', 'movement_speed': '이동 속도', 'command': '명령',
    'player': '사용자 손', 'opponent': '캐릭터 손', 'hand': '손 후보',
    'previous_hand': '이전 손 후보', 'result': '결과', 'detail': '세부 내용',
    'last_hand': '마지막 손 후보', 'stable_samples': '안정 판정 표본 수',
    'warmup_seconds': '준비 시간(초)', 'cooldown_seconds': '휴식 시간(초)',
    'changed_fields': '변경 항목', 'fields': '변경 항목', 'patch': '요청 설정',
    'values': '설정값', 'section': '설정 분류', 'applied_sections': '적용한 설정 분류',
    'runtime_status': '실행 반영 상태', 'runtime_applied': '실행 반영 여부',
    'runtime_configured': '실행 설정 반영 여부', 'result_message': '처리 결과 안내',
    'previous_status': '이전 요청 상태', 'late': '늦은 응답 여부', 'ok': '성공 여부',
    'restored': '원래 상태 복원 여부', 'previous_model': '이전 모델',
    'output': '진단 출력 전문', 'stderr': '진단 출력 전문', 'raw': '받은 원문',
    'method': '종료 방법', 'exit_code': '종료 코드', 'pid': '프로세스 번호',
    'fallback': '대체 동작', 'frame_count': '프레임 수', 'valid_frame_count': '유효 프레임 수',
    'invalid_paths': '읽지 못한 프레임', 'animation': '애니메이션',
    'stats': '렌더 측정값', 'api_key_present': 'API 키 설정 여부',
    'remaining': '남은 대기 시간(초)', 'stream': '출력 경로', 'size': '크기',
    'limit': '허용 크기', 'usage': 'API 사용량', 'prompt_feedback': '프롬프트 처리 결과',
    'finish_reason': '모델 종료 사유', 'candidate_index': '응답 후보 번호',
    'part_index': '텍스트 부분 번호', 'personality': '성격 설정', 'resolution': '화면 크기',
    'motion': '직접 조작 동작', 'direction': '방향', 'active': '직접 조작 활성 여부',
    'dtype': '오디오 데이터 형식', 'sensitivity': '음성 감도', 'silence': '무음 판정 설정',
    'provider': '인식 서비스', 'capture_at': '손 판정 시작 시각', 'deadline': '대기 종료 시각',
    'rig_root': '렌더 에셋 경로', 'parts': '렌더 구성 요소 수', 'source_hashes': '렌더 파일 해시',
    'device_pixel_ratio': '화면 배율', 'operation': '렌더 작업', 'max_bytes': '로그 파일 최대 크기(byte)',
    'backup_count': '로그 백업 파일 수', 'executable': '실행 파일', 'script': '인식 실행 파일',
    'suppressed_until': '음성 억제 종료 시각', 'hold_until': '감정 유지 종료 시각',
    'offset': '오디오 시작 위치', 'sample': '손 관찰 표본', 'background': '백그라운드 실행 여부',
    'requested_bounds': '요청한 캐릭터 크기', 'effective_bounds': '실제 캐릭터 크기',
    'options': '캐릭터 설정', 'resize_required': '크기 변경 필요 여부', 'grounded': '바닥 위치 여부',
}

# Translate known diagnostic values only; unknown values retain their original
# representation so new event families cannot silently lose information.
_VALUES = {
    'typed': '문자 입력', 'speech': '음성 입력', 'manual': '직접 조작',
    'automatic': '자동', 'disabled': '음성 설정 꺼짐', 'shutdown': '앱 종료',
    'empty': '내용 없음', 'empty_input': '빈 입력', 'closed': '종료된 상태',
    'empty_prepared_text': '발화할 문장 없음', 'empty_audio': '오디오 없음',
    'no_api_key': 'API 키 미설정', 'missing_api_key': 'API 키 미설정',
    'generation_mismatch': '이전 요청의 늦은 결과', 'replaced': '새 요청으로 교체',
    'new_user_input': '새 사용자 입력', 'dialogue_busy': '대화 처리 중',
    'input_epoch_changed': '새 사용자 입력', 'ai_responding': 'AI 응답 대기',
    'tts_busy': '음성 합성·재생 중', 'speaking': '음성 재생 중',
    'cooldown': '재요청 대기 시간', 'low_confidence': '신뢰도 부족',
    'stale': '유효 시간이 지난 결과', 'not_final': '최종 결과 아님',
    'duplicate': '이미 처리한 결과', 'unstable': '안정 판정 부족',
    'neutral': '중립', 'happy': '기쁨', 'sad': '슬픔', 'angry': '분노',
    'scared': '두려움', 'surprise': '놀람', 'surprised': '놀람',
    'away': '자리 비움', 'present': '사용자 있음', 'focused': '집중',
    'blocked': '반응 보류', 'shown': '표시됨', 'callback_returned': '콜백 반환 확인',
    'applied': '반영 확인', 'unknown': '확인되지 않음', 'failed': '실패',
    'completed': '완료', 'queued': '대기', 'responding': '응답 처리 중',
    'json_field': 'JSON 대사 필드 추출', 'raw_text': '일반 문장 사용',
    'json_value': 'JSON 값 사용', 'json_without_dialogue_field': '대사 필드 없는 JSON 사용',
    'empty_fallback': '빈 응답 안내문 사용', 'error_fallback': '오류 안내문 사용',
    'bubble': '말풍선', 'narration': '내레이션', 'timeout': '시간 초과',
    'timer': '표시 시간 만료', 'device_stopped': '오디오 장치 정지',
    'no_device': '오디오 출력 장치 없음', 'unsupported_format': '지원하지 않는 오디오 형식',
    'start_exception': '재생 시작 오류', 'queue_full': '송신 대기열 가득 참',
    'saved_match': '저장 장치 일치', 'fallback': '대체 장치 선택',
    'no_devices': '사용 가능한 장치 없음', 'monitor_mismatch': '모니터 정보 불일치',
    'qt_monitor_mismatch': 'Qt 화면과 Win32 모니터 불일치',
    'rps': '가위바위보', 'rock': '바위', 'paper': '보', 'scissors': '가위',
    'win': '승리', 'lose': '패배', 'draw': '무승부',
    'emotion': '감정', 'gesture': '동작', 'attention': '주의 상태',
    'head_motion': '고개 동작', 'greeting': '인사', 'dialogue': '대화',
    'drag': '드래그', 'pet': '쓰다듬기', 'ball': '공 놀이',
    'emotion_changed': '감정 변화', 'click': '클릭', 'item_acquired': '아이템 획득',
    'items_released': '아이템 반환', 'cham': '참참참', 'air_drawing': '허공 그림',
    'listening': '음성 입력 대기', 'recording': '녹음 중', 'processing': '처리 중',
    'starting': '시작 중', 'stopping': '중지 중', 'stopped': '중지됨',
    'STT listening': '음성 입력 대기', 'STT stopping...': '음성 인식 중지 중',
    'STT stopped': '음성 인식 중지됨', 'STT silence detected': '무음 감지',
    'STT no speech': '발화 없음', 'STT could not understand speech': '음성 해석 불가',
    'STT speech detected': '발화 감지',
    'STT sending audio to Google Web Speech': 'Google 음성 인식에 오디오 전송 중',
    'STT recording with Google Web Speech': 'Google 음성 인식용 녹음 중',
    'STT transcribed with Google Web Speech': 'Google 음성 인식 결과 수신',
    'conversation_busy': '대화 처리 중', 'closing': '앱 종료 중',
    'closing_or_generation_changed': '앱 종료 또는 새 요청으로 무효화',
    'invalid_or_empty_input': '올바르지 않거나 빈 입력', 'user_input_priority': '사용자 대화 우선',
    'no_active_input': '대상 대화 입력 없음', 'empty_response_or_no_window': '응답 또는 활성 창 없음',
    'drag_started': '드래그 시작', 'leave': '커서가 캐릭터를 벗어남',
    'unknown_value': '해석 가능한 음성 없음', 'tts_suppressed': '음성 출력과 겹친 입력',
    'label_match': '저장한 마이크 이름 일치', 'system_default': '시스템 기본 장치',
}

_ACTIONS = {
    'dialogue.input_accepted': '대화 입력 접수', 'dialogue.input_rejected': '대화 입력 거부',
    'dialogue.input_waiting': '대화 입력 대기', 'dialogue.processing_started': '대화 처리 시작',
    'dialogue.prompt_built': '대화 프롬프트 구성', 'dialogue.provider_called': '응답 제공자 호출',
    'dialogue.turn_completed': '대화 응답 완료', 'dialogue.turn_failed': '대화 응답 실패',
    'dialogue.turn_cancelled': '대화 처리 취소', 'dialogue.retry_requested': '대화 재시도 요청',
    'dialogue.model_text_received': '모델 문장 수신', 'dialogue.response_normalized': '응답 가공',
    'dialogue.response_discarded': '대화 응답 폐기', 'dialogue.response_failed': '응답 처리 실패',
    'dialogue.display_requested': '대사 표시 요청', 'dialogue.widget_shown': '대사 표시',
    'dialogue.widget_replaced': '대사 교체', 'dialogue.widget_closed': '대사 닫힘',
    'dialogue.display_discarded': '대사 표시 생략', 'dialogue.tts_requested': '대사 음성 출력 요청',
    'dialogue.automatic_started': '자동 대화 시작', 'dialogue.automatic_prompt': '자동 대화 프롬프트 구성',
    'dialogue.automatic_response': '자동 대화 응답 수신', 'dialogue.automatic_finished': '자동 대화 처리 종료',
    'dialogue.automatic_discarded': '자동 대화 폐기', 'dialogue.automatic_skipped': '자동 대화 생략',
    'gemini.request': 'Gemini 요청 구성', 'gemini.attempt_started': 'Gemini 요청 시작',
    'gemini.http_response': 'Gemini 응답 수신', 'gemini.http_failed': 'Gemini HTTP 요청 실패',
    'gemini.connection_failed': 'Gemini 연결 실패', 'gemini.retry_scheduled': 'Gemini 재시도 예약',
    'gemini.text_extracted': 'Gemini 대사 추출', 'gemini.empty_response': 'Gemini 응답 내용 없음',
    'gemini.failed': 'Gemini 응답 처리 실패', 'gemini.skipped': 'Gemini 호출 생략',
    'tts.requested': '음성 합성 요청', 'tts.skipped': '음성 출력 생략',
    'tts.model_loading': '음성 모델 로딩', 'tts.model_ready': '음성 모델 준비',
    'tts.model_failed': '음성 모델 로딩 실패', 'tts.synthesis_started': '음성 합성 시작',
    'tts.synthesis_completed': '음성 합성 완료', 'tts.synthesis_failed': '음성 합성 실패',
    'tts.playback_requested': '오디오 재생 요청', 'tts.playback_started': '오디오 실제 재생 시작',
    'tts.playback_completed': '오디오 재생 완료', 'tts.playback_failed': '오디오 재생 실패',
    'tts.playback_stopped': '오디오 재생 중단', 'tts.playback_suspended': '오디오 재생 일시 정지',
    'tts.output_unavailable': '오디오 출력 사용 불가', 'tts.request_cancelled': '음성 요청 취소',
    'tts.queued_discarded': '대기 발화 폐기', 'tts.synthesis_discarded': '음성 합성 폐기',
    'tts.audio_discarded': '오디오 결과 폐기',
    'stt.status': '음성 인식 상태', 'stt.google.request': 'Google 음성 인식 요청',
    'stt.google.result': '음성 인식 완료', 'stt.google.unrecognized': '음성 해석 불가',
    'stt.google.failed': '음성 인식 요청 실패', 'stt.result.forwarded': '음성 입력 전달 준비',
    'stt.google.empty': '음성 인식 결과 없음', 'stt.google.discarded': '음성 인식 결과 폐기',
    'stt.result.discarded': '음성 입력 전달 생략', 'stt.utterance.silence': '낮은 음량의 입력 생략',
    'stt.suppression.changed': '음성 입력 억제 변경', 'stt.audio.suppressed': '오디오 청크 억제',
    'perception.rejected': '인식 적용 생략', 'perception.emotion.applied': '인식 감정 반영',
    'perception.attention.changed': '사용자 주의 상태 변경', 'perception.wave.detected': '손 흔들기 인식',
    'perception.speech.accepted': '음성 대화 입력 수락',
    'perception.reaction.requested': '인식 반응 요청', 'perception.reaction.result': '인식 반응 전달 결과',
    'perception.reaction.failed': '인식 반응 실패', 'perception.dialogue_shown': '인식 반응 대사 표시',
    'perception.dialogue_blocked': '인식 반응 대사 보류',
    'transport.sender.queued': '인식 메시지 송신 대기', 'transport.sender.sent': '인식 메시지 송신',
    'transport.sender.dropped': '인식 메시지 폐기', 'transport.sender.failed': '인식 메시지 송신 실패',
    'transport.receiver.received': '인식 메시지 수신', 'transport.receiver.invalid': '잘못된 인식 메시지',
    'mood.influence': '감정 사건 반영', 'mood.pet': '쓰다듬기 감정 반영',
    'mood.snapshot': '현재 감정 상태',
    'character.pet_started': '쓰다듬기 시작', 'character.pet_finished': '쓰다듬기 종료',
    'character.drag_started': '캐릭터 드래그 시작', 'character.drag_finished': '캐릭터 드래그 종료',
    'character.movement_started': '캐릭터 이동 시작', 'character.movement_arrived': '이동 목표 도착',
    'character.movement_stopped': '캐릭터 이동 중단', 'character.animation_finished': '캐릭터 동작 종료',
    'game.rps.result': '가위바위보 결과', 'game.rps.no_result': '가위바위보 판정 불가',
    'desktop.dpi.fallback': '창 좌표 변환 대체',
    'settings.remote.timeout': '인식 설정 적용 확인 지연',
    'settings.remote.unknown': '인식 설정 적용 확인 불가',
    'settings.recognition.stt_timeout': '음성 재시작 확인 지연',
    'settings.recognition.completed': '인식 설정 적용 결과',
    'settings.remote.acknowledged': '인식 설정 응답 수신',
}


def _json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _short(value: Any, limit=76, *, translate=True) -> str:
    if value is None:
        return '확인되지 않음'
    if isinstance(value, bool):
        return '예' if value else '아니오'
    if isinstance(value, float):
        return f'{value:.4g}'
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if translate:
        text = _VALUES.get(text, text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _legacy_domain(message: str, category: str) -> str:
    if re.search(r'(?:외부 (?:감정|음성|동작)|사용자 인사|\bSTT\b|MediaPipe|인식 수신)', message, re.I):
        return '사용자 인식'
    if re.search(r'(?:Gemini|\bTTS\b|말풍선|대화 입력)', message, re.I):
        return '대화·AI'
    if re.search(r'(?:감정 상태|Russell|valence|arousal|좌표\s*[:=]|강도\s*[:=]|V\s*=.*A\s*=|Surface|쓰다듬|드래그|점프)', message, re.I):
        return '캐릭터 상태'
    return category


def _domain(event: str, category: str, data: dict, message: str) -> str:
    source = data.get('source_category')
    if source in CATEGORY_TABS and source not in ('전체', '오류'):
        return source
    if event.startswith(('dialogue.', 'gemini.', 'tts.')):
        return '대화·AI'
    if event.startswith(('perception.', 'stt.', 'transport.', 'recognition.')):
        return '사용자 인식'
    if event.startswith('device.') and not event.startswith('device.settings.'):
        return '사용자 인식'
    if event.startswith(('character.', 'mood.', 'game.', 'sandbox.')):
        return '캐릭터 상태'
    if event.startswith(('settings.', 'device.settings.', 'renderer.', 'sprite.', 'desktop.', 'logging.', 'application.', 'qt.')):
        return '시스템'
    if event.startswith(('legacy.', 'python.', 'native.')):
        return _legacy_domain(message, category)
    return category if category in CATEGORY_TABS and category != '전체' else '시스템'


def _topic(event: str, domain: str, message: str, data: dict, level: str) -> str:
    if domain == '사용자 인식':
        if event.startswith('stt.') or '.speech.' in event or re.search(r'(?:STT|음성 인식)', message, re.I):
            return '음성'
        if event.startswith(('device.', 'transport.', 'recognition.model.', 'recognition.inference.',
                             'recognition.process', 'recognition.shutdown', 'recognition.control', 'recognition.command', 'native.')):
            return '장치·연결'
        if re.search(r'(?:MediaPipe (?:실행|시작|종료)|카메라|마이크|TensorFlow|XNNPACK)', message, re.I):
            return '장치·연결'
        return '감정·동작·주의'
    if domain == '캐릭터 상태':
        if event.startswith(('mood.', 'character.expression.')) or re.search(r'(?:감정|Russell|valence|arousal|좌표\s*[:=]|강도\s*[:=])', message, re.I):
            return '감정'
        if event.startswith(('game.', 'sandbox.', 'character.pet', 'character.drag', 'character.manual')) or re.search(r'(?:쓰다듬|드래그|가위바위보)', message):
            return '상호작용·게임'
        return '이동·표면'
    if domain == '대화·AI':
        if event.startswith('tts.') or event == 'dialogue.tts_requested':
            return '음성 출력'
        if event.startswith('gemini.') or any(key in data for key in ('prompt', 'raw_response')):
            return '요청·응답 전문'
        return '대화 흐름'
    if domain == '시스템':
        if event.startswith(('settings.', 'device.settings.')) or '[설정]' in message:
            return '설정'
        if event.startswith(('renderer.', 'sprite.', 'desktop.', 'logging.')):
            return '렌더·파일'
        return '시작·종료'
    return '오류' if level in ('ERROR', 'CRITICAL') else '경고'


def _field(data: dict, key: str, label: str | None = None, limit=60) -> str:
    if key not in data:
        return ''
    value = data[key]
    if key in ('emotion', 'final_emotion', 'mood', 'old_emotion', 'new_emotion'):
        value = _emotion(value)
    if key in ('state', 'before', 'after', 'target'):
        value = _coordinates(value)
    translated_fields = {
        'source', 'reason', 'selection_reason', 'previous_reason', 'kind', 'mode', 'outcome',
        'state', 'status', 'label', 'runtime_status', 'previous_status', 'previous', 'current',
        'emotion', 'final_emotion', 'mood', 'old_emotion', 'new_emotion',
        'player', 'opponent', 'hand', 'previous_hand', 'result', 'display_type',
    }
    return f'{label or _LABELS.get(key, key)} {_short(value, limit, translate=key in translated_fields)}'


def _emotion(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    emotion = value.get('emotion')
    if isinstance(emotion, dict):
        return _emotion(emotion)
    if emotion is not None:
        description = _short(emotion)
        if 'intensity' in value:
            description += f' (강도 {_short(value["intensity"])})'
        return description
    return value


def _coordinates(value: Any) -> Any:
    if isinstance(value, dict) and all(key in value for key in ('valence', 'arousal')):
        return f'V {_short(value["valence"])} / A {_short(value["arousal"])}'
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f'V {_short(value[0])} / A {_short(value[1])}'
    return value


def _text(data: dict, *keys: str) -> str:
    for key in keys:
        if key in data and data[key] not in (None, ''):
            return f'“{_short(data[key], 76, translate=False)}”'
    return ''


def _duration(data: dict) -> str:
    for key in ('elapsed_seconds', 'elapsed', 'duration', 'queued_seconds'):
        if key in data and data[key] is not None:
            return f'{_LABELS.get(key, "소요 시간").removesuffix("(초)")} {_short(data[key])}초'
    if data.get('elapsed_ms') is not None:
        return f'소요 시간 {_short(data["elapsed_ms"])}ms'
    return ''


def _mood_summary(data: dict) -> list[str]:
    influence = data.get('influence')
    parts = []
    if isinstance(influence, dict):
        parts.append(_field(influence, 'source', '원인'))
        for axis, label in (('valence', 'V'), ('arousal', 'A')):
            before, after = influence.get('before_' + axis), influence.get('after_' + axis)
            if before is not None and after is not None:
                parts.append(f'{label} {_short(before)} → {_short(after)}')
        parts.append(_field(influence, 'adjusted_weight', '반영 가중치'))
    elif 'state' in data:
        parts += [_field(data, 'state', '좌표')]
    else:
        for key in ('before', 'after'):
            parts.append(_field(data, key, limit=38))
        parts.append(_field(data, 'amount', '보상'))
    parts.append(_field(data, 'final_emotion'))
    return parts


def _settings_summary(data: dict) -> list[str]:
    result = data.get('result')
    values = result if isinstance(result, dict) else data
    # A settings response can also be the payload of the child ACK event.
    if isinstance(data.get('payload'), dict):
        values = data['payload']
    parts = []
    if 'saved' in values:
        saved = values['saved']
        parts.append('파일 저장 ' + ('완료' if saved is True else '미완료' if saved is False else _short(saved)))
    status = values.get('runtime_status')
    if status is not None:
        parts.append('실행 반영 ' + _short(status))
    elif 'runtime_applied' in values:
        applied = values['runtime_applied']
        parts.append('실행 반영 ' + ('확인' if applied is True else '미반영' if applied is False else '확인되지 않음'))
    for key in ('changed_fields', 'fields', 'section', 'applied_sections', 'model', 'late', 'reason', 'error'):
        parts.append(_field(data, key))
    if 'result_message' in values:
        parts.append(_short(values['result_message']))
    elif isinstance(values, dict) and 'message' in values:
        parts.append(_short(values['message']))
    return parts


def _summary(event: str, message: str, data: dict) -> str:
    parts: list[str] = []
    if event.startswith('gemini.'):
        for key in ('status', 'attempt', 'next_attempt', 'delay_seconds', 'model'):
            label = 'HTTP' if key == 'status' else None
            parts.append(_field(data, key, label))
        parts += [_duration(data), _field(data, 'reason'), _field(data, 'error'),
                  _text(data, 'text'), _field(data, 'finish_reason', '종료 이유')]
        if 'payload' in data:
            parts.append('요청 전문 확인 가능')
        if 'body' in data:
            parts.append('응답 전문 확인 가능')
    elif event.startswith('dialogue.'):
        if event == 'dialogue.response_normalized':
            parts += [_field(data, 'mode', '가공 방식'), _field(data, 'selected_field'), _text(data, 'final_text')]
        else:
            parts += [_text(data, 'text', 'response', 'raw_response', 'raw_text'), _field(data, 'source')]
        parts += [_field(data, 'reason'), _field(data, 'queue_size'), _duration(data),
                  _field(data, 'state'), _field(data, 'outcome'), _field(data, 'shown'),
                  _field(data, 'failed'), _field(data, 'display_type'), _field(data, 'model'),
                  _field(data, 'error')]
        if 'prompt' in data:
            parts += [_field(data, 'history_count'), '프롬프트 전문 확인 가능']
        if 'activity' in data:
            parts.append(_field(data, 'activity', '활성 창', 54))
    elif event.startswith('tts.'):
        parts += [_field(data, 'reason'), _text(data, 'prepared_text', 'text'),
                  _field(data, 'voice_id'), _field(data, 'language'), _duration(data),
                  _field(data, 'audio_seconds'), _field(data, 'state'),
                  _field(data, 'device'), _field(data, 'model'), _field(data, 'error')]
        if not any(parts):
            parts += [_field(data, key) for key in ('enabled', 'sample_rate', 'stopped', 'timeout_seconds')]
    elif event.startswith('stt.'):
        parts += [_text(data, 'text'), _field(data, 'status'), _field(data, 'reason'),
                  _duration(data), _field(data, 'microphone'), _field(data, 'requested_label'),
                  _field(data, 'actual_index'), _field(data, 'selection_reason'),
                  _field(data, 'provider', '인식 서비스'), _field(data, 'language'),
                  _field(data, 'rms'), _field(data, 'threshold'), _field(data, 'speaking'),
                  _field(data, 'suppressed_chunks'), _field(data, 'error')]
    elif event.startswith('perception.'):
        parts += [_text(data, 'text'), _field(data, 'kind'), _field(data, 'label'),
                  _field(data, 'confidence'), _field(data, 'reason'), _field(data, 'outcome'),
                  _field(data, 'previous'), _field(data, 'current'),
                  _field(data, 'sides', '인식한 손'), _field(data, 'error')]
    elif event.startswith('mood.'):
        parts += _mood_summary(data)
        parts += [_field(data, 'reason'), _field(data, 'error')]
    elif event.startswith('settings.') or event.startswith('device.settings.'):
        parts += _settings_summary(data)
    elif event.startswith('transport.'):
        parts += [_field(data, 'queue_size'), _field(data, 'reason'),
                  _field(data, 'retry_scheduled'), _field(data, 'bytes'), _field(data, 'client'),
                  _field(data, 'host'), _field(data, 'port'), _field(data, 'error')]
        payload = data.get('payload')
        if isinstance(payload, dict):
            parts += [_field(payload, 'mode', '인식 모드'), _text(payload, 'speech_text', 'text')]
            for key in ('emotion', 'gestures', 'head_motion', 'attention', 'speech'):
                if key in payload:
                    parts.append(_field(payload, key, _LABELS.get(key, key), 40))
            if not any(parts):
                parts.append('인식 본문 확인 가능')
    elif event.startswith('device.'):
        parts += [_field(data, 'selected'), _field(data, 'requested'),
                  _field(data, 'reason'), _field(data, 'count', '발견 수'),
                  _field(data, 'actual_width', '너비'), _field(data, 'actual_height', '높이'),
                  _field(data, 'fps'), _field(data, 'error')]
        if 'labels' in data:
            parts.append(_field(data, 'labels', '마이크 목록', 74))
    elif event.startswith(('character.', 'game.', 'sandbox.')):
        for key in ('count', 'reward', 'player', 'opponent', 'result', 'reason', 'command',
                    'emotion', 'mood', 'target_x', 'position', 'velocity', 'velocity_x',
                    'velocity_y', 'duration', 'action', 'hand', 'warmup_seconds',
                    'cooldown_seconds', 'state', 'error'):
            parts.append(_field(data, key))
    if not any(parts):
        # Human text is preserved for existing print output and unmapped events.
        if message:
            parts.append(_short(message, 110, translate=False))
        for key, value in data.items():
            if key not in ('source_category', 'trace_id', 'session_id', 'generation', 'component'):
                parts.append(_field(data, key, limit=48))
    if 'suppressed_since_previous' in data:
        parts.append(f'같은 사유 {_short(data["suppressed_since_previous"])}회 추가')
    if 'repeated_packets' in data and data['repeated_packets']:
        parts.append(f'반복 패킷 {_short(data["repeated_packets"])}건')
    summary = ' · '.join(dict.fromkeys(part for part in parts if part))
    return _short(summary or '추가 내용 없음', 164, translate=False)


def present_event(entry: LogEvent) -> PresentedEvent:
    """Project one sanitized event; no suppression, merging, or success inference."""
    event = str(getattr(entry, 'event', '') or 'legacy.output')
    message = sanitize(str(getattr(entry, 'message', '') or ''))
    raw_data = sanitize(getattr(entry, 'data', {}))
    data = raw_data if isinstance(raw_data, dict) else {'detail': raw_data}
    category = str(getattr(entry, 'category', '시스템'))
    level = str(getattr(entry, 'level', 'INFO')).upper()
    domain = _domain(event, category, data, message)
    topic = _topic(event, domain, message, data, level)
    action = _ACTIONS.get(event)
    if action is None:
        # The original Korean event description is a better future-proof title
        # than exposing implementation identifiers to every table row.
        action = _short(message, 52, translate=False) if message else '기록'
        action = re.sub(r'^(?:\[[^\]]+\]\s*)+', '', action) or '진단 출력'
    sections = []
    if message:
        sections.append(('기록 설명', message))
    sections.extend((_LABELS.get(key, key), _json(value)) for key, value in data.items())
    if not sections:
        sections.append(('기록 설명', '추가 내용 없음'))
    return PresentedEvent(domain, topic, action, _summary(event, message, data), tuple(sections))
