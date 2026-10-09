from datetime import datetime
from types import SimpleNamespace

import pytest

from app_logging import LogEvent, register_secret
from character.log_presentation import CATEGORY_TABS, PresentedEvent, present_event


def event(name, message='', category='시스템', level='INFO', **data):
    return LogEvent(datetime(2026, 10, 8, 12, 10, 3), category, message,
                    name, level, 'trace-example', data)


def full_text(presented):
    return '\n'.join(value for _, value in presented.sections)


def test_tab_structure_has_integrated_and_original_views_for_every_category():
    for tabs in CATEGORY_TABS.values():
        assert tabs[0] == '통합'
        assert tabs[-1] == '원본'
        assert '요약' not in tabs


def test_input_preview_includes_actual_words_source_and_queue_without_metadata_prefix():
    result = present_event(event('dialogue.input_accepted', '사용자 입력 접수',
                                 category='대화·AI', text='안녕하세요', raw_text='  안녕하세요  ',
                                 source='speech', queue_size=1, turn_id=3))
    assert isinstance(result, PresentedEvent)
    assert (result.domain, result.topic, result.action) == ('대화·AI', '대화 흐름', '대화 입력 접수')
    assert '안녕하세요' in result.summary
    assert '음성 입력' in result.summary
    assert '대기 건수 1' in result.summary
    assert 'trace-example' not in result.summary
    assert 'dialogue.input_accepted' not in result.summary
    assert ('입력 원문', '  안녕하세요  ') in result.sections


def test_no_dialogue_stage_is_merged_or_interpreted_as_playback():
    names = ['dialogue.input_accepted', 'dialogue.processing_started', 'dialogue.prompt_built',
             'gemini.request', 'gemini.attempt_started', 'gemini.http_failed',
             'gemini.retry_scheduled', 'gemini.attempt_started', 'gemini.http_response',
             'gemini.text_extracted', 'dialogue.response_normalized',
             'dialogue.widget_shown', 'tts.skipped']
    rows = [present_event(event(name, name, category='대화·AI')) for name in names]
    assert len(rows) == len(names)
    assert all(row.domain == '대화·AI' for row in rows)
    assert rows[5].action == 'Gemini HTTP 요청 실패'
    assert rows[6].action == 'Gemini 재시도 예약'
    assert rows[-1].action == '음성 출력 생략'
    assert all('재생 완료' not in row.action for row in rows)


def test_failed_request_remains_in_original_domain_and_displays_actual_retry_fields():
    failed = present_event(event('gemini.http_failed', 'Gemini HTTP 요청 실패', category='오류',
                                 level='ERROR', source_category='대화·AI', status=500,
                                 attempt=1, elapsed_ms=513.2, error='Internal Server Error', body='full body'))
    retry = present_event(event('gemini.retry_scheduled', '재시도 예약', category='대화·AI',
                                attempt=1, next_attempt=2, delay_seconds=1))
    assert failed.domain == '대화·AI'
    assert 'HTTP 500' in failed.summary
    assert '요청 횟수 1' in failed.summary
    assert '513.2ms' in failed.summary
    assert '다음 요청 횟수 2' in retry.summary
    assert '재시도 대기(초) 1' in retry.summary
    assert ('HTTP 응답 전문', 'full body') in failed.sections


def test_request_full_prompt_and_nested_payload_are_preserved():
    prompt = '첫 줄\n' + '아주 긴 프롬프트 ' * 1000 + '\n마지막 줄'
    payload = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.7}}
    requested = present_event(event('gemini.request', 'Gemini 실제 요청 본문',
                                    category='대화·AI', model='gemma-4-31b-it', payload=payload))
    built = present_event(event('dialogue.prompt_built', '프롬프트', category='대화·AI',
                                model='gemma-4-31b-it', prompt=prompt, history_count=12))
    assert 'gemma-4-31b-it' in requested.summary
    assert requested.topic == '요청·응답 전문'
    assert '마지막 줄' in full_text(requested)
    assert dict(built.sections)['프롬프트 전문'] == prompt
    assert len(requested.summary) <= 164
    assert len(built.summary) <= 164


def test_normalization_fields_show_mode_and_final_dialogue_without_hiding_raw_response():
    raw = '```json\n{"dialogue":"안녕하세요"}\n```'
    row = present_event(event('dialogue.response_normalized', category='대화·AI',
                              mode='json_field', selected_field='dialogue', final_text='안녕하세요',
                              raw_response=raw, fenced=True))
    assert 'JSON 대사 필드 추출' in row.summary
    assert '선택한 응답 필드 dialogue' in row.summary
    assert '안녕하세요' in row.summary
    assert dict(row.sections)['모델 응답 원문'] == raw


def test_disabled_tts_explains_reason_and_does_not_claim_audio_was_played():
    row = present_event(event('tts.skipped', '음성 출력 생략', category='대화·AI',
                              reason='disabled', text='안녕하세요', generation=None, component='TTS'))
    assert (row.domain, row.topic) == ('대화·AI', '음성 출력')
    assert '음성 설정 꺼짐' in row.summary
    assert '안녕하세요' in row.summary
    assert '재생 완료' not in row.action + row.summary
    assert dict(row.sections)['처리 세대'] == 'null'


@pytest.mark.parametrize('name,data,expected', [
    ('stt.google.result', {'text': '반가워요', 'elapsed': 1.24}, '반가워요'),
    ('stt.google.unrecognized', {'reason': 'no_matching_phrase', 'elapsed': 0.53}, 'no_matching_phrase'),
    ('perception.rejected', {'kind': 'speech', 'reason': 'duplicate'}, '이미 처리한 결과'),
    ('perception.reaction.result', {'kind': 'dialogue', 'outcome': 'callback_returned'}, '콜백 반환 확인'),
    ('transport.sender.dropped', {'reason': 'queue_full', 'queue_size': 200, 'retry_scheduled': False}, '재전송 예정 여부 아니오'),
    ('device.camera.started', {'selected': '카메라 2', 'actual_width': 640, 'actual_height': 480, 'fps': 30}, '카메라 2'),
])
def test_recognition_summaries_use_actual_results_and_failure_reasons(name, data, expected):
    row = present_event(event(name, '인식 기록', category='사용자 인식', **data))
    assert row.domain == '사용자 인식'
    assert expected in row.summary


def test_transport_dynamic_stages_are_distinct_and_nested_payload_remains_complete():
    payload = {'type': 'recognition', 'mode': 'rps', 'speech': {'text': '안녕'},
               'rps_game': {'hand': 'rock', 'sample': 2}, 'event_id': 'unique-id'}
    rows = [present_event(event(f'transport.sender.{phase}', '인식 메시지 ' + phase,
                                category='사용자 인식', payload=payload, queue_size=1))
            for phase in ('queued', 'sent', 'dropped')]
    assert len({row.action for row in rows}) == 3
    assert all(row.topic == '장치·연결' for row in rows)
    assert all('unique-id' in full_text(row) and 'rock' in full_text(row) for row in rows)


def test_mood_snapshot_shows_cause_coordinates_emotion_and_intensity():
    original = '[감정 상태]\n좌표: (0.1, 0.2)\n강도: 0.7'
    row = present_event(event('mood.snapshot', '감정 변화 후 상태', category='캐릭터 상태',
                              reason='click', state={'valence': 0.1, 'arousal': 0.2},
                              final_emotion={'emotion': 'happy', 'intensity': 0.7},
                              formatted_state=original))
    assert (row.domain, row.topic) == ('캐릭터 상태', '감정')
    assert '클릭' in row.summary
    assert 'V 0.1 / A 0.2' in row.summary
    assert '기쁨 (강도 0.7)' in row.summary
    assert dict(row.sections)['감정 상태 전문'] == original


def test_mood_influence_shows_real_before_after_values_and_cause():
    row = present_event(event('mood.influence', '감정 사건 평가', category='캐릭터 상태',
                              influence={'source': '쓰다듬기', 'before_valence': 0.1,
                                         'after_valence': 0.2, 'before_arousal': 0.3,
                                         'after_arousal': 0.25, 'adjusted_weight': 0.07},
                              final_emotion={'emotion': 'neutral', 'intensity': 0.85}))
    assert '원인 쓰다듬기' in row.summary
    assert 'V 0.1 → 0.2' in row.summary
    assert 'A 0.3 → 0.25' in row.summary
    assert '중립 (강도 0.85)' in row.summary


def test_character_interaction_and_movement_display_real_values_in_distinct_topics():
    pet = present_event(event('character.pet_finished', category='캐릭터 상태', count=3,
                              reward=0.0078, reason='leave', mood={'emotion': {'emotion': 'neutral', 'intensity': 0.8}}))
    movement = present_event(event('character.movement_arrived', category='캐릭터 상태',
                                   target_x=200, position=[200, 300]))
    assert pet.topic == '상호작용·게임'
    assert '횟수 3' in pet.summary and '보상 0.0078' in pet.summary
    assert '중립' in pet.summary
    assert movement.topic == '이동·표면'
    assert '목표 X 200' in movement.summary


def test_settings_file_saved_and_unknown_runtime_are_independent():
    row = present_event(event('settings.recognition.completed', '인식 설정 적용 결과',
                              category='오류', level='ERROR', ok=False, saved=True,
                              runtime_applied=None, runtime_status='unknown',
                              result_message='재시작 확인 시간 초과'))
    assert (row.domain, row.topic) == ('시스템', '설정')
    assert '파일 저장 완료' in row.summary
    assert '실행 반영 확인되지 않음' in row.summary
    assert '실행 반영 완료' not in row.summary


def test_settings_late_ack_extracts_nested_result_without_claiming_unknown_success():
    result = {'saved': True, 'runtime_applied': None, 'runtime_status': 'unknown',
              'message': '확인 시간이 지났습니다'}
    row = present_event(event('settings.remote.acknowledged', '설정 응답 수신',
                              result=result, previous_status='unknown', late=True))
    assert '파일 저장 완료' in row.summary
    assert '실행 반영 확인되지 않음' in row.summary
    assert '늦은 응답 여부 예' in row.summary
    assert '확인 시간이 지났습니다' in full_text(row)


@pytest.mark.parametrize('message,domain,topic', [
    ('좌표: V=0.12, A=0.4', '캐릭터 상태', '감정'),
    ('Russell valence=0.12 arousal=0.4', '캐릭터 상태', '감정'),
    ('[외부 음성 인식] 안녕하세요', '사용자 인식', '음성'),
    ('[Surface 추가] ground: y=1440px', '캐릭터 상태', '이동·표면'),
])
def test_legacy_field_lines_keep_correct_source_topic(message, domain, topic):
    row = present_event(event('legacy.stdout', message))
    assert (row.domain, row.topic) == (domain, topic)
    assert message in full_text(row)


def test_legacy_multiline_message_is_preserved_in_full_even_with_short_preview():
    message = '첫 번째 줄\n두 번째 줄\n' + '원문 ' * 100
    row = present_event(event('legacy.stdout', message))
    assert dict(row.sections)['기록 설명'] == message
    assert '\n' not in row.summary
    assert len(row.summary) <= 164


@pytest.mark.parametrize('level', ['INFO', 'WARNING'])
def test_native_diagnostics_keep_the_classified_source_domain(level):
    row = present_event(event('native.stderr', 'INFO: Created TensorFlow Lite XNNPACK delegate for CPU.',
                              category='사용자 인식', level=level))
    assert row.domain == '사용자 인식'
    assert row.topic == '장치·연결'
    assert 'TensorFlow Lite XNNPACK' in full_text(row)


def test_device_settings_load_failure_retains_system_settings_domain():
    row = present_event(event('device.settings.default', '장치 설정 읽기 실패로 기본값 사용',
                              category='오류', level='WARNING', reason='unreadable', error='bad JSON'))
    assert (row.domain, row.topic) == ('시스템', '설정')
    assert 'bad JSON' in row.summary


def test_settings_unsaved_value_does_not_infer_that_a_file_write_was_attempted():
    row = present_event(event('settings.recognition.completed', '요청 형식 오류',
                              category='오류', level='ERROR', saved=False,
                              runtime_applied=False, runtime_status='failed'))
    assert '파일 저장 미완료' in row.summary
    assert '파일 저장 실패' not in row.summary


def test_known_recognition_emotion_and_stt_status_values_are_readable():
    emotion = present_event(event('perception.emotion.applied', '외부 감정 반영',
                                  category='사용자 인식', label='happy', confidence=0.88))
    listening = present_event(event('stt.status', '음성 인식 상태', category='사용자 인식',
                                    status='STT listening'))
    assert '인식 감정 기쁨' in emotion.summary
    assert '상태 음성 입력 대기' in listening.summary
    assert dict(emotion.sections)['인식 감정'] == 'happy'
    assert dict(listening.sections)['상태'] == 'STT listening'


def test_user_text_that_matches_semantic_values_is_never_translated():
    row = present_event(event('dialogue.input_accepted', '사용자 입력 접수', category='대화·AI',
                              text='happy listening', source='typed'))
    assert 'happy listening' in row.summary
    assert dict(row.sections)['문장'] == 'happy listening'


def test_tts_elapsed_milliseconds_remain_visible_with_synthesis_details():
    row = present_event(event('tts.synthesis_completed', '음성 합성 완료', category='대화·AI',
                              elapsed_ms=124.7, audio_seconds=2.3, sample_rate=44100, pcm_bytes=202860))
    assert '소요 시간 124.7ms' in row.summary
    assert '오디오 길이(초) 2.3' in row.summary
    assert ('샘플레이트(Hz)', '44100') in row.sections


def test_unknown_event_and_nested_data_remain_visible_without_dropping_fields():
    row = present_event(event('future.component.result', '새로운 작업 결과',
                              state='weird_state', new_data={'nested': ['a', 'z-last']}, count=27))
    assert row.domain == '시스템'
    assert row.action == '새로운 작업 결과'
    assert 'weird_state' in row.summary
    assert 'z-last' in full_text(row)
    assert dict(row.sections)['횟수'] == '27'


def test_empty_event_and_malformed_non_dictionary_data_are_safe_to_present():
    empty = present_event(event('', ''))
    malformed = present_event(SimpleNamespace(event='unknown', message='', data=['raw', {'answer': 4}],
                                             category='unrecognized', level='INFO'))
    assert empty.action == '기록'
    assert empty.summary == '추가 내용 없음'
    assert malformed.domain == '시스템'
    assert 'answer' in full_text(malformed)


def test_secrets_are_never_unredacted_by_previews_or_sections():
    secret = 'presentation-test-secret-1234567'
    register_secret(secret)
    row = present_event(event('gemini.http_failed', secret, category='오류', level='ERROR',
                              source_category='대화·AI', error=secret,
                              body=f'GET https://example.invalid/?key={secret}',
                              payload={'api_key': secret, 'contents': [{'text': 'retain this text'}]}))
    assert secret not in repr(row)
    assert '[REDACTED]' in full_text(row)
    assert 'retain this text' in full_text(row)
